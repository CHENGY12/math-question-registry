"""Backup contracts with isolated temporary folders and a tiny deterministic adapter.

No Google Drive account, real sync directory, credentials, or network is accessed.
Real question/schema/rendering integration is exercised by the CLI trial separately.
"""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from lib import question_backup as backup


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(canonical(value)+b'\n')


def validate_fixture(q,root):
    for a in q['assets']:
        if digest((root/a['path']).read_bytes())!=a['sha256']:
            raise ValueError('image mismatch')
    if digest((root/q['source']['original_file']).read_bytes())!=q['source']['original_sha256']:
        raise ValueError('source mismatch')
    if digest((root/q['alignment']['graph_file']).read_bytes())!=q['alignment']['graph_sha256']:
        raise ValueError('graph mismatch')


def render_fixture(questions,root,preview_limit=100):
    data=('<html><body>'+questions[0]['solution_guide']['one_sentence']+'</body></html>').encode()
    (root/'preview.html').write_bytes(data)
    return {'question_count':len(questions),'preview_question_count':1,'preview_sha256':digest(data)}


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='question-backup-test-')
        self.root=Path(self.temp.name).resolve()
        self.output=self.root/'published';self.output.mkdir()
        self.input=self.root/'input';self.input.mkdir()
        self.sync=self.root/'fake existing Drive'/'My Drive';self.sync.mkdir(parents=True)
        self.config={'version':1,'provider':'google_drive_desktop','sync_root':str(self.sync),
                     'subfolder':'教育题库备份/高中数学','max_attempts':2}
        source=b'test source document';image=b'original question image';graph=b'{"nodes":[]}'
        for name,data in [('originals/source.docx',source),('assets/figure.png',image),('raw/graph.json',graph)]:
            path=self.output/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        self.q={'id':'xkw_gzsx_1','source':{'question_id':'1','original_file':'originals/source.docx','original_sha256':digest(source)},
            'alignment':{'graph_file':'raw/graph.json','graph_sha256':digest(graph)},
            'assets':[{'path':'assets/figure.png','sha256':digest(image)}],
            'solution_guide':{'version':'test-guide/1','one_sentence':'先识别条件，再验证结论。'},
            'presentation':{'stem':'已知条件，求结果。'}}
        self.patches=[patch.object(backup.pipeline_lib,'validate_question',side_effect=validate_fixture),
                      patch.object(backup.pipeline_lib,'render_bank',side_effect=render_fixture)]
        for p in self.patches:p.start()
        self.publish('run-one')

    def tearDown(self):
        for p in self.patches:p.stop()
        self.temp.cleanup()

    def publish(self,run_id):
        write_json(self.output/'questions'/f'{self.q["id"]}.json',self.q)
        (self.output/'questions.jsonl').write_bytes(canonical(self.q)+b'\n')
        write_json(self.output/'question.schema.json',{'type':'object','required':['id']})
        write_json(self.output/'validation.json',{'result':'PASS_FOR_LOCAL_PIPELINE','question_count':1,
             'schema_checks':'pass','media_integrity':'pass','questions_jsonl_sha256':digest((self.output/'questions.jsonl').read_bytes())})
        names=['questions.jsonl','questions/'+self.q['id']+'.json','question.schema.json','validation.json',
               'assets/figure.png','originals/source.docx','raw/graph.json']
        write_json(self.output/'artifacts.json',{'files':{name:digest((self.output/name).read_bytes()) for name in names}})
        write_json(self.output/'run-report.json',{'run_id':run_id})
        write_json(self.output/'.pipeline/state.json',{'run_id':run_id,'status':'completed','input':str(self.input)})
        write_json(self.output/'.pipeline/publication-receipt.json',{'run_id':run_id,
             'artifact_index_sha256':digest((self.output/'artifacts.json').read_bytes()),
             'run_report_sha256':digest((self.output/'run-report.json').read_bytes())})

    def run_backup(self,config=None):
        return backup.backup_questions(self.output,config or self.config)

    def local_zip(self,result):
        return self.output/result['records'][0]['local_zip']

    def remote_zip(self,result,sync=None):
        return (sync or self.sync)/result['records'][0]['destination_relative']

    def test_success_restores_and_rerun_ignores_run_id(self):
        first=self.run_backup();self.assertEqual(first['result'],'STAGED_FOR_SYNC')
        self.assertEqual(first['cloud_confirmed'],0)
        local=self.local_zip(first);data=local.read_bytes();modified=local.stat().st_mtime_ns
        self.assertEqual(data,self.remote_zip(first).read_bytes())
        self.assertEqual(backup.verify_backup(local)['restore_check'],'pass')
        with ZipFile(local) as z:
            for name in ['questions.jsonl','questions/xkw_gzsx_1.json','preview.html','question.schema.json','validation.json','backup-manifest.json','originals/source.docx','assets/figure.png','raw/graph.json']:
                self.assertIn(name,z.namelist())
            self.assertNotIn(str(self.output).encode(),b''.join(z.read(n) for n in z.namelist()))
        self.publish('a-new-run-id')
        second=self.run_backup();self.assertEqual(second['reused_versions'],1)
        self.assertEqual(self.local_zip(second),local)
        self.assertEqual(local.stat().st_mtime_ns,modified)

    def test_new_target_reuses_local_but_copies_again(self):
        first=self.run_backup();other=self.root/'second fake Drive';other.mkdir()
        second=self.run_backup({**self.config,'sync_root':str(other)})
        self.assertEqual(second['result'],'STAGED_FOR_SYNC')
        self.assertEqual(second['reused_versions'],1)
        self.assertEqual(self.local_zip(first),self.local_zip(second))
        self.assertTrue(self.remote_zip(second,other).is_file())
        self.assertTrue(self.remote_zip(first).is_file())

    def test_content_revision_keeps_old_version(self):
        first=self.run_backup();old_local=self.local_zip(first);old_remote=self.remote_zip(first)
        self.q['solution_guide']['one_sentence']='补充适用条件与自检。';self.publish('second-run')
        second=self.run_backup()
        self.assertNotEqual(first['records'][0]['version'],second['records'][0]['version'])
        self.assertTrue(old_local.is_file());self.assertTrue(old_remote.is_file())

    def test_missing_sync_root_keeps_local_archive_and_recovers(self):
        missing=self.root/'not mounted';config={**self.config,'sync_root':str(missing)}
        first=self.run_backup(config)
        self.assertEqual(first['result'],'FAILED');self.assertEqual(first['local_archives'],1)
        self.assertFalse(missing.exists());self.assertTrue(self.local_zip(first).is_file())
        missing.mkdir();second=self.run_backup(config)
        self.assertEqual(second['result'],'STAGED_FOR_SYNC');self.assertEqual(second['reused_versions'],1)

    def test_conflicting_destination_is_not_overwritten(self):
        first=self.run_backup();remote=self.remote_zip(first);remote.write_bytes(b'unrelated replacement')
        second=self.run_backup()
        self.assertEqual(second['result'],'FAILED')
        self.assertEqual(remote.read_bytes(),b'unrelated replacement')
        self.assertEqual(backup.verify_backup(self.local_zip(first))['result'],'PASS')
        state=json.loads((self.output/'.pipeline/backups/state.json').read_text())
        record=state['records'][state['latest'][self.q['id']]]
        self.assertEqual(record['status'],'failed');self.assertEqual(record['attempts_this_invocation'],2)

    def test_interrupted_copy_leaves_no_final_and_resumes_owned_partial(self):
        def broken_copy(source,destination,length):
            destination.write(source.read(37));raise OSError('injected transfer interruption')
        config={**self.config,'max_attempts':1}
        with patch.object(backup.shutil,'copyfileobj',side_effect=broken_copy):
            first=self.run_backup(config)
        self.assertEqual(first['result'],'FAILED')
        self.assertFalse(self.remote_zip(first).exists())
        self.assertEqual(len(list(self.sync.rglob('*.pending'))),1)
        second=self.run_backup(config)
        self.assertEqual(second['result'],'STAGED_FOR_SYNC')
        self.assertEqual(backup.verify_backup(self.remote_zip(second))['result'],'PASS')
        self.assertEqual(list(self.sync.rglob('*.pending')),[])

    def test_overlapping_roots_and_symlink_destination_are_rejected(self):
        overlapping=self.run_backup({**self.config,'sync_root':str(self.output)})
        self.assertEqual(overlapping['result'],'FAILED')
        outside=self.root/'outside';outside.mkdir()
        (self.sync/'redirect').symlink_to(outside,target_is_directory=True)
        redirected=self.run_backup({**self.config,'subfolder':'redirect/bank'})
        self.assertEqual(redirected['result'],'FAILED');self.assertEqual(list(outside.iterdir()),[])
        invalid=self.run_backup({**self.config,'subfolder':'../escape'})
        self.assertEqual(invalid['result'],'FAILED')

    def test_only_verified_published_question_enters_archive(self):
        (self.output/'assets/figure.png').write_bytes(b'tampered')
        result=self.run_backup()
        self.assertEqual(result['result'],'FAILED');self.assertEqual(result['local_archives'],0)
        self.assertEqual(list(self.sync.rglob('*.zip')),[])
        unknown=backup.backup_questions(self.output,self.config,['xkw_gzsx_999'])
        self.assertEqual(unknown['result'],'FAILED')

    def test_review_scope_boundaries_and_question_filtering(self):
        review_root=self.root/'trial';index=review_root/'review/review-index.json'
        report=review_root/'revisions/review.json'
        write_json(report,{'review_scope':'独立核验','current_input':'/Users/private/input.json',
          'account_email':'person@example.com','questions':[{'question_id':'1','verdict':'pass'},{'question_id':'2','private_note':'OTHER QUESTION'}]})
        entry={'question_id':'1','annotation':'presentation.json','canonical_sha256':digest(canonical(self.q['presentation'])),
               'independent_review':'../revisions/review.json','teacher_review':'pending'}
        write_json(index,{'records':[entry,{'question_id':'2','annotation':'presentation.json'}],'teacher_signoff':'pending'})
        config={**self.config,'review_index':str(index)}
        limited=self.run_backup(config)
        with ZipFile(self.local_zip(limited)) as z:
            self.assertFalse(any(n.startswith('review/record-') for n in z.namelist()))
        expanded=self.run_backup({**config,'review_root':str(review_root)})
        with ZipFile(self.local_zip(expanded)) as z:
            records=[n for n in z.namelist() if n.startswith('review/record-')]
            self.assertEqual(len(records),1)
            contents=z.read(records[0])
            self.assertNotIn(b'OTHER QUESTION',contents);self.assertNotIn(b'person@example.com',contents)
            self.assertNotIn(b'/Users/private',contents)
            included=json.loads(z.read('review/review-index.json'))
            self.assertEqual(len(included['records']),1)
        outside=self.root/'private.json';write_json(outside,{'secret':'DO NOT COPY'})
        entry['independent_review']='../../private.json';write_json(index,{'records':[entry]})
        escaped=self.run_backup({**config,'review_root':str(review_root)})
        with ZipFile(self.local_zip(escaped)) as z:
            self.assertNotIn(b'DO NOT COPY',b''.join(z.read(n) for n in z.namelist()))

    def test_untrusted_zip_paths_and_corruption_fail_restore(self):
        bad=self.root/'bad.zip'
        with ZipFile(bad,'w') as z:z.writestr('../escape','bad')
        with self.assertRaises(backup.BackupError):backup.verify_backup(bad)
        good=self.run_backup();local=self.local_zip(good)
        broken=self.root/'modified.zip'
        with ZipFile(local) as original,ZipFile(broken,'w') as out:
            for name in original.namelist():out.writestr(name,b'changed' if name=='preview.html' else original.read(name))
        with self.assertRaises(backup.BackupError):backup.verify_backup(broken)
        bad.write_bytes(b'not zip')
        with self.assertRaises(backup.BackupError):backup.verify_backup(bad)


if __name__=='__main__':unittest.main()
