"""Exercise 100-question Word parsing and per-question provenance offline.

The DOCX is a controlled fixture, not 100 downloaded or reviewed source questions.
"""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from xml.sax.saxutils import escape
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from lib import xkw_docx


class MixedSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='math-merged-word-')
        self.root = Path(self.temp.name)
        self.graph = {'version': 'fixture', 'nodes': []}
        (self.root / 'graph.json').write_text(json.dumps(self.graph))
        self.taxonomy = {'dimensions': {'solution_strategies': {'source_dictionary': {}}}}

    def tearDown(self):
        self.temp.cleanup()

    def fixture(self, count=100):
        rows = []
        paragraphs = [f'{i}．计算 {i}+1。' for i in range(1, count + 1)]
        paragraphs.append('参考答案')
        for i in range(1, count + 1):
            paragraphs.extend([f'{i}．{i + 1}', '【难度】0.85', '【知识点】数与式', '【解析】按加法计算。'])
            rows.append({
                'id': str(90000000 + i), 'ordinal': i, 'type': 'fill_blank',
                'type_raw': '填空题', 'subtype_raw': None,
                'difficulty': {'label': '较易', 'coefficient': 0.85, 'normalized': 'low', 'label_3': '简单'},
                'source_tags': [{'kind': 'knowledge', 'name': '数与式', 'url': None}],
                'stem_latex': f'计算 {i}+1。', 'options_latex': [], 'parts_latex': [],
                'answer': {'kind': 'blanks', 'value': [str(i + 1)], 'summary_latex': str(i + 1)},
                'thinking_candidates': [], 'alignments': [], 'gaps': [], 'topic_candidates': [],
                'source_paper': {'title': f'受控来源 {i}', 'province': '江苏',
                                 'city': '南京' if i % 2 else '苏州',
                                 'exam_date': '2024-06-01' if i % 2 else '2026-06-01'}
            })
        body = ''.join('<w:p><w:r><w:t>' + escape(p) + '</w:t></w:r></w:p>' for p in paragraphs)
        with ZipFile(self.root / 'merged.docx', 'w') as z:
            z.writestr('word/document.xml', '<w:document xmlns:w="' + xkw_docx.NS['w'] + '"><w:body>' + body + '</w:body></w:document>')
            z.writestr('word/_rels/document.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')
        return {'source_mode': 'mixed_papers', 'questions': rows,
                'paper': {'title': '批次默认值不应污染单题', 'province': '浙江', 'city': '杭州', 'exam_date': '2019-01-01'},
                'graph_file': 'graph.json', 'graph_origin': 'Controlled fixture',
                'download': {'file': 'merged.docx', 'identity_matching': 'Controlled fixture ordinals'},
                'capture_date': '2026-11-06', 'list_url': 'https://example.invalid/controlled-fixture'}

    def build(self, manifest):
        blocks, assets = xkw_docx.extract_docx(self.root / 'merged.docx', self.root / 'stage')
        guidance = {'version': 'fixture', 'questions': {q['id']: {} for q in manifest['questions']}}
        presentation = {'questions': {q['id']: {} for q in manifest['questions']}}
        return xkw_docx.build_questions(manifest, self.graph, blocks, assets, self.root,
                                        guidance, presentation, self.taxonomy)

    def test_full_100_question_document_keeps_each_source_and_answer(self):
        manifest = self.fixture()
        before = copy.deepcopy(manifest)
        questions = self.build(manifest)
        self.assertEqual(len(questions), 100)
        self.assertEqual(len({q['id'] for q in questions}), 100)
        for i, q in enumerate(questions, 1):
            self.assertEqual(q['source']['paper']['title'], f'受控来源 {i}')
            self.assertEqual(q['source']['download_ordinal'], i)
            self.assertEqual(q['region']['city'], '南京' if i % 2 else '苏州')
            self.assertEqual(q['tags']['year']['values'], [2024 if i % 2 else 2026])
            self.assertEqual(q['answer']['source_blocks'][0]['text_with_image_refs'], f'{i}．{i + 1}')
        self.assertEqual(manifest, before)

    def test_unknown_source_does_not_inherit_batch_defaults(self):
        manifest = self.fixture(2)
        manifest['questions'][1]['source_paper'] = {}
        unknown = self.build(manifest)[1]
        self.assertEqual(unknown['source']['paper'], {})
        self.assertEqual(unknown['region'], {'province': None, 'city': None, 'county': None})
        self.assertEqual(unknown['tags']['year']['values'], [])

    def test_mixed_download_missing_one_source_is_rejected(self):
        manifest = self.fixture()
        del manifest['questions'][99]['source_paper']
        with self.assertRaisesRegex(ValueError, 'every question'):
            self.build(manifest)

    def test_legacy_single_paper_manifest_still_works(self):
        manifest = self.fixture(2)
        del manifest['source_mode']
        for q in manifest['questions']:
            del q['source_paper']
        for q in self.build(manifest):
            self.assertEqual(q['source']['paper'], manifest['paper'])
            self.assertEqual(q['tags']['year']['values'], [2019])

    def test_invalid_source_metadata_is_rejected(self):
        manifest = self.fixture(2)
        manifest['questions'][1]['source_paper'] = None
        with self.assertRaisesRegex(ValueError, 'must be an object'):
            self.build(manifest)

    def test_unknown_source_mode_is_rejected(self):
        manifest = self.fixture(2)
        manifest['source_mode'] = 'misspelled'
        with self.assertRaisesRegex(ValueError, 'source_mode'):
            self.build(manifest)


if __name__ == '__main__':
    unittest.main()
