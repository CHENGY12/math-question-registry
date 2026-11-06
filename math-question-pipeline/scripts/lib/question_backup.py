"""Versioned single-question archives staged in an existing Drive desktop folder.

No Google credentials, APIs or desktop internals are read. A successful copy means
staged_for_sync, never confirmed cloud persistence. The caller owns the output lock.
"""
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import tempfile
from datetime import datetime, timezone
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED, BadZipFile

from . import pipeline_lib

FORMAT = 'question-backup/1'
BATCH_FORMAT = 'question-batch-backup/1'
MAX_REVIEW_BYTES = 8 * 1024 * 1024
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024


class BackupError(ValueError):
    pass


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _relative(value):
    if not isinstance(value, str) or not value or '\\' in value:
        raise BackupError('Expected a nonempty POSIX relative path')
    p = Path(value)
    if not p.parts or p.as_posix()!=value or p.is_absolute() or PureWindowsPath(value).is_absolute() or '..' in p.parts:
        raise BackupError('Path must remain inside its configured root')
    return p


def _inside(root, relative):
    rel = _relative(relative)
    current = root
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise BackupError('Symbolic links are not accepted inside backup paths')
    resolved = current.resolve()
    if root not in resolved.parents:
        raise BackupError('Path escapes its configured root')
    return current


def _mkdir(root, relative):
    if not root.is_dir():
        raise BackupError('Configured root is missing; it will not be created')
    current = root
    for part in _relative(relative).parts:
        current = current / part
        if current.is_symlink():
            raise BackupError('Symbolic-link directory is not accepted')
        current.mkdir(exist_ok=True)  # Deliberately no parents=True: never invent a missing sync root.
        if not current.is_dir():
            raise BackupError('Backup directory is not a directory')
    return current


def _atomic_json(path, value):
    if path.is_symlink():
        raise BackupError('State path cannot be a symbolic link')
    data = _canonical(value) + b'\n'
    with tempfile.NamedTemporaryFile(dir=str(path.parent), prefix='.'+path.name+'.', delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(str(temporary), str(path))
    finally:
        temporary.unlink(missing_ok=True)


def _overlap(a, b):
    return a == b or a in b.parents or b in a.parents


def _checked_config(output, config, publication_state):
    if not isinstance(config, dict) or config.get('version') != 1 or config.get('provider') != 'google_drive_desktop':
        raise BackupError('Backup config needs version 1 and provider google_drive_desktop')
    attempts = config.get('max_attempts', 2)
    if type(attempts) is not int or not 1 <= attempts <= 5:
        raise BackupError('max_attempts must be an integer from 1 to 5')
    raw = Path(config.get('sync_root', '')).expanduser()
    if not config.get('sync_root') or not raw.is_absolute() or raw.is_symlink():
        raise BackupError('sync_root must be an absolute directory path, not a symlink')
    # Missing/offline mounts are handled after the durable local ZIP is prepared.
    sync = raw.resolve()
    _relative(config.get('subfolder', ''))
    destination = _inside(sync, config['subfolder'])
    sources = [output]
    if publication_state.get('input'):
        sources.append(Path(publication_state['input']).expanduser().resolve())
    if any(_overlap(sync, source) or _overlap(destination, source) for source in sources):
        raise BackupError('Backup sync root must not overlap input or output')
    if config.get('review_index'):
        index = Path(config['review_index']).expanduser()
        if not index.is_absolute():
            raise BackupError('review_index must be an explicit absolute path')
        review_root = Path(config.get('review_root', str(index.parent))).expanduser()
        if not review_root.is_absolute() or review_root.is_symlink() or not review_root.is_dir():
            raise BackupError('review_root must be an existing absolute directory')
        review_root = review_root.resolve()
        _review_path(review_root, index)
    else:
        index = review_root = None
    return sync, destination, attempts, index, review_root


def _review_path(root, path):
    # Relative ../revisions references are allowed only with an explicitly broad review_root.
    normalized = Path(os.path.abspath(str(path)))
    try:
        relative = normalized.relative_to(root).as_posix()
    except ValueError as error:
        raise BackupError('Review reference is outside configured review_root') from error
    resolved = _inside(root, relative)
    if resolved.suffix.lower() != '.json' or not resolved.is_file():
        raise BackupError('Review reference must be an existing JSON file')
    if resolved.stat().st_size > MAX_REVIEW_BYTES:
        raise BackupError('Review record exceeds the per-file size limit')
    return resolved


def _scrub(value):
    """Portable review excerpts omit account-bearing fields and local absolute paths."""
    if isinstance(value, dict):
        return {k:_scrub(v) for k,v in value.items()
                if not re.search(r'password|credential|cookie|authorization|token|secret|api.?key|email|account|sync_root', k, re.I)
                and not (isinstance(v,str) and (v.startswith('/') or PureWindowsPath(v).is_absolute()))}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    if isinstance(value, str):
        return re.sub(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', '[redacted-email]', value)
    return value


def _review_files(question, index_path, review_root):
    if index_path is None:
        return {}, ['No review index configured; mathematical or teacher approval is not inferred.']
    qid = question['source']['question_id']
    files, exported, warnings = {}, [], []
    try:
        index = _json(_review_path(review_root,index_path))
    except (OSError, ValueError) as error:
        return {}, ['Review index unavailable: '+type(error).__name__]
    for original in index.get('records', []):
        if str(original.get('question_id')) not in [qid,question['id']]:
            continue
        record = {k:original[k] for k in ['question_id','annotation','canonical_sha256','verdict','teacher_review',
                  'same_as_prior_reviewed_entry','matches_independent_review_hash'] if k in original}
        annotation = record.get('annotation')
        candidates = []
        if annotation == 'presentation.json':
            candidates = [question['presentation']]
        elif annotation == 'learning-guidance.json':
            candidates = [question['solution_guide'], {k:v for k,v in question['solution_guide'].items() if k!='version'}]
        bound = record.get('canonical_sha256') in [_hash(_canonical(candidate)) for candidate in candidates]
        record['binding_status'] = 'matches_current_question' if bound else 'unverified_or_stale'
        if not bound:
            warnings.append('Review binding is stale or unsupported for '+str(annotation))
        reference = original.get('independent_review')
        if reference and bound:
            try:
                target = Path(reference)
                if not target.is_absolute():
                    target = index_path.parent / target
                target = _review_path(review_root,target)
                evidence = _json(target)
                excerpt = _scrub(evidence)
                if isinstance(excerpt,dict) and isinstance(excerpt.get('questions'),list):
                    excerpt['questions'] = [row for row in excerpt['questions']
                        if str(row.get('question_id')) in [qid,question['id']]]
                wrapper = {'format':'question-review-excerpt/1','question_id':question['id'],
                           'source_review_sha256':_digest(target),
                           'export_scope':'Referenced review; question rows filtered; local paths/account fields removed.',
                           'review':excerpt}
                data = _canonical(wrapper)+b'\n'
                name = 'review/record-'+_hash(data)+'.json'
                files[name] = data
                record['included_review'] = name
            except (OSError, ValueError, TypeError) as error:
                record['review_attachment_status'] = 'unavailable'
                warnings.append('Referenced review was not included: '+type(error).__name__)
        elif reference:
            record['review_attachment_status'] = 'not_included_due_to_stale_binding'
        else:
            record['review_attachment_status'] = 'no_direct_reference_in_index'
        exported.append(_scrub(record))
    files['review/review-index.json'] = _canonical({'format':'question-review-binding/1',
        'question_id':question['id'],'records':exported,
        'teacher_signoff':index.get('teacher_signoff','pending'),
        'note':'Only matching index entries and explicitly referenced evidence are included.'})+b'\n'
    if not exported:
        warnings.append('No review-index entries match this question.')
    return files, warnings


def _load_published(output):
    state = _json(_inside(output,'.pipeline/state.json'))
    receipt = _json(_inside(output,'.pipeline/publication-receipt.json'))
    if state.get('status') not in ['completed','incomplete'] or receipt.get('run_id') != state.get('run_id'):
        raise BackupError('Only a completed publication may enter the backup queue')
    if _digest(_inside(output,'artifacts.json')) != receipt.get('artifact_index_sha256'):
        raise BackupError('Publication artifact index checksum differs')
    if _digest(_inside(output,'run-report.json')) != receipt.get('run_report_sha256'):
        raise BackupError('Publication run report checksum differs')
    index = _json(output/'artifacts.json')['files']
    validation = _json(_inside(output,'validation.json'))
    if validation.get('schema_checks') != 'pass' or validation.get('media_integrity') != 'pass':
        raise BackupError('Published question validation did not pass')
    for name in ['validation.json','questions.jsonl','question.schema.json']:
        if _digest(_inside(output,name)) != index.get(name):
            raise BackupError('Published file checksum differs: '+name)
    if _digest(output/'questions.jsonl') != validation.get('questions_jsonl_sha256'):
        raise BackupError('Published question JSONL differs from validation')
    questions = [json.loads(line) for line in (output/'questions.jsonl').read_text().splitlines() if line.strip()]
    if len(questions) != validation.get('question_count') or len({q['id'] for q in questions}) != len(questions):
        raise BackupError('Published question inventory is inconsistent')
    return state, questions, index


def _payload(output, question, published_index, index_path, review_root, staging):
    qid = question['id']
    if not re.fullmatch(r'[a-zA-Z0-9_-]+',qid):
        raise BackupError('Unsafe question ID')
    individual = 'questions/'+qid+'.json'
    if _digest(_inside(output,individual)) != published_index.get(individual) or _json(output/individual) != question:
        raise BackupError('Individual question is not the validated published record')
    pipeline_lib.validate_question(question,output)
    names = {individual,'question.schema.json',question['source']['original_file'],question['alignment']['graph_file']}
    names.update(a['path'] for a in question['assets'])
    files = {}
    for name in sorted(names):
        path = _inside(output,name)
        if _digest(path) != published_index.get(name):
            raise BackupError('Required question resource differs from its published checksum: '+name)
        files[name] = path.read_bytes()
    files[individual] = _canonical(question)+b'\n'
    files['questions.jsonl'] = _canonical(question)+b'\n'
    review_files,warnings = _review_files(question,index_path,review_root)
    files.update(review_files)
    for name,data in files.items():
        path = _inside(staging,name)
        _mkdir(staging,Path(name).parent.as_posix()) if Path(name).parent.as_posix()!='.' else None
        path.write_bytes(data)
    rendering = pipeline_lib.render_bank([question],staging,preview_limit=1)
    files['preview.html'] = (staging/'preview.html').read_bytes()
    files['validation.json'] = _canonical({'format':FORMAT,'result':'PASS_FOR_QUESTION_BACKUP',
        'question_id':qid,'schema_checks':'pass','media_integrity':'pass',
        'questions_jsonl_sha256':_hash(files['questions.jsonl']),
        'rendering':rendering,'review_warnings':warnings,
        'teacher_signoff':'not_inferred_from_backup','cloud_confirmation':'not_performed'})+b'\n'
    manifest_files = {name:{'sha256':_hash(data),'bytes':len(data)} for name,data in sorted(files.items())}
    version = _hash(_canonical({'format':FORMAT,'question_id':qid,'files':manifest_files}))
    manifest = {'format':FORMAT,'question_id':qid,'content_version':version,'files':manifest_files,
        'restore':'Extract to a new empty directory; open preview.html or load questions.jsonl.',
        'cloud_status':'not_confirmed; copying to Drive desktop storage only stages synchronization'}
    files['backup-manifest.json'] = _canonical(manifest)+b'\n'
    return version, files, warnings


def _write_zip(path, files):
    with ZipFile(path,'w',compression=ZIP_DEFLATED,compresslevel=6) as archive:
        for name,data in sorted(files.items()):
            member = ZipInfo(name,date_time=(1980,1,1,0,0,0))
            member.compress_type = ZIP_DEFLATED
            member.external_attr = 0o100644 << 16
            archive.writestr(member,data)


def _batch_identity(config):
    if not isinstance(config, dict) or config.get('mode') != 'batch_end':
        raise BackupError('Batch backup requires mode: batch_end')
    result = []
    for key in ['operator_alias', 'batch_id']:
        value = config.get(key)
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', value):
            raise BackupError(key+' is required: use a nonempty portable identifier (letters, digits, _ or -)')
        if value.upper() in {'CON','PRN','AUX','NUL'} | {'COM'+str(i) for i in range(1,10)} | {'LPT'+str(i) for i in range(1,10)}:
            raise BackupError(key+' cannot be a reserved device name')
        result.append(value)
    return tuple(result)


def pending_batch(config):
    """No sync path access: local automation waits for an explicit batch-end command."""
    operator, batch = _batch_identity(config)
    return {'result':'PENDING_LOCAL_COMPLETION', 'status':'pending_local_completion',
            'mode':'batch_end', 'operator_alias':operator, 'batch_id':batch,
            'staged_for_sync':0, 'local_archives':0, 'cloud_confirmed':0,
            'next_action':'Finish all local work, then run backup-batch --output OUTPUT --config CONFIG.'}


def _review_snapshot(question):
    """Record actual states; a successful archive never manufactures teacher approval."""
    return _scrub({
        'guidance_review_status':question.get('solution_guide',{}).get('review_status','not_recorded'),
        'presentation_review_status':question.get('presentation',{}).get('review_status','not_recorded'),
        'transcription_teacher_review':question.get('content',{}).get('transcription',{}).get('teacher_review','not_recorded'),
        'answer_independent_verification':question.get('answer',{}).get('independent_verification','not_recorded')})


def _manifest_version(manifest):
    keys = (['format','question_id','files'] if manifest.get('format') == FORMAT else
            ['format','operator_alias','batch_id','question_count','question_ids','questions','files'])
    return _hash(_canonical({key:manifest[key] for key in keys}))


def _load_complete_batch(output):
    state, questions, index = _load_published(output)
    report = _json(_inside(output,'run-report.json'))
    validation = _json(_inside(output,'validation.json'))
    jobs = state.get('jobs',{})
    if (state.get('status') != 'completed' or not questions or not jobs
            or any(job.get('status') != 'completed' for job in jobs.values())
            or report.get('result') != 'PASS_FOR_LOCAL_PIPELINE'
            or validation.get('result') != 'PASS_FOR_LOCAL_PIPELINE'
            or report.get('failed_jobs') or report.get('question_conflicts')
            or report.get('conflicting_question_count',0) or validation.get('failed_job_count',0)
            or validation.get('conflicting_question_ids')):
        raise BackupError('Batch is not locally complete: every configured job and all validation must pass')
    expected = {str(qid) for job in jobs.values() for qid in job.get('question_ids',[])}
    ids = {q['id'] for q in questions}
    source_ids = {str(q['source']['question_id']) for q in questions}
    if not expected or (expected != ids and expected != source_ids):
        raise BackupError('Published questions do not cover the complete configured batch')
    if (report.get('question_count') != len(questions) or state.get('question_count') != len(questions)
            or report.get('completed_jobs') != len(jobs) or report.get('unique_job_count') != len(jobs)):
        raise BackupError('Batch completion counts disagree with its job inventory')
    for name, expected_hash in index.items():
        path = _inside(output,name)
        if not path.is_file() or _digest(path) != expected_hash:
            raise BackupError('Published artifact is missing or changed: '+name)
    if {p.name for p in (output/'questions').glob('*.json')} != {qid+'.json' for qid in ids}:
        raise BackupError('Individual question inventory differs from the complete batch')
    for question in questions:
        name = 'questions/'+question['id']+'.json'
        if name not in index or _json(_inside(output,name)) != question:
            raise BackupError('Individual question differs from the verified batch')
        pipeline_lib.validate_question(question,output)
    return state, sorted(questions,key=lambda q:q['id']), index, report, validation


def _batch_payload(output, questions, index, report, validation, operator, batch, review_index, review_root):
    required = {'questions.jsonl','question.schema.json','preview.html','validation.json'}
    for q in questions:
        if not re.fullmatch(r'[A-Za-z0-9_-]+',q['id']):
            raise BackupError('Unsafe question ID')
        required.update(['questions/'+q['id']+'.json',q['source']['original_file']])
        if q.get('alignment',{}).get('graph_file'):
            required.add(q['alignment']['graph_file'])
        required.update(a['path'] for a in q.get('assets',[]))
    if not required.issubset(index):
        raise BackupError('Complete batch lacks a required published resource or preview')
    files, warnings = {}, []
    # Only generated publication materials are eligible. Never sweep input, home,
    # runtime state, backup configuration, caches or other colleagues' directories.
    for name in sorted(index):
        parts = _relative(name).parts
        allowed = (parts[0] in {'questions','assets','originals','raw'} or
                   name in {'questions.jsonl','question.schema.json','preview.html','validation.json','coverage.json','quarantine.json'})
        sensitive = any(part.startswith('.') or re.search(r'backup\.json|credential|password|cookie|token|secret|account',part,re.I) for part in parts)
        if not allowed or sensitive:
            if name in required:
                raise BackupError('Required resource has a nonportable or credential-like path: '+name)
            continue
        path = _inside(output,name)
        if sum(len(value) for value in files.values()) + path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise BackupError('Batch exceeds the archive size limit')
        data = path.read_bytes()
        if _hash(data) != index[name]:
            raise BackupError('Published artifact changed while preparing batch: '+name)
        if parts[0] == 'raw' and name not in required and path.suffix.lower() == '.json':
            data = _canonical(_scrub(json.loads(data)))+b'\n'
        files[name] = data
    # Export a useful, stable run report without timestamps, local paths or host state.
    report_keys = ['result','question_count','unique_job_count','unique_manifest_count',
                   'completed_jobs','failed_jobs','question_conflicts','conflicting_question_count','scope']
    files['run-report.json'] = _canonical(_scrub({k:report[k] for k in report_keys if k in report}))+b'\n'
    rows = []
    for q in questions:
        rows.append({'question_id':q['id'],'source_question_id':str(q['source']['question_id']),
                     'sha256':_hash(files['questions/'+q['id']+'.json']),
                     'canonical_sha256':_hash(_canonical(q)), 'review':_review_snapshot(q)})
        evidence, notes = _review_files(q,review_index,review_root)
        prefix = 'review/questions/'+q['id']+'/'
        for name, data in evidence.items():
            if name == 'review/review-index.json':
                exported = json.loads(data)
                for record in exported.get('records',[]):
                    if record.get('included_review'):
                        record['included_review'] = prefix+record['included_review']
                data = _canonical(exported)+b'\n'
            files[prefix+name] = data
        warnings.extend(q['id']+': '+note for note in notes)
    ids = [q['id'] for q in questions]
    files['batch-verification.json'] = _canonical({'result':'PASS','artifact_integrity':'pass',
        'question_count':len(ids),'question_ids':ids,'all_configured_jobs_completed':True,
        'scope':'This configured local publication only; no other operator or batch is assumed complete.',
        'teacher_signoff':validation.get('teacher_signoff','not_recorded'),
        'cloud_confirmation':'not_performed','review_warnings':warnings})+b'\n'
    files['artifacts.json'] = _canonical({'format':BATCH_FORMAT,
        'files':{name:_hash(data) for name,data in sorted(files.items())}})+b'\n'
    manifest = {'format':BATCH_FORMAT,'mode':'batch_end','operator_alias':operator,'batch_id':batch,
        'question_count':len(ids),'question_ids':ids,'questions':rows,
        'files':{name:{'sha256':_hash(data),'bytes':len(data)} for name,data in sorted(files.items())},
        'teacher_signoff':validation.get('teacher_signoff','not_recorded'),
        'cloud_status':'staged_for_sync_only; independent cloud verification is required for cloud_confirmed',
        'restore':'Extract into a new empty directory; open preview.html or load questions.jsonl.',
        'excluded':'Runtime state, caches, input backup configuration, credentials and machine configuration.'}
    manifest['content_version'] = _manifest_version(manifest)
    files['backup-manifest.json'] = _canonical(manifest)+b'\n'
    if sum(map(len,files.values())) > MAX_ARCHIVE_BYTES:
        raise BackupError('Batch exceeds the archive size limit')
    return manifest['content_version'], files, warnings


def _verify_backup(zip_path):
    """Verify every ZIP member and restore the single question into an isolated directory."""
    path = Path(zip_path).expanduser()
    if path.is_symlink() or not path.is_file():
        raise BackupError('Backup archive must be an existing regular file')
    with ZipFile(path) as archive:
        members = archive.infolist()
        names = [m.filename for m in members]
        if len(names)!=len(set(names)) or sum(m.file_size for m in members)>MAX_ARCHIVE_BYTES:
            raise BackupError('Backup archive has duplicate members or exceeds the size limit')
        for member in members:
            _relative(member.filename)
            if ((member.external_attr>>16)&0o170000)==0o120000 or member.is_dir():
                raise BackupError('Backup archives may contain regular files only')
        manifest = json.loads(archive.read('backup-manifest.json'))
        if manifest.get('format') not in [FORMAT,BATCH_FORMAT] or set(names)!=set(manifest.get('files',{}))|{'backup-manifest.json'}:
            raise BackupError('Backup ZIP inventory differs from its manifest')
        version = _manifest_version(manifest)
        if version!=manifest.get('content_version'):
            raise BackupError('Backup content version is inconsistent')
        for name,info in manifest['files'].items():
            data=archive.read(name)
            if _hash(data)!=info['sha256'] or len(data)!=info['bytes']:
                raise BackupError('Backup member checksum differs: '+name)
        with tempfile.TemporaryDirectory(prefix='question-backup-restore-') as temporary:
            restored=Path(temporary).resolve()
            for name in manifest['files']:
                target=_inside(restored,name)
                if target.parent!=restored:
                    _mkdir(restored,target.parent.relative_to(restored).as_posix())
                target.write_bytes(archive.read(name))
            questions=[json.loads(line) for line in (restored/'questions.jsonl').read_text().splitlines() if line.strip()]
            if manifest['format'] == FORMAT:
                if len(questions)!=1 or questions[0]['id']!=manifest['question_id']:
                    raise BackupError('Backup must restore exactly the manifest question')
            else:
                _batch_identity(manifest)
                ids = [q['id'] for q in questions]
                if (not ids or sorted(ids)!=manifest['question_ids'] or len(ids)!=len(set(ids))
                        or len(ids)!=manifest['question_count']
                        or {n for n in names if n.startswith('questions/')} != {'questions/'+qid+'.json' for qid in ids}):
                    raise BackupError('Batch archive question inventory differs from its manifest')
                rows = [{'question_id':q['id'],'source_question_id':str(q['source']['question_id']),
                         'sha256':_digest(_inside(restored,'questions/'+q['id']+'.json')),
                         'canonical_sha256':_hash(_canonical(q)), 'review':_review_snapshot(q)}
                        for q in sorted(questions,key=lambda q:q['id'])]
                if rows != manifest['questions']:
                    raise BackupError('Batch question checksums or review states differ from manifest')
            for q in questions:
                if _json(_inside(restored,'questions/'+q['id']+'.json'))!=q:
                    raise BackupError('Restored individual JSON differs from JSONL')
                pipeline_lib.validate_question(q,restored)
            validation=_json(restored/'validation.json')
            if validation.get('questions_jsonl_sha256')!=_digest(restored/'questions.jsonl'):
                raise BackupError('Restored validation differs from question JSONL')
            if not (restored/'preview.html').is_file() or not (restored/'question.schema.json').is_file():
                raise BackupError('Restored backup lacks preview or schema')
            if manifest['format'] == BATCH_FORMAT:
                if validation.get('result')!='PASS_FOR_LOCAL_PIPELINE' or validation.get('question_count')!=len(questions):
                    raise BackupError('Batch archive does not contain passing local validation')
                if manifest.get('teacher_signoff') != validation.get('teacher_signoff','not_recorded'):
                    raise BackupError('Batch teacher review state differs from local validation')
    identity = ({'question_id':manifest['question_id']} if manifest['format']==FORMAT else
                {key:manifest[key] for key in ['operator_alias','batch_id','question_count','question_ids']})
    return {'result':'PASS',**identity,'content_version':version,
            'zip_sha256':_digest(path),'member_count':len(names),'restore_check':'pass',
            'cloud_confirmation':'not_performed'}


def verify_backup(zip_path):
    """Public offline verification API; malformed archives fail with BackupError."""
    try:
        return _verify_backup(zip_path)
    except BackupError:
        raise
    except (OSError,ValueError,KeyError,TypeError,BadZipFile,RuntimeError) as error:
        raise BackupError('Invalid or unrestorable backup archive: '+type(error).__name__) from error


def _copy_to_sync(local, sync, subfolder, filename, record, persist):
    """Single-coordinator File Provider transfer: verify a resumable temp, then rename.

    No hard links are required. Multi-machine writers to the same destination are
    outside this contract; an existing final archive is always checked before rename.
    """
    destination_dir=_mkdir(sync,subfolder)
    target=_inside(sync,subfolder+'/'+filename)
    expected=_digest(local)
    if target.exists():
        if not target.is_file() or _digest(target)!=expected:
            raise BackupError('Existing same-name destination differs; it was not overwritten')
        verify_backup(target)
        return target,True
    identity=_hash(str(sync).encode('utf-8'))
    transfer=record.get('transfer',{})
    if (transfer.get('sync_identity')==identity and transfer.get('zip_sha256')==expected
            and transfer.get('relative_path')):
        temporary=_inside(sync,transfer['relative_path'])
    else:
        with tempfile.NamedTemporaryFile(dir=str(destination_dir),prefix='.'+filename+'.',suffix='.pending',delete=False) as stream:
            temporary=Path(stream.name)
        record['transfer']={'sync_identity':identity,'zip_sha256':expected,
                            'relative_path':temporary.relative_to(sync).as_posix()}
        persist()
    # Only our recorded private transfer may be resumed, and only if every byte
    # already written matches the local verified ZIP. Unknown final files never resume.
    if temporary.exists():
        if not temporary.is_file() or temporary.stat().st_size>local.stat().st_size:
            raise BackupError('Recorded partial transfer is not a valid archive prefix')
        with temporary.open('rb') as partial,local.open('rb') as original:
            for block in iter(lambda:partial.read(1024*1024),b''):
                if original.read(len(block))!=block:
                    raise BackupError('Recorded partial transfer differs; it was not overwritten')
        offset=temporary.stat().st_size
    else:
        # A file removed by the sync client can be recreated at the same owned path.
        offset=0
    flags=os.O_WRONLY|os.O_APPEND|os.O_CREAT|getattr(os,'O_NOFOLLOW',0)
    descriptor=os.open(str(temporary),flags,0o600)
    with os.fdopen(descriptor,'ab') as dest,local.open('rb') as source:
        source.seek(offset)
        shutil.copyfileobj(source,dest,1024*1024)
        dest.flush();os.fsync(dest.fileno())
    if _digest(temporary)!=expected:
        raise BackupError('Copied archive checksum differs')
    verify_backup(temporary)
    # Recheck immediately before the same-directory atomic move. The caller owns
    # the local output lock; the configured destination requires one coordinator.
    target=_inside(sync,subfolder+'/'+filename)
    if target.exists():
        if target.is_file() and _digest(target)==expected:
            return target,True
        raise BackupError('Destination appeared during copy; it was not overwritten')
    os.rename(str(temporary),str(target))
    verify_backup(target)
    record.pop('transfer',None)
    persist()
    return target,False


def backup_questions(output_root, config, question_ids=None):
    """Backup verified published questions; caller must hold the output's exclusive lock."""
    if isinstance(config,dict) and config.get('mode') == 'batch_end':
        if question_ids is not None:
            raise BackupError('batch_end cannot select individual questions')
        return pending_batch(config)
    if isinstance(config,dict) and config.get('mode','per_question') != 'per_question':
        raise BackupError('Backup mode must be per_question or batch_end')
    raw=Path(output_root).expanduser()
    if raw.is_symlink() or not raw.is_dir():
        raise BackupError('Output root must be an existing directory, not a symlink')
    output=raw.resolve()
    backup_root=_mkdir(output,'.pipeline/backups')
    state_path=_inside(output,'.pipeline/backups/state.json')
    state=_json(state_path) if state_path.is_file() else {'version':1,'provider':'google_drive_desktop','records':{},'latest':{}}
    if state.get('version')!=1 or state.get('provider')!='google_drive_desktop':
        raise BackupError('Existing backup state has an incompatible format')
    summary={'result':'FAILED','status':'failed','selected_questions':0,'staged_for_sync':0,
             'failed':0,'pending':0,'cloud_confirmed':0,'local_archives':0,'reused_versions':0,
             'records':[],'errors':[],'warnings':[]}
    try:
        publication,questions,published_index=_load_published(output)
        sync,destination,max_attempts,index,review_root=_checked_config(output,config,publication)
        available={q['id']:q for q in questions}
        selected=list(available) if question_ids is None else list(dict.fromkeys(question_ids))
        if any(qid not in available for qid in selected):
            raise BackupError('Selected question IDs must belong to the verified publication')
    except (OSError,ValueError,KeyError,TypeError,BadZipFile) as error:
        summary['errors'].append(str(error));summary['failed']=1
        state['last_error']={'message':str(error),'updated_at':_now()}
        _atomic_json(state_path,state)
        return summary
    summary['selected_questions']=len(selected)
    if not selected:
        summary.update(result='NOTHING_TO_BACK_UP',status='nothing_to_back_up')
        return summary
    for qid in selected:
        record=None
        try:
            with tempfile.TemporaryDirectory(prefix='build-',dir=str(backup_root)) as temporary:
                version,files,warnings=_payload(output,available[qid],published_index,index,review_root,Path(temporary).resolve())
                key=qid+'/'+version
                local_relative='.pipeline/backups/archives/'+qid+'/'+version+'.zip'
                filename=qid+'/'+version+'.zip'
                record=state['records'].setdefault(key,{'question_id':qid,'version':version,
                    'status':'pending','attempts_total':0,'local_zip':local_relative})
                state['latest'][qid]=key
                record.update(status='pending',warnings=warnings,destination_relative=config['subfolder']+'/'+filename,updated_at=_now())
                _atomic_json(state_path,state)
                directory=_mkdir(output,'.pipeline/backups/archives/'+qid)
                local=_inside(output,local_relative)
                existed=local.exists()
                if existed:
                    verified=verify_backup(local)
                    if verified['content_version']!=version:
                        raise BackupError('Existing local archive has a different content version')
                    summary['reused_versions']+=1
                else:
                    temporary_zip=Path(temporary)/'archive.zip'
                    _write_zip(temporary_zip,files)
                    verified=verify_backup(temporary_zip)
                    if local.exists():
                        raise BackupError('Local archive appeared unexpectedly; it was not overwritten')
                    os.rename(str(temporary_zip),str(local))  # caller holds the output lock
                record.update(zip_sha256=verified['zip_sha256'],status='pending',local_verified=True)
                summary['local_archives']+=1
                _atomic_json(state_path,state)
                last_error=None
                for attempt in range(max_attempts):
                    record['attempts_total']+=1
                    record['attempts_this_invocation']=attempt+1
                    _atomic_json(state_path,state)
                    try:
                        target,reused=_copy_to_sync(local,sync,config['subfolder']+'/'+qid,version+'.zip',record,lambda:_atomic_json(state_path,state))
                        record.update(status='staged_for_sync',last_error=None,updated_at=_now(),destination_reused=reused)
                        last_error=None
                        break
                    except (OSError,ValueError,BadZipFile) as error:
                        last_error=str(error)
                        record.update(status='pending',last_error=last_error,updated_at=_now())
                        _atomic_json(state_path,state)
                if last_error is not None:
                    record.update(status='failed',last_error=last_error)
                    summary['failed']+=1;summary['errors'].append(qid+': '+last_error)
                else:
                    summary['staged_for_sync']+=1
                summary['warnings'].extend(qid+': '+warning for warning in warnings)
                _atomic_json(state_path,state)
                summary['records'].append({k:record.get(k) for k in ['question_id','version','status','local_zip','zip_sha256','destination_relative','last_error']})
        except (OSError,ValueError,KeyError,TypeError,BadZipFile) as error:
            summary['failed']+=1;summary['errors'].append(qid+': '+str(error))
            if record is not None:
                record.update(status='failed',last_error=str(error),updated_at=_now())
            else:
                state.setdefault('question_failures',{})[qid]={'status':'failed','last_error':str(error),'updated_at':_now()}
            _atomic_json(state_path,state)
    if summary['failed']:
        summary.update(result='PARTIAL' if summary['staged_for_sync'] else 'FAILED',status='partial' if summary['staged_for_sync'] else 'failed')
    else:
        summary.update(result='STAGED_FOR_SYNC',status='staged_for_sync')
    state['last_summary']={k:v for k,v in summary.items() if k!='records'}
    state['updated_at']=_now();state.pop('last_error',None)
    _atomic_json(state_path,state)
    return summary


def backup_batch(output_root, config):
    """Explicit batch-end transfer, under the caller's exclusive output lock.

    Only the current operator/batch publication is evaluated. Other colleagues'
    directories, jobs and configurations are never consulted or finalized.
    """
    operator, batch = _batch_identity(config)
    raw = Path(output_root).expanduser()
    if raw.is_symlink() or not raw.is_dir():
        raise BackupError('Output root must be an existing directory, not a symlink')
    output = raw.resolve()
    publication, questions, published_index, report, validation = _load_complete_batch(output)
    sync, destination, max_attempts, review_index, review_root = _checked_config(output,config,publication)
    version, files, warnings = _batch_payload(output,questions,published_index,report,validation,
                                             operator,batch,review_index,review_root)
    root = _mkdir(output,'.pipeline/backups')
    state_path = _inside(output,'.pipeline/backups/batches.json')
    state = _json(state_path) if state_path.is_file() else {'version':1,'format':BATCH_FORMAT,'records':{},'latest':{}}
    if state.get('version')!=1 or state.get('format')!=BATCH_FORMAT:
        raise BackupError('Existing batch backup state has an incompatible format')
    scope = operator+'/'+batch
    key = scope+'/'+version
    relative = '.pipeline/backups/batch-archives/'+key+'.zip'
    destination_relative = config['subfolder']+'/'+key+'.zip'
    record = state['records'].setdefault(key,{'operator_alias':operator,'batch_id':batch,
        'version':version,'content_version':version,'question_count':len(questions),
        'question_ids':[q['id'] for q in questions],'attempts_total':0,'local_zip':relative})
    state['latest'][scope] = key
    record.update(status='pending',destination_relative=destination_relative,updated_at=_now())
    _atomic_json(state_path,state)
    persist = lambda:_atomic_json(state_path,state)
    summary = {'result':'FAILED','status':'failed','mode':'batch_end','operator_alias':operator,
        'batch_id':batch,'content_version':version,'selected_questions':len(questions),
        'question_ids':[q['id'] for q in questions],'staged_for_sync':0,'cloud_confirmed':0,
        'local_archives':0,'reused_versions':0,'failed':0,'pending':0,'errors':[],
        'warnings':warnings,'records':[]}
    try:
        _mkdir(output,'.pipeline/backups/batch-archives/'+scope)
        local = _inside(output,relative)
        if local.exists():
            verified = verify_backup(local)
            if verified['content_version'] != version:
                raise BackupError('Existing local batch archive has a different content version')
            summary['reused_versions'] = 1
        else:
            with tempfile.TemporaryDirectory(prefix='batch-build-',dir=str(root)) as temporary:
                pending = Path(temporary)/'archive.zip'
                _write_zip(pending,files)
                verified = verify_backup(pending)
                if local.exists():
                    raise BackupError('Local batch archive appeared unexpectedly; it was not overwritten')
                os.rename(str(pending),str(local))
        summary['local_archives'] = 1
        record.update(zip_sha256=verified['zip_sha256'],local_verified=True)
        persist()
        last_error = None
        for attempt in range(max_attempts):
            record['attempts_total'] += 1
            record['attempts_this_invocation'] = attempt+1
            persist()
            try:
                target, reused = _copy_to_sync(local,sync,config['subfolder']+'/'+scope,
                    version+'.zip',record,persist)
                record.update(status='staged_for_sync',last_error=None,destination_reused=reused,updated_at=_now())
                summary.update(result='STAGED_FOR_SYNC',status='staged_for_sync',staged_for_sync=1)
                last_error = None
                break
            except (OSError,ValueError,BadZipFile) as error:
                last_error = str(error)
                record.update(status='pending',last_error=last_error,updated_at=_now())
                persist()
        if last_error is not None:
            raise BackupError(last_error)
    except (OSError,ValueError,KeyError,TypeError,BadZipFile) as error:
        record.update(status='failed',last_error=str(error),updated_at=_now())
        summary.update(result='FAILED',status='failed',failed=1)
        summary['errors'].append(str(error))
    summary['records'] = [{k:record.get(k) for k in ['operator_alias','batch_id','content_version',
        'question_count','question_ids','status','local_zip','zip_sha256','destination_relative','last_error']}]
    state['last_summary'] = {k:v for k,v in summary.items() if k!='records'}
    persist()
    return summary
