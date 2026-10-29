"""Opt-in regression against a user-provided, unmodified real PDF.

No paper is copied into the repository. Set DDPM_FIXTURE_PATH to the arXiv v2
file (SHA-256 checked below) to run these real-paper assertions locally.
"""
import collections
import hashlib
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'python'))
from paper_translation.parser import parse_pdf


@unittest.skipUnless(os.environ.get('DDPM_FIXTURE_PATH'),'DDPM_FIXTURE_PATH not provided')
class DdpmRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path=Path(os.environ['DDPM_FIXTURE_PATH'])
        cls.digest=hashlib.sha256(cls.path.read_bytes()).hexdigest()
        if cls.digest!='aee5e07a802e8dfd2a386374c94fd61d1d056cb7e1e0fec4f28e8120ff5d8505':
            raise AssertionError('Fixture must be the exact unmodified arXiv v2 PDF')
        cls.result=parse_pdf(cls.path)

    def test_reference_mode_ends_before_appendix(self):
        for page in [13,14,15,16]:
            blocks=[b for b in self.result['blocks'] if b['sources'][0]['page']==page]
            self.assertTrue(any(b['translate'] for b in blocks),page)
            self.assertFalse(any(b['type']=='reference' for b in blocks),page)
        refs=[b for b in self.result['blocks'] if b['type']=='reference']
        self.assertTrue(refs)
        self.assertTrue(all(9<=b['sources'][0]['page']<=12 for b in refs))

    def test_no_false_columns_captions_or_rotated_chart_blockers(self):
        messages=[i['message'] for i in self.result['issues']]
        for word in ['column content','Caption has no','Vertical or rotated','Mathematical expression']:
            self.assertFalse(any(word in m for m in messages),messages)

    def test_all_pages_accounted_and_input_unchanged(self):
        self.assertEqual(self.result['pages'],25)
        self.assertEqual({s['page'] for b in self.result['blocks'] for s in b['sources']},set(range(1,26)))
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),self.digest)
        ids=[b['blockId'] for b in self.result['blocks']]
        self.assertEqual(len(ids),len(set(ids)))


if __name__=='__main__':unittest.main()
