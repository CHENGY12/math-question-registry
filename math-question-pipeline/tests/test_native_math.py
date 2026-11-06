"""Prevent silent OMML loss and delimiter-based corruption of complete source tags."""
from pathlib import Path
import sys
import tempfile
import unittest
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from lib import xkw_docx as adapter


class NativeMathTests(unittest.TestCase):
    def extract(self, equation):
        with tempfile.TemporaryDirectory(prefix='native-math-test-') as temporary:
            root = Path(temporary)
            source = root / 'fixture.docx'
            document = ('<w:document xmlns:w="' + adapter.NS['w'] + '" xmlns:m="' + adapter.NS['m'] + '">'
                        '<w:body><w:p><w:r><w:t>before</w:t></w:r>' + equation +
                        '<w:r><w:t>after</w:t></w:r></w:p></w:body></w:document>')
            with ZipFile(source, 'w') as archive:
                archive.writestr('word/document.xml', document)
                archive.writestr('word/_rels/document.xml.rels', '<Relationships/>')
            return adapter.extract_docx(source, root / 'out')[0]

    def test_flat_native_equation_is_kept_in_order_with_original_xml(self):
        blocks = self.extract('<m:oMath><m:r><m:t>BM</m:t></m:r><m:r><m:t>⟂</m:t></m:r><m:r><m:t>AQ</m:t></m:r></m:oMath>')
        self.assertEqual(blocks[0]['text_with_image_refs'], 'beforeBM⟂AQafter')
        token = blocks[0]['tokens'][1]
        self.assertEqual(token['native_math']['status'], 'supported_flat_text')
        self.assertIn('<m:t>BM</m:t>', token['native_math']['original_xml'])
        adapter.require_reviewed_native_math(blocks)

    def test_structured_equation_is_explicit_and_cannot_be_published(self):
        blocks = self.extract('<m:oMath><m:f><m:num><m:r><m:t>1</m:t></m:r></m:num><m:den><m:r><m:t>3</m:t></m:r></m:den></m:f></m:oMath>')
        self.assertIn('原生公式待核对', blocks[0]['html'])
        self.assertNotIn('before13after', blocks[0]['text_with_image_refs'])
        self.assertIn('<m:f>', blocks[0]['tokens'][1]['native_math']['original_xml'])
        with self.assertRaisesRegex(ValueError, 'needs review'):
            adapter.require_reviewed_native_math(blocks)

    def test_corrupt_source_character_is_never_guessed(self):
        blocks = self.extract('<m:oMath><m:r><m:t>��(x+2)≥0</m:t></m:r></m:oMath>')
        self.assertEqual(blocks[0]['tokens'][1]['native_math']['reason'], 'source_text_damaged')
        with self.assertRaises(ValueError):
            adapter.require_reviewed_native_math(blocks)

    def test_zero_omml_output_shape_is_unchanged(self):
        blocks = self.extract('')
        self.assertEqual(blocks, [{'body_index': 0, 'kind': 'paragraph', 'text_with_image_refs': 'beforeafter',
            'tokens': [{'kind': 'text', 'text': 'before'}, {'kind': 'text', 'text': 'after'}], 'html': '<p>beforeafter</p>'}])

    def test_internal_delimiter_preserves_complete_knowledge_names(self):
        names = ['指数幂的化简、求值', '对数的运算']
        question = {'source_tags': [{'name': name, 'kind': 'knowledge'} for name in names]}
        self.assertEqual(adapter.word_knowledge_names('、'.join(names), question), names)
        question['word_knowledge_names'] = names
        self.assertEqual(adapter.word_knowledge_names('、'.join(names), question), names)
        with self.assertRaises(ValueError):
            adapter.word_knowledge_names('指数幂的化简、求值、其他', question)

    def test_ambiguous_or_unknown_knowledge_boundary_is_blocked(self):
        question = {'source_tags': [{'name': name, 'kind': 'knowledge'} for name in ['A', 'B', 'A、B']]}
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            adapter.word_knowledge_names('A、B', question)


if __name__ == '__main__':
    unittest.main()
