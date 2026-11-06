"""Portable adapter boundary used by the resumable local pipeline.

The adapter consumes reviewed metadata. It does not log in, download, invent tags,
or certify mathematics; those activities remain explicit stages in the skill.
"""
import copy
import hashlib
import json
import re
from pathlib import Path, PureWindowsPath

from jsonschema import Draft202012Validator

from . import xkw_docx
from .math_typesetting import MathTypesetter, segments, strings
from .preview_renderer import render_preview, word_media_roles


ADAPTER_VERSION = 'xkw-official-docx/1'


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')


def _safe(root, relative):
    """Require portable relative paths and reject symlink traversal as well."""
    if not isinstance(relative, str) or not relative or '\\' in relative:
        raise ValueError('Expected a nonempty POSIX relative path')
    path = Path(relative)
    if path.is_absolute() or PureWindowsPath(relative).is_absolute() or '..' in path.parts:
        raise ValueError('Path must remain inside its workspace: ' + relative)
    root = Path(root).resolve()
    resolved = (root / path).resolve()
    if root not in resolved.parents:
        raise ValueError('Path escapes its workspace: ' + relative)
    return resolved


def _read_json(root, relative):
    path = _safe(root, relative)
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise ValueError('Cannot read JSON ' + relative + ': ' + str(error)) from error


def _load_inputs(input_root, manifest_relative):
    root = Path(input_root).resolve()
    manifest = _read_json(root, manifest_relative)
    questions = manifest.get('questions')
    if not isinstance(questions, list) or not questions:
        raise ValueError('Manifest must contain at least one question')
    ids = [q.get('id') for q in questions]
    ordinals = [q.get('ordinal') for q in questions]
    if any(not isinstance(qid, str) or not re.fullmatch(r'[0-9]+', qid) for qid in ids):
        raise ValueError('Source question IDs must be decimal strings')
    if len(set(ids)) != len(ids) or len(set(ordinals)) != len(ordinals):
        raise ValueError('Question IDs and document ordinals must each be unique within a manifest')
    if any(type(n) is not int or n < 1 for n in ordinals):
        raise ValueError('Document ordinals must be positive integers')
    if not manifest.get('download', {}).get('identity_matching'):
        raise ValueError('Manifest needs explicit evidence matching source IDs to document ordinals')
    original = _safe(root, manifest['download']['file'])
    if original.suffix.lower() != '.docx':
        raise ValueError('This adapter supports official .docx files only')
    graph_path = _safe(root, manifest['graph_file'])
    graph = _read_json(root, manifest['graph_file'])
    taxonomy = _read_json(root, 'tag-taxonomy.json')
    guidance_all = _read_json(root, 'inputs/learning-guidance.json')
    presentation_all = _read_json(root, 'inputs/presentation.json')
    try:
        guidance = {'version':guidance_all['version'],
                    'questions':{qid:guidance_all['questions'][qid] for qid in ids}}
        presentation = {'version':presentation_all['version'],
                        'questions':{qid:presentation_all['questions'][qid] for qid in ids}}
    except KeyError as error:
        raise ValueError('Missing guidance or edited presentation for question ' + str(error)) from error
    # Download credentials belong to the browser session, not to portable artifacts.
    text = json.dumps(manifest, ensure_ascii=False)
    if re.search(r'(?:[?&](?:access_token|auth_token|token|sessionid|signature)=|cookie=)', text, re.I):
        raise ValueError('Manifest contains a credential or signed URL; keep only stable public provenance')
    dependencies = {
        'manifest':_hash(_canonical(manifest)),
        'original_docx':_hash(original.read_bytes()),
        'knowledge_graph':_hash(graph_path.read_bytes()),
        'tag_taxonomy':_hash(_canonical(taxonomy)),
        'guidance_for_this_document':_hash(_canonical(guidance)),
        'presentation_for_this_document':_hash(_canonical(presentation)),
        'adapter_version':ADAPTER_VERSION,
        'adapter_code':_hash(Path(xkw_docx.__file__).read_bytes()),
        'contract_code':_hash(Path(__file__).read_bytes()),
    }
    return root, manifest, graph, taxonomy, guidance, presentation, dependencies


def describe_job(input_root, manifest_relative):
    """Content-address one document and only its own authored annotations."""
    _, manifest, _, _, _, _, dependencies = _load_inputs(input_root, manifest_relative)
    return {'key':_hash(_canonical(dependencies)),
            'manifest_relative':manifest_relative,
            'question_ids':['xkw_gzsx_' + q['id'] for q in manifest['questions']],
            'dependency_hashes':dependencies,
            'adapter':ADAPTER_VERSION}


def inspect_docx(docx_path, output_root):
    """Expose raw blocks and media before any site ID or authored annotation exists."""
    path = Path(docx_path).resolve()
    if path.suffix.lower() != '.docx' or not path.is_file():
        raise ValueError('inspect_docx requires an existing .docx file')
    root = Path(output_root).resolve()
    root.mkdir(parents=True,exist_ok=True)
    blocks,assets=xkw_docx.extract_docx(path,root)
    roles=word_media_roles(path)
    for rid,asset in assets.items():
        asset['detected_role']=roles.get(rid,'unclassified')
    separators=[i for i,b in enumerate(blocks) if xkw_docx.is_answer_heading(b['text_with_image_refs'])]
    candidate_ordinals=[]
    for block in blocks[:separators[0] if separators else len(blocks)]:
        match=re.match(r'^([1-9][0-9]*)．',block['text_with_image_refs'])
        if match:candidate_ordinals.append(int(match[1]))
    xkw_docx.dump(root/'raw/document-blocks.json',blocks)
    xkw_docx.dump(root/'raw/media-relations.json',assets)
    report={'original_sha256':_hash(path.read_bytes()),'block_count':len(blocks),
            'media_relations':len(assets),'candidate_question_ordinals':candidate_ordinals,
            'answer_boundary_block_indices':separators,
            'source_question_ids':'not_detected; match IDs to ordinals using source evidence',
            'blocks_file':'raw/document-blocks.json','assets_file':'raw/media-relations.json',
            'layout_status':'candidate_supported_layout' if len(separators)==1 else 'manual_adaptation_required'}
    xkw_docx.dump(root/'inspection.json',report)
    return report


def process_job(input_root, description, stage_root):
    """Write one document into its isolated stage; no shared output mutation."""
    current = describe_job(input_root, description['manifest_relative'])
    if current['key'] != description['key']:
        raise ValueError('Inputs changed after scheduling; describe the job again before running')
    root, manifest, graph, taxonomy, guidance, presentation, _ = _load_inputs(
        input_root, description['manifest_relative'])
    stage = Path(stage_root).resolve()
    stage.mkdir(parents=True, exist_ok=True)
    original = _safe(root, manifest['download']['file'])
    original_hash = _hash(original.read_bytes())
    graph_hash = _hash(_safe(root, manifest['graph_file']).read_bytes())
    xkw_docx.atomic_write(stage/'originals'/f'{original_hash}.docx', original.read_bytes())
    xkw_docx.atomic_write(stage/'raw'/f'knowledge-{graph_hash}.json',
                          _safe(root, manifest['graph_file']).read_bytes())
    try:
        blocks, assets = xkw_docx.extract_docx(original, stage)
        questions = xkw_docx.build_questions(manifest, graph, blocks, assets,
                         root, guidance, presentation, taxonomy)
    except (AssertionError, StopIteration, KeyError, ValueError) as error:
        message = str(error) or 'Required question/answer boundary or source metadata was not found'
        raise ValueError('Unsupported or inconsistent official DOCX: ' + message) from error
    roles = word_media_roles(original)
    for q in questions:
        drawing_ids = {t['relationship_id'] for b in q['content']['source_blocks']
                       for t in b['tokens'] if t['kind']=='image'
                       and roles.get(t['relationship_id'])=='diagram'}
        declared_ids = {f['relationship_id'] for f in q['content']['figures']}
        if not drawing_ids <= declared_ids:
            raise ValueError('Stem drawings lack figure metadata for ' + q['id'] + ': '
                             + ', '.join(sorted(drawing_ids-declared_ids)))
        validate_question(q, stage)
        xkw_docx.dump(stage/'questions'/f'{q["id"]}.json', q)
    if describe_job(input_root,description['manifest_relative'])['key'] != current['key']:
        raise ValueError('Inputs changed during processing; discard this stage and reschedule')
    xkw_docx.atomic_write(stage/'questions.jsonl', b''.join(
        json.dumps(q, ensure_ascii=False, sort_keys=True).encode('utf-8')+b'\n' for q in questions))
    xkw_docx.dump(stage/'raw'/f'{current["key"]}-blocks.json', blocks)
    xkw_docx.dump(stage/'raw'/f'{current["key"]}-manifest.json', manifest)
    return {'question_ids':[q['id'] for q in questions], 'question_count':len(questions)}


def question_schema():
    schema = xkw_docx.build_schema()
    text = {'type':'string','minLength':1}
    options = {'type':'array','items':{'type':'object','required':['key','content'],
               'properties':{'key':{'type':'string','pattern':'^[A-Z]$'},'content':text},
               'additionalProperties':False}}
    parts = {'type':'array','items':{'type':'object','required':['id','content'],
             'properties':{'id':{'type':'string','pattern':'^[1-9][0-9]*$'},'content':text},
             'additionalProperties':False}}
    for name in ['content','presentation']:
        schema['properties'][name]['properties']['options'] = copy.deepcopy(options)
        schema['properties'][name]['properties']['parts'] = copy.deepcopy(parts)
    # A faithful, already well-edited source may need no presentation correction.
    schema['properties']['presentation']['properties']['changes']['minItems'] = 0
    return schema


_VALIDATOR = Draft202012Validator(question_schema())


def validate_question(q, root):
    """Validate structure, resources, provenance and completeness, not mathematics."""
    errors = list(_VALIDATOR.iter_errors(q))
    if errors:
        first = errors[0]
        location = '.'.join(map(str,first.absolute_path)) or '<question>'
        raise ValueError('Question schema error at ' + location + ': ' + first.message)
    qid = q['id']
    def require(condition, message):
        if not condition:
            raise ValueError(qid + ': ' + message)
    require(qid == 'xkw_gzsx_' + q['source']['question_id'], 'source ID differs from question ID')
    require(_hash(_safe(root,q['source']['original_file']).read_bytes()) == q['source']['original_sha256'],
            'original DOCX checksum differs')
    if 'graph_file' in q['alignment']:
        require(_hash(_safe(root,q['alignment']['graph_file']).read_bytes()) == q['alignment']['graph_sha256'],
                'knowledge graph checksum differs')
    require(q['quality'].get('production_import_ready') is False,
            'local structural validation cannot declare production readiness')
    for field in ['correct_rate','score_rate','used_in_papers']:
        require(q['school_context'][field] is None, 'school statistic must remain unknown: ' + field)
        require(q['tags'][field]['status']=='deferred' and q['tags'][field]['values']==[],
                'school statistic tag must remain deferred: ' + field)
    require(q['school_context']['status']=='deferred', 'school context must remain deferred')
    original = q['content']
    edited = q['presentation']
    part_ids = [part['id'] for part in original['parts']]
    option_ids = [option['key'] for option in original['options']]
    require(len(part_ids)==len(set(part_ids)), 'duplicate part IDs')
    require(len(option_ids)==len(set(option_ids)), 'duplicate option IDs')
    require([part['id'] for part in edited['parts']]==part_ids, 'edited presentation changed part IDs/order')
    require([option['key'] for option in edited['options']]==option_ids, 'edited presentation changed options/order')
    require([route['part_id'] for route in q['solution_guide']['routes']]==(part_ids or [None]),
            'learning guidance must cover every question part in order')
    kind = q['tags']['question_type']['values']
    require(len(kind)==1, 'question type must be unambiguous')
    if q['answer']['kind']=='choice':
        require(bool(option_ids) and set(q['answer']['value'])<=set(option_ids), 'choice answer refers to a missing option')
        if kind[0]=='single_choice':
            require(len(q['answer']['value'])==1, 'single-choice question needs one answer')
    if q['answer']['kind']=='parts':
        require([p['part'] for p in q['answer']['value']]==part_ids, 'answer parts do not match question parts')
    asset_map = {a['relationship_id']:a for a in q['assets']}
    require(len(asset_map)==len(q['assets']), 'duplicate media relationship IDs')
    for asset in q['assets']:
        require(_hash(_safe(root,asset['path']).read_bytes())==asset['sha256'], 'image checksum differs: '+asset['path'])
    for block in original['source_blocks']+q['answer']['source_blocks']+q['explanation']['source_blocks']:
        for token in block['tokens']:
            if token['kind']=='image':
                require(token['relationship_id'] in asset_map, 'unresolved source image')
                require(token['asset']==asset_map[token['relationship_id']]['path'], 'image token points at different asset')
    stem_images = {t['relationship_id'] for b in original['source_blocks'] for t in b['tokens'] if t['kind']=='image'}
    for figure in original['figures']:
        require(figure['relationship_id'] in stem_images, 'figure is not present in the stem')
        asset = asset_map[figure['relationship_id']]
        require(figure['asset']==asset['path'] and figure['sha256']==asset['sha256'], 'figure metadata differs from its asset')
    require((original['visual_dependency']=='required')==bool(original['figures']), 'visual dependency disagrees with figure list')
    knowledge = {t['name'] for t in q['source']['tags_raw'] if t['kind']=='knowledge'}
    require(knowledge==set(q['tags']['syllabus_knowledge']['values']), 'source knowledge labels were lost or added')
    strategies=q['tags']['solution_strategies']
    require(strategies['values']==[i['name'] for i in strategies['items']], 'strategy names differ from typed items')
    origins=[o for i in strategies['items'] for o in i['origins']]
    for raw in q['source']['tags_raw']:
        if raw['kind'] in ['solution_method','competency']:
            require(any(o['evidence']==raw for o in origins), 'source strategy label lost its provenance')
    for item in strategies['items']:
        for origin in item['origins']:
            require(origin['status'] in ['inferred','source_observed','source_normalized'], 'unknown strategy origin')
            require(bool(origin['evidence']), 'strategy origin needs concrete evidence')
    for text in strings({'presentation':edited,'guide':q['solution_guide']}):
        list(segments(text))  # Balanced authoring delimiters; KaTeX validates all formulas on render.


def render_bank(questions, output_root, preview_limit=100):
    """Typeset every question, but cap the self-contained HTML preview size."""
    if type(preview_limit) is not int or preview_limit < 1:
        raise ValueError('preview_limit must be a positive integer')
    root=Path(output_root).resolve()
    all_content=[{'presentation':q['presentation'],'guide':q['solution_guide']} for q in questions]
    typesetter=MathTypesetter(all_content)
    visible=sorted(questions,key=lambda q:not q['content'].get('figures'))[:preview_limit]
    html=render_preview(visible,root,typesetter=typesetter,total_count=len(questions))
    xkw_docx.atomic_write(root/'preview.html',html.encode('utf-8'))
    return {'question_count':len(questions),'preview_question_count':len(visible),
            'preview_limit':preview_limit,'unique_formulas_validated':len(typesetter.cache),
            'strict_math_validated_questions':len(questions),
            'preview_formula_occurrences':html.count('class="katex"'),
            'preview_image_occurrences':len(re.findall(r'<img id="media-',html)),
            'preview_sha256':_hash(html.encode('utf-8')),
            'content_review':'not certified by structural or typesetting checks'}
