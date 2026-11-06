"""Batch-end contracts. Every input, output and fake Drive lives in TemporaryDirectory."""
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import pipeline
from lib import question_backup as backup
from test_backup import canonical, digest, write_json, validate_fixture, render_fixture
from test_runner import FixtureAdapter


class BatchBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='batch-backup-test-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.output=self.root/'published';self.output.mkdir()
        self.input=self.root/'input';self.input.mkdir()
        self.sync=self.root/'fake Drive';self.sync.mkdir()
        self.config={'version':1,'provider':'google_drive_desktop','mode':'batch_end',
            'operator_alias':'operator_a','batch_id':'batch_01','sync_root':str(self.sync),
            'subfolder':'math-batches','max_attempts':1}
        self.config_path=self.input/'inputs/backup.json'
        write_json(self.config_path,self.config)
        source,image,graph=b'source DOCX fixture',b'image fixture',b'{"nodes":[]}'
        self.resources={'originals/source.docx':source,'assets/figure.png':image,'raw/graph.json':graph}
        for name,data in self.resources.items():
            path=self.output/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        self.questions=[]
        for qid in ['1','2']:
            self.questions.append({'id':'xkw_gzsx_'+qid,
                'source':{'question_id':qid,'original_file':'originals/source.docx','original_sha256':digest(source)},
                'assets':[{'path':'assets/figure.png','sha256':digest(image)}],
                'alignment':{'graph_file':'raw/graph.json','graph_sha256':digest(graph)},
                'content':{'transcription':{'teacher_review':'pending'}},
                'answer':{'independent_verification':'not_independently_verified'},
                'presentation':{'review_status':'pending_teacher_review','stem':'Synthetic fixture'},
                'solution_guide':{'review_status':'pending_teacher_review','one_sentence':'Check conditions.'}})
        write_json(self.output/'raw/job-manifest.json',{'question_ids':['1','2'],
            'access_token':'DO_NOT_EXPORT_TOKEN','account_email':'private@example.com','local_path':'/private/machine'})
        write_json(self.output/'machine-config.json',{'secret':'DO_NOT_EXPORT_MACHINE'})
        for target,attribute,value in [(backup.pipeline_lib,'validate_question',validate_fixture),
                (backup.pipeline_lib,'render_bank',render_fixture)]:
            mocked=patch.object(target,attribute,side_effect=value);mocked.start();self.addCleanup(mocked.stop)
        mocked=patch.object(pipeline,'load_lib',return_value=SimpleNamespace(validate_question=validate_fixture))
        mocked.start();self.addCleanup(mocked.stop)
        self.publish('first-run')

    def publish(self,run_id):
        for q in self.questions:write_json(self.output/'questions'/(q['id']+'.json'),q)
        data=b''.join(canonical(q)+b'\n' for q in self.questions)
        (self.output/'questions.jsonl').write_bytes(data)
        (self.output/'preview.html').write_bytes(b'<html>All two fixture questions</html>')
        write_json(self.output/'question.schema.json',{'type':'object','required':['id']})
        write_json(self.output/'coverage.json',{'teacher_approved_covered_node_ids':[]})
        write_json(self.output/'validation.json',{'result':'PASS_FOR_LOCAL_PIPELINE',
            'question_count':len(self.questions),'schema_checks':'pass','media_integrity':'pass',
            'failed_job_count':0,'conflicting_question_ids':[],
            'questions_jsonl_sha256':digest(data),'teacher_signoff':'not_inferred_from_pipeline_success'})
        names=list(self.resources)+['raw/job-manifest.json','machine-config.json','questions.jsonl',
            'preview.html','question.schema.json','coverage.json','validation.json']
        names+=['questions/'+q['id']+'.json' for q in self.questions]
        write_json(self.output/'artifacts.json',{'files':{name:digest((self.output/name).read_bytes()) for name in names}})
        write_json(self.output/'run-report.json',{'run_id':run_id,'result':'PASS_FOR_LOCAL_PIPELINE',
            'question_count':len(self.questions),'unique_job_count':2,'unique_manifest_count':2,
            'completed_jobs':2,'failed_jobs':[],'question_conflicts':[],'conflicting_question_count':0,
            'finished_at':run_id,'artifact_index_sha256':digest((self.output/'artifacts.json').read_bytes())})
        write_json(self.output/'.pipeline/owner.json',{'format':pipeline.STATE_VERSION})
        write_json(self.output/'.pipeline/state.json',{'run_id':run_id,'status':'completed',
            'question_count':len(self.questions),'input':str(self.input),'jobs':{
                'job-one':{'status':'completed','question_ids':['xkw_gzsx_1']},
                'job-two':{'status':'completed','question_ids':['xkw_gzsx_2']}}})
        write_json(self.output/'.pipeline/publication-receipt.json',{'run_id':run_id,
            'artifact_index_sha256':digest((self.output/'artifacts.json').read_bytes()),
            'run_report_sha256':digest((self.output/'run-report.json').read_bytes())})

    def stage(self,config=None):
        return backup.backup_batch(self.output,config or self.config)

    def local(self,result):
        return self.output/result['records'][0]['local_zip']

    def remote(self,result):
        return self.sync/result['records'][0]['destination_relative']

    def test_one_complete_portable_archive_and_actual_review_states(self):
        result=self.stage()
        self.assertEqual(result['result'],'STAGED_FOR_SYNC')
        self.assertEqual(result['staged_for_sync'],1)
        self.assertEqual(result['selected_questions'],2)
        self.assertEqual(result['cloud_confirmed'],0)
        self.assertEqual(len(list(self.sync.rglob('*.zip'))),1)
        self.assertEqual(self.local(result).read_bytes(),self.remote(result).read_bytes())
        verified=backup.verify_backup(self.local(result))
        self.assertEqual(verified['question_count'],2)
        self.assertEqual(verified['cloud_confirmation'],'not_performed')
        with ZipFile(self.local(result)) as archive:
            manifest=json.loads(archive.read('backup-manifest.json'))
            self.assertEqual(manifest['question_ids'],['xkw_gzsx_1','xkw_gzsx_2'])
            for row in manifest['questions']:
                self.assertEqual(row['review']['transcription_teacher_review'],'pending')
                self.assertEqual(row['sha256'],digest(archive.read('questions/'+row['question_id']+'.json')))
            for name in ['originals/source.docx','assets/figure.png','raw/graph.json','preview.html',
                         'validation.json','run-report.json','artifacts.json','batch-verification.json']:
                self.assertIn(name,archive.namelist())
            contents=b''.join(archive.read(name) for name in archive.namelist())
            for secret in [b'DO_NOT_EXPORT_TOKEN',b'DO_NOT_EXPORT_MACHINE',b'private@example.com',str(self.root).encode()]:
                self.assertNotIn(secret,contents)
            self.assertFalse(any(name.startswith('.pipeline/') or name.endswith('backup.json') for name in archive.namelist()))

    def test_same_content_idempotent_across_run_ids(self):
        first=self.stage();path=self.local(first);mtime=path.stat().st_mtime_ns
        self.publish('second-run')
        second=self.stage()
        self.assertEqual(second['content_version'],first['content_version'])
        self.assertEqual(second['reused_versions'],1)
        self.assertEqual(path.stat().st_mtime_ns,mtime)
        self.assertEqual(len(list(self.sync.rglob('*.zip'))),1)

    def test_operators_and_batches_have_separate_paths(self):
        results=[self.stage(),self.stage({**self.config,'operator_alias':'operator_b'}),
                 self.stage({**self.config,'batch_id':'batch_02'})]
        self.assertEqual(len({r['records'][0]['destination_relative'] for r in results}),3)
        for result in results:
            expected='math-batches/'+result['operator_alias']+'/'+result['batch_id']+'/'+result['content_version']+'.zip'
            self.assertEqual(result['records'][0]['destination_relative'],expected)
            self.assertTrue((self.sync/expected).is_file())

    def test_missing_or_unsafe_operator_and_batch_are_rejected_before_transfer(self):
        for key in ['operator_alias','batch_id']:
            for value in [None,'','../other','person@example.com']:
                with self.subTest(key=key,value=value),self.assertRaisesRegex(backup.BackupError,key):
                    self.stage({**self.config,key:value})
        self.assertEqual(list(self.sync.iterdir()),[])

    def test_unfinished_job_and_missing_expected_question_block_whole_batch(self):
        state_path=self.output/'.pipeline/state.json'
        state=json.loads(state_path.read_text())
        state['jobs']['job-two']['status']='pending';write_json(state_path,state)
        with self.assertRaisesRegex(backup.BackupError,'not locally complete'):self.stage()
        state['jobs']['job-two']['status']='completed'
        state['jobs']['job-two']['question_ids'].append('xkw_gzsx_missing');write_json(state_path,state)
        with self.assertRaisesRegex(backup.BackupError,'complete configured batch'):self.stage()
        self.assertEqual(list(self.sync.iterdir()),[])
        self.assertFalse((self.output/'.pipeline/backups/batch-archives').exists())

    def test_tampered_file_blocks_before_any_archive_or_drive_write(self):
        (self.output/'assets/figure.png').write_bytes(b'broken')
        result=pipeline.backup_batch(self.output,self.config_path)
        self.assertEqual(result['result'],'BACKUP_BLOCKED')
        self.assertEqual(result['backup_result']['status'],'failed')
        self.assertEqual(list(self.sync.iterdir()),[])
        self.assertFalse((self.output/'.pipeline/backups/batch-archives').exists())

    def test_existing_different_destination_never_overwritten(self):
        first=self.stage();destination=self.remote(first)
        destination.write_bytes(b'other content')
        second=self.stage()
        self.assertEqual(second['result'],'FAILED')
        self.assertEqual(destination.read_bytes(),b'other content')
        self.assertEqual(backup.verify_backup(self.local(first))['result'],'PASS')

    def test_missing_drive_keeps_verified_local_batch_for_retry(self):
        absent=self.root/'not mounted'
        config={**self.config,'sync_root':str(absent)}
        first=self.stage(config)
        self.assertEqual(first['result'],'FAILED');self.assertEqual(first['local_archives'],1)
        self.assertFalse(absent.exists())
        absent.mkdir()
        second=self.stage(config)
        self.assertEqual(second['result'],'STAGED_FOR_SYNC');self.assertEqual(second['reused_versions'],1)

    def test_corrupted_archive_fails_offline_restore(self):
        result=self.stage();broken=self.root/'broken.zip'
        with ZipFile(self.local(result)) as original,ZipFile(broken,'w') as changed:
            for name in original.namelist():
                changed.writestr(name,b'corrupt' if name=='assets/figure.png' else original.read(name))
        with self.assertRaises(backup.BackupError):backup.verify_backup(broken)

    def test_auto_run_only_reports_pending_local_completion(self):
        write_json(self.input/'inputs/batches.json',['inputs/a.json','inputs/b.json'])
        write_json(self.input/'inputs/a.json',{'id':'1','value':'first'})
        write_json(self.input/'inputs/b.json',{'id':'2','value':'second'})
        write_json(self.input/'inputs/guidance.json',{'1':'first','2':'second'})
        args=SimpleNamespace(input=str(self.input),output=str(self.root/'auto-output'),workers=2,preview_limit=100,max_attempts=1)
        with patch.object(pipeline,'load_lib',return_value=FixtureAdapter()),\
             patch.object(backup,'backup_batch') as whole,patch.object(backup,'backup_questions') as individual,\
             patch.object(backup,'_copy_to_sync') as transfer:
            result=pipeline.run(args)
        whole.assert_not_called();individual.assert_not_called();transfer.assert_not_called()
        self.assertEqual(result['backup_result']['status'],'pending_local_completion')
        self.assertFalse(pipeline.backup_incomplete(result['backup_result']))
        self.assertEqual(list(self.sync.iterdir()),[])
        self.assertEqual(pipeline.status(args.output)['backup']['last_operation']['status'],'pending_local_completion')

    def test_batch_mode_cannot_fall_back_to_per_question_or_select_subset(self):
        result=backup.backup_questions(self.output,self.config)
        self.assertEqual(result['status'],'pending_local_completion')
        rejected=pipeline.backup(self.output,self.config_path,['xkw_gzsx_1'])
        self.assertEqual(rejected['backup_result']['result'],'FAILED')
        self.assertEqual(list(self.sync.iterdir()),[])

    def test_explicit_batch_cli_and_existing_backup_dispatch(self):
        with patch.object(sys,'argv',['pipeline.py','backup-batch','--output',str(self.output),'--config',str(self.config_path)]),redirect_stdout(io.StringIO()) as stream:
            self.assertEqual(pipeline.main(),0)
        first=json.loads(stream.getvalue())
        self.assertEqual(first['backup_result']['staged_for_sync'],1)
        second=pipeline.backup(self.output,self.config_path)
        self.assertEqual(second['backup_result']['reused_versions'],1)
        self.assertEqual(len(list(self.sync.rglob('*.zip'))),1)

    def test_default_mode_still_stages_individual_archives(self):
        config={k:v for k,v in self.config.items() if k not in ['mode','operator_alias','batch_id']}
        result=backup.backup_questions(self.output,config)
        self.assertEqual(result['result'],'STAGED_FOR_SYNC')
        self.assertEqual(result['staged_for_sync'],2)
        self.assertEqual(len(list(self.sync.rglob('*.zip'))),2)


if __name__=='__main__':unittest.main()
