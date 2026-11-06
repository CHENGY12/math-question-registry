#!/usr/bin/env python3
"""Strict adapter for Xueke official DOCX layout; metadata is explicitly supplied."""
import hashlib
import html
import io
import json
import re
import os
import tempfile
import datetime
from collections import Counter
from pathlib import Path
from zipfile import ZipFile

from lxml import etree as E
from PIL import Image

ADAPTER_VERSION = "xkw-docx-1"
NS = {
    'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'v': 'urn:schemas-microsoft-com:vml',
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'wp': 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing',
    'm': 'http://schemas.openxmlformats.org/officeDocument/2006/math',
}
DIMENSIONS = ['chapter', 'syllabus_knowledge', 'question_type', 'difficulty',
              'question_category', 'solution_strategies', 'year',
              'correct_rate', 'score_rate', 'used_in_papers']
DIMENSION_NAMES = ['章节', '考纲知识点', '题型', '难度', '题目类别', '解题思路与技巧',
                   '年份', '正确率', '得分率', '已组卷']
DEFERRED_DIMENSIONS = ['correct_rate', 'score_rate', 'used_in_papers']


def _xml(data):
    return E.fromstring(data, E.XMLParser(resolve_entities=False, no_network=True, huge_tree=False))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.'+path.name+'.', delete=False) as f:
        temp_path = Path(f.name)
        f.write(data)
    try:
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def dump(path, value):
    atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode())


def label(values, status, method, evidence, confidence=None):
    return {'values': values, 'status': status, 'method': method,
            'evidence': evidence, 'confidence': confidence,
            'review_status': 'pending_teacher_review', 'version': 'pilot-tags-v2'}


def solution_strategies(question, taxonomy):
    """One user-facing dimension; retain category and evidence for every origin."""
    names = taxonomy['dimensions']['solution_strategies']['source_dictionary']
    entries = {}
    def add(name, category, status, method, evidence, confidence):
        item = entries.setdefault(name, {'name':name, 'categories':[], 'origins':[]})
        if category not in item['categories']:
            item['categories'].append(category)
        origin = {'category':category, 'status':status, 'method':method,
                  'evidence':evidence, 'confidence':confidence,
                  'review_status':'pending_teacher_review'}
        if origin not in item['origins']:
            item['origins'].append(origin)
    for candidate in question['thinking_candidates']:
        add(candidate['name'], candidate.get('category', 'thinking_method'), 'inferred', 'agent_content_review',
            candidate['evidence'], candidate['confidence'])
    for raw in question['source_tags']:
        if raw['kind'] == 'solution_method':
            add(raw['name'], 'technique', 'source_observed', 'source_tag_preserved', raw, 1)
    for raw in question['source_tags']:
        if raw['kind'] == 'competency':
            add(names.get(raw['name'], raw['name']), 'competency', 'source_normalized',
                'ability_name_dictionary_v1', raw, 1)
    statuses = {origin['status'] for item in entries.values() for origin in item['origins']}
    status = 'mixed' if len(statuses) > 1 else next(iter(statuses), 'not_assessed')
    return {**label(list(entries), status, 'merge_typed_tags_v2',
                   '思想方法、具体解题方法与能力标签合并展示；逐项证据见items.origins。'),
            'items':list(entries.values())}


def reserved_statistic():
    return {**label([], 'deferred', 'reserved_field', '按用户要求先留空，后续接入；不作为本轮验收前提。'),
            'review_status':'not_applicable'}


def year_label(question, paper):
    if paper.get('exam_date'):
        try:
            year = datetime.date.fromisoformat(paper['exam_date']).year
        except (TypeError, ValueError) as error:
            raise ValueError('Source exam_date must be an ISO calendar date') from error
        return label([year], 'source_observed', 'source_exam_date', paper['exam_date'], 1)
    if question.get('year') is not None and question.get('year_evidence'):
        return label([question['year']], 'inferred', 'academic_year_and_term', question['year_evidence'], 0.95)
    match = re.fullmatch(r'(\d{4})\s*[-—–]\s*(\d{4})', paper.get('academic_year') or '')
    term = paper.get('term')
    if match and term in ['上学期','下学期','第一学期','第二学期']:
        first, second = map(int,match.groups())
        if second != first + 1:
            raise ValueError('Academic year must contain consecutive calendar years')
        year = first if term in ['上学期','第一学期'] else second
        return label([year], 'inferred', 'academic_year_and_term',
                     paper['academic_year']+'学年'+term+'；具体考试日期未知。', 0.95)
    return label([], 'unavailable', 'source_absent', '未取得可核验的题目年份；不使用下载或更新时间代替。')


def native_math_token(element):
    """Preserve OMML and only display lossless, flat runs; never flatten structures."""
    raw = E.tostring(element, encoding='unicode')
    text = ''.join(element.xpath('.//m:t/text()', namespaces=NS))
    allowed = {'oMath', 'r', 'rPr', 'sty', 'nor', 't'}
    flat = all(child.tag == '{%s}r' % NS['m'] for child in element)
    supported = flat and all(E.QName(node).localname in allowed for node in element.iter()
                             if E.QName(node).namespace == NS['m'])
    damaged = '\ufffd' in text or not text
    status = 'supported_flat_text' if supported and not damaged else 'needs_review'
    reason = 'source_text_damaged' if damaged else 'structured_omml_not_rendered' if not supported else None
    rendered = text if status == 'supported_flat_text' else '【原生公式待核对：' + ('源文字符损坏' if damaged else '结构化公式') + '】'
    return {'kind': 'text', 'text': rendered, 'native_math': {
        'format': 'OMML', 'status': status, 'reason': reason,
        'original_xml': raw, 'original_xml_sha256': sha(raw.encode()),
        'plain_runs_for_diagnostics_only': text,
        'note': 'Original XML is preserved. Structured equations are not flattened into misleading text.'}}


def require_reviewed_native_math(blocks):
    pending = [block['body_index'] for block in blocks for token in block['tokens']
               if token.get('native_math', {}).get('status') == 'needs_review']
    if pending:
        raise ValueError('Native OMML needs review at Word body indices ' + ','.join(map(str, sorted(set(pending))))
                         + '; original XML is preserved in source tokens. Do not publish missing equations.')


def word_knowledge_names(raw, question):
    """Tag names may contain 顿号; use reviewed boundaries or a unique full-name parse."""
    known = [tag['name'] for tag in question['source_tags'] if tag['kind'] == 'knowledge']
    if len(set(known)) != len(known) or any(not name for name in known):
        raise ValueError('Source knowledge names must be nonempty and unique')
    supplied = question.get('word_knowledge_names')
    if supplied is not None:
        if not isinstance(supplied, list) or any(not isinstance(name, str) or not name for name in supplied):
            raise ValueError('word_knowledge_names must contain complete nonempty tag names')
        matches = [supplied]
    else:
        memo = {}
        def parse(position):
            if position == len(raw):
                return [[]]
            if position in memo:
                return memo[position]
            paths = []
            for name in known:
                end = position + len(name)
                if raw.startswith(name, position) and (end == len(raw) or raw[end] == '、'):
                    for tail in parse(end if end == len(raw) else end + 1):
                        paths.append([name] + tail)
                        if len(paths) > 1:
                            break
                if len(paths) > 1:
                    break
            memo[position] = paths
            return paths
        matches = parse(0)
    if len(matches) != 1 or '、'.join(matches[0]) != raw or set(matches[0]) != set(known) or len(matches[0]) != len(known):
        raise ValueError('Word knowledge boundaries are missing, ambiguous or inconsistent; needs manual review')
    if question.get('word_knowledge_raw', raw) != raw:
        raise ValueError('word_knowledge_raw differs from the actual Word metadata')
    return matches[0]


def extract_docx(path, output_root):
    assets = {}
    with ZipFile(path) as z:
        if sum(member.file_size for member in z.infolist()) > 256*1024*1024:
            raise ValueError('DOCX uncompressed size exceeds this adapter limit (256 MiB)')
        rels = _xml(z.read('word/_rels/document.xml.rels'))
        for rel in rels:
            if not rel.get('Type', '').endswith('/image'):
                continue
            assert rel.get('TargetMode') != 'External', 'Remote media requires explicit capture'
            target = rel.get('Target')
            if not target or Path(target).is_absolute() or '..' in Path(target).parts or '\\' in target:
                raise ValueError('Unsupported or unsafe OOXML image target')
            data = z.read('word/' + target)
            asset_path = 'assets/' + sha(data) + Path(target).suffix.lower()
            if not (output_root / asset_path).exists() or sha((output_root / asset_path).read_bytes()) != sha(data):
                atomic_write(output_root / asset_path, data)
            with Image.open(io.BytesIO(data)) as im:
                size = list(im.size)
            assets[rel.get('Id')] = {'path': asset_path, 'sha256': sha(data),
                'original_zip_member': 'word/' + target, 'dimensions_px': size}
        doc = _xml(z.read('word/document.xml'))
        # OLE equation binaries remain in the original archive and are never executed.
        body = doc.find('w:body', NS)
        def inline(element):
            tokens = []
            native = element.findall('.//m:oMath', NS)
            native_children = {child for equation in native for child in equation.iterdescendants()}
            for n in element.iter():
                if n in native_children:
                    continue
                if n.tag == '{%s}oMath' % NS['m']:
                    tokens.append(native_math_token(n))
                elif n.tag == '{%s}t' % NS['w']:
                    tokens.append({'kind': 'text', 'text': n.text or ''})
                elif n.tag in ['{%s}imagedata' % NS['v'], '{%s}blip' % NS['a']]:
                    rid = n.get('{%s}id' % NS['r']) or n.get('{%s}embed' % NS['r'])
                    assert rid in assets, f'Unresolved media {rid}'
                    width = None
                    for ancestor in n.iterancestors():
                        if ancestor.tag == '{%s}shape' % NS['v']:
                            match = re.search(r'(?:^|;)width:([\d.]+)pt', ancestor.get('style', ''))
                            if match:
                                width = round(float(match[1]) * 4 / 3, 2)
                            break
                        if ancestor.tag == '{%s}drawing' % NS['w']:
                            extent = ancestor.find('.//wp:extent', NS)
                            if extent is not None:
                                width = round(int(extent.get('cx')) / 9525, 2)
                            break
                    tokens.append({'kind': 'image', 'relationship_id': rid,
                                   'asset': assets[rid]['path'], 'display_width_px': width})
                elif n.tag == '{%s}br' % NS['w']:
                    tokens.append({'kind': 'text', 'text': '\n'})
            return tokens
        def markup(tokens):
            result = []
            for t in tokens:
                if t['kind'] == 'text':
                    result.append(html.escape(t['text']).replace('\n', '<br>'))
                else:
                    width = t['display_width_px']
                    style = f' style="width:{width}px"' if width else ''
                    result.append(f'<img class="formula" src="{t["asset"]}" alt="原始公式或配图 {t["relationship_id"]}"{style}>')
            return ''.join(result)
        blocks = []
        for idx, el in enumerate(body):
            if el.tag not in ['{%s}p' % NS['w'], '{%s}tbl' % NS['w']]:
                continue
            tokens = inline(el)
            text = ''.join(t['text'] if t['kind'] == 'text' else '[IMAGE:%s]' % t['relationship_id'] for t in tokens)
            if el.tag.endswith('tbl'):
                cells = [inline(c) for c in el.findall('.//w:tr/w:tc', NS)]
                # The source places all four options inside one Word cell.
                if len(cells) == 1:
                    option_cells = []
                    for token in cells[0]:
                        if token['kind'] == 'text' and re.fullmatch(r'\s*[A-D][.．]\s*', token['text']):
                            option_cells.append([])
                        if option_cells:
                            option_cells[-1].append(token)
                    if len(option_cells) == 4:
                        cells = option_cells
                content = '<div class="options">' + ''.join('<div>' + markup(c) + '</div>' for c in cells) + '</div>'
                kind = 'table'
            else:
                content, kind = '<p>' + markup(tokens) + '</p>', 'paragraph'
                option_cells = []
                if tokens and tokens[0].get('text') == 'A．':
                    for token in tokens:
                        if token['kind'] == 'text' and re.fullmatch(r'\s*[A-D][.．]\s*', token['text']):
                            option_cells.append([])
                        if option_cells:
                            option_cells[-1].append(token)
                    if len(option_cells) == 4:
                        content = '<div class="options">' + ''.join('<div>' + markup(c) + '</div>' for c in option_cells) + '</div>'
            blocks.append({'body_index': idx, 'kind': kind, 'text_with_image_refs': text,
                           'tokens': tokens, 'html': content})
        return blocks, assets


def is_answer_heading(text):
    # Official downloads may prefix the heading with a logo and a quoted paper title.
    return re.search(r'参考答案\s*[：:]?\s*$', text) is not None


def split_questions(blocks, manifest):
    separators = [i for i,b in enumerate(blocks) if is_answer_heading(b['text_with_image_refs'])]
    if len(separators) != 1:
        raise ValueError('Expected exactly one 参考答案 boundary; inspect the document before adapting it')
    separator = separators[0]
    result = {}
    for part, candidates in [('question', blocks[:separator]), ('answer', blocks[separator + 1:])]:
        current = None
        for b in candidates:
            text = b['text_with_image_refs']
            match = re.match(r'^([1-9][0-9]*)．', text)
            if match:
                current = int(match[1])
                if part in result.get(current, {}):
                    raise ValueError('Repeated document ordinal in '+part+': '+str(current))
                result.setdefault(current, {})[part] = []
            if re.match(r'^[一二三四五]、', text):
                current = None
            if current is not None:
                result[current][part].append(b)
    if set(result) != {q['ordinal'] for q in manifest['questions']}:
        raise ValueError('Document ordinals do not exactly match the reviewed manifest')
    for parts in result.values():
        assert parts['question'] and parts['answer']
    return result


def build_questions(manifest, graph, blocks, assets, input_root, guidance, presentation, taxonomy):
    source_mode = manifest.get('source_mode', 'single_paper')
    if source_mode not in ['single_paper', 'mixed_papers']:
        raise ValueError('source_mode must be single_paper or mixed_papers')
    if source_mode == 'mixed_papers' and any('source_paper' not in q for q in manifest['questions']):
        raise ValueError('Mixed-paper downloads require source_paper for every question; use {} for unknown metadata')
    split = split_questions(blocks, manifest)
    nodes = {n['id']: n for n in graph['nodes']}
    graph_path = (input_root / manifest['graph_file']).resolve()
    graph_hash = sha(graph_path.read_bytes())
    original_hash = sha((input_root / manifest['download']['file']).read_bytes())
    questions = []
    for m in manifest['questions']:
        # A per-question source is a complete replacement, never a field merge
        # with another paper's school, city or year. An empty dict is unknown.
        paper = m['source_paper'] if 'source_paper' in m else manifest['paper']
        if not isinstance(paper, dict):
            raise ValueError('Source paper metadata must be an object')
        parts = split[m['ordinal']]
        all_blocks = parts['question'] + parts['answer']
        require_reviewed_native_math(all_blocks)
        answer_blocks = parts['answer']
        raw_diff = next(b['text_with_image_refs'].removeprefix('【难度】') for b in answer_blocks if b['text_with_image_refs'].startswith('【难度】'))
        assert float(raw_diff) == m['difficulty']['coefficient']
        knowledge_line = next(b['text_with_image_refs'].removeprefix('【知识点】') for b in answer_blocks if b['text_with_image_refs'].startswith('【知识点】'))
        original_knowledge = word_knowledge_names(knowledge_line, m)
        assert set(original_knowledge) == {t['name'] for t in m['source_tags'] if t['kind'] == 'knowledge'}
        diff_index = next(i for i, b in enumerate(answer_blocks) if b['text_with_image_refs'].startswith('【难度】'))
        knowledge_index = next(i for i, b in enumerate(answer_blocks) if b['text_with_image_refs'].startswith('【知识点】'))
        aligned = []
        for a in m['alignments']:
            assert a['node_id'] in nodes and nodes[a['node_id']]['semantic_available']
            aligned.append({**a, 'node_name': nodes[a['node_id']]['name'],
                            'method': 'agent_semantic_review', 'review_status': 'pending_teacher_review'})
        labels = {
            'chapter': label(m['chapter']['values'], 'source_observed', 'source_paper_title', m['chapter']['evidence'], 1) if m.get('chapter') else label([], 'unavailable', 'source_absent', '未取得教材版本及章节路径；不把站点推荐教材当成本题教材。'),
            'syllabus_knowledge': label(original_knowledge, 'source_observed', 'official_docx_and_browser', '来源知识点原样保留；是否对应适用课程标准条目尚未核验。'),
            'question_type': label([m['type']], 'source_normalized', 'explicit_dictionary', m['type_raw'], 1),
            'difficulty': label([m['difficulty']['normalized']], 'source_normalized', 'source_label_dictionary_v1', m['difficulty']['label'], 1),
            'question_category': label([], 'unavailable', 'source_absent', '未见题目类别；未见标签不等于不属于这些类别。'),
            'solution_strategies': solution_strategies(m, taxonomy),
            'year': year_label(m, paper),
            'correct_rate': reserved_statistic(),
            'score_rate': reserved_statistic(),
            'used_in_papers': reserved_statistic(),
        }
        rids = sorted({t['relationship_id'] for b in all_blocks for t in b['tokens'] if t['kind'] == 'image'}, key=lambda v: int(v[3:]))
        figures = []
        stem_rids = {t['relationship_id'] for b in parts['question'] for t in b['tokens'] if t['kind']=='image'}
        for fig in m.get('figures',[]):
            assert fig['relationship_id'] in stem_rids, 'Stem figure must occur in the question blocks'
            figures.append({**fig, 'asset':assets[fig['relationship_id']]['path'],
                            'sha256':assets[fig['relationship_id']]['sha256'],
                            'dimensions_px':assets[fig['relationship_id']]['dimensions_px']})
        fingerprint_parts = [m['stem_latex'], m['options_latex'], m['parts_latex']]
        if figures:
            fingerprint_parts.append([f['sha256'] for f in figures])
        fingerprint = sha(json.dumps(fingerprint_parts, ensure_ascii=False, sort_keys=True).encode())
        questions.append({
            'schema_version': 'question-bank-pilot/2.1', 'id': 'xkw_gzsx_' + m['id'],
            'subject': '数学', 'stage': '高中', 'region': {key:paper.get(key) for key in ['province','city','county']},
            'source': {'platform':'学科网·组卷网','question_id':m['id'],
                       'url':m.get('source_url','https://zujuan.xkw.com/11q' + m['id'] + '.html'),
                       'url_status':'detail_page_verified' if m.get('source_url') else 'canonical_url_derived_from_source_id; list_page_verified',
                       'verified_list_url':manifest['list_url'], 'paper':paper,
                       'capture_date':manifest['capture_date'], 'capture_date_precision':'day',
                       'updated_at':m.get('source_updated_at'),
                       'original_file':'originals/' + original_hash + '.docx', 'original_sha256':original_hash,
                       'download_ordinal':m['ordinal'], 'identity_evidence':manifest['download']['identity_matching'],
                       'tags_raw':m['source_tags'], 'difficulty_raw':m['difficulty'],
                       'question_type_raw':m['type_raw'], 'subtype_raw':m['subtype_raw'],
                       'rights':{'status':'local_pilot_only','redistribution_license_verified':False}},
            'content': {'stem_latex':m['stem_latex'],'options':m['options_latex'],
                        'parts':m['parts_latex'],'source_blocks':parts['question'],
                        'figures':figures,'visual_dependency':'required' if figures else 'not_marked',
                        'transcription':{'method':'agent_manual_from_source_images','scope':'stem_options_parts_and_answer_summary',
                                         'review':m.get('transcription_review','transcription_supplied; visual_review_not_recorded'),'teacher_review':'pending'},
                        'formula_policy':'source_images_preserved; solution_not_fully_converted_to_latex'},
            'answer': {**m['answer'], 'source_blocks':answer_blocks[:diff_index],
                       'origin':'source_transcribed', 'independent_verification':m.get('answer_verification','not_independently_verified; teacher_signoff_pending')},
            'explanation': {'source_blocks':answer_blocks[knowledge_index+1:],
                            'complete_solution_location':'answer.source_blocks + explanation.source_blocks',
                            'note':'来源答案与解析按原文顺序合并保留；完整解答可能位于难度标签之前。'},
            'solution_guide': {**guidance['questions'][m['id']], 'version':guidance['version']},
            'presentation': presentation['questions'][m['id']],
            'tags': labels,
            'topic_candidates': {'values':m['topic_candidates'],'status':'inferred','textbook_version':None},
            'alignment': {'graph_version':graph['version'],'graph_file':'raw/knowledge-' + graph_hash + '.json','graph_origin':manifest['graph_origin'],'graph_sha256':graph_hash,
                          'matches':aligned,'unmapped':m['gaps'],
                          'status':'partial' if m['gaps'] else 'mapped_pending_review',
                          'coverage_credit':'not_counted_until_review'},
            'school_context': {'school_id':None,'cohort_id':None,'window':None,
                              'correct_rate':None,'correct_count':None,'attempt_count':None,
                              'score_rate':None,'score_sum':None,'max_score_sum':None,
                              'used_in_papers':None,'paper_uses':None,'status':'deferred',
                              'required_for_current_scope':False},
            'assets': [{**assets[r], 'relationship_id':r} for r in rids],
            'deduplication': {'source_key':'xkw:gzsx:' + m['id'],'content_sha256':fingerprint,
                              'variant_group_id':None,'near_duplicate_status':'not_assessed'},
            'quality': {'status':'pilot_review_required','media_complete':True,
                        'production_import_ready':False,'teacher_review':'pending',
                        'limitations':['尚未完成教师签审','教材版本未完整核验','知识点及推断标签待复核'],
                        'deferred_features':['本校正确率','本校得分率','本校已组卷记录']}
        })
    return questions


def build_schema():
    nonempty = {'type':'string','minLength':1}
    arr = {'type':'array'}
    tag = {'type':'object','required':['values','status','method','evidence','confidence','review_status','version'],
           'properties':{'values':arr,'status':{'enum':['unavailable','source_observed','source_normalized','inferred','not_assessed','mixed','deferred']},
                         'method':nonempty,'confidence':{'type':['number','null'],'minimum':0,'maximum':1},'review_status':nonempty,'version':nonempty}}
    tag_properties = {k:tag for k in DIMENSIONS}
    tag_properties['solution_strategies'] = {'allOf':[tag, {
        'required':['items'], 'properties':{
            'values':{'type':'array','items':nonempty,'uniqueItems':True},
            'items':{'type':'array','items':{'type':'object','required':['name','categories','origins'],
                'properties':{'name':nonempty,
                    'categories':{'type':'array','minItems':1,'uniqueItems':True,'items':{'enum':['thinking_method','technique','competency']}},
                    'origins':{'type':'array','minItems':1,'items':{'type':'object','required':['category','status','method','evidence','confidence','review_status']}}}}}
        }}]}
    text_list = {'type':'array','minItems':1,'items':nonempty}
    route = {'type':'object','required':['part_id','label','trigger','goal','why','steps','checkpoint'],
             'properties':{**{k:nonempty for k in ['label','trigger','goal','why','checkpoint']},
                 'part_id':{'type':['string','null']},
                 'steps':{'type':'array','minItems':2,'items':{'type':'object','required':['action','reason'],
                         'properties':{'action':nonempty,'reason':nonempty},'additionalProperties':False}}},
             'additionalProperties':False}
    guide = {'type':'object','required':['version','title','one_sentence','routes','transfer','pitfalls','self_check','origin','review_status'],
             'properties':{'version':{'const':'pilot-learning-v1'},'title':nonempty,'one_sentence':nonempty,
                 'routes':{'type':'array','minItems':1,'items':route},
                 'transfer':{'type':'object','required':['template','conditions'],
                             'properties':{'template':nonempty,'conditions':text_list},'additionalProperties':False},
                 'pitfalls':text_list,'self_check':text_list,'origin':{'const':'agent_authored'},
                 'review_status':{'const':'pending_teacher_review'}},'additionalProperties':False}
    edited = {'type':'object','required':['version','origin','stem_latex','options','parts','answer_summary_latex','changes','source_preserved','review_status'],
              'properties':{'version':{'const':'math-editorial-v1'},'origin':{'const':'editorial_normalization'},
                  'stem_latex':nonempty,'options':arr,'parts':arr,'answer_summary_latex':nonempty,
                  'changes':{'type':'array','minItems':0,'items':{'type':'object','required':['field','before','after','reason'],
                      'properties':{k:nonempty for k in ['field','before','after','reason']},'additionalProperties':False}},
                  'source_preserved':{'const':True},'review_status':{'const':'pending_teacher_review'}},'additionalProperties':False}
    schema = {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':'https://local.invalid/question-bank-pilot-2.1.schema.json',
              'title':'高中数学题目中间格式','type':'object',
              'required':['schema_version','id','subject','stage','region','source','content','answer','explanation','solution_guide','presentation','tags','alignment','school_context','assets','deduplication','quality'],
              'properties':{
                  'schema_version':{'const':'question-bank-pilot/2.1'},'id':{'type':'string','pattern':'^xkw_gzsx_[0-9]+$'},
                  'subject':{'const':'数学'},'stage':{'const':'高中'},
                  'source':{'type':'object','required':['platform','question_id','original_file','original_sha256','tags_raw','difficulty_raw'],
                            'properties':{'original_sha256':{'type':'string','pattern':'^[a-f0-9]{64}$'},'tags_raw':arr,
                                          'difficulty_raw':{'type':'object','required':['label','coefficient','normalized'],
                                                            'properties':{'coefficient':{'type':'number','minimum':0,'maximum':1},'normalized':{'enum':['low','mid','high']}}}}},
                  'content':{'type':'object','required':['stem_latex','options','parts','source_blocks','figures','visual_dependency'],'properties':{'stem_latex':nonempty,'options':arr,'parts':arr,'source_blocks':{'type':'array','minItems':1},'figures':{'type':'array','items':{'type':'object','required':['asset','sha256','role','relationship_id','alt','dimensions_px'],'properties':{'asset':nonempty,'sha256':{'type':'string','pattern':'^[a-f0-9]{64}$'},'role':{'const':'stem_diagram'}}}},'visual_dependency':{'enum':['required','not_marked']}}},
                  'answer':{'type':'object','required':['kind','value','source_blocks'],'properties':{'kind':{'enum':['choice','blanks','parts']},'value':{'type':'array','minItems':1}}},
                  'solution_guide':guide,'presentation':edited,
                  'tags':{'type':'object','required':DIMENSIONS,'properties':tag_properties,'additionalProperties':False},
                  'alignment':{'type':'object','required':['graph_version','graph_sha256','matches','unmapped','status']},
                  'assets':{'type':'array','items':{'type':'object','required':['path','sha256','relationship_id']}},
                  'school_context':{'type':'object','required':['correct_rate','score_rate','used_in_papers','status'],
                                    'properties':{'correct_rate':{'type':['number','null'],'minimum':0,'maximum':1},'score_rate':{'type':['number','null'],'minimum':0,'maximum':1},'used_in_papers':{'type':['boolean','null']}}},
                  'quality':{'type':'object','required':['status','media_complete','production_import_ready']}
              }}
    return schema
