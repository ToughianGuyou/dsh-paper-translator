"""Synthetic, human-labelled reading order and classification regressions."""
import pathlib
import sys
import tempfile
import unittest

import fitz

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'python'))
from paper_translation.parser import parse_pdf


class ParserTests(unittest.TestCase):
    def test_appendix_after_references_becomes_translatable_again(self):
        def build(doc):
            p=doc.new_page()
            p.insert_text((60,80),'References',fontsize=14)
            p.insert_text((60,120),'[1] Example Author. A preserved reference.',fontsize=11)
            p=doc.new_page()
            p.insert_text((60,80),'Supplementary information',fontsize=14)
            p.insert_text((60,120),'This supplementary paragraph must be translated.',fontsize=11)
            p.insert_text((60,170),'A Extended derivations',fontsize=14)
            p.insert_text((60,210),'The derivation explains the mathematical assumptions.',fontsize=11)
        r=self.parse(build)
        self.assertFalse(r['issues'],r['issues'])
        self.assertFalse(r['blocks'][1]['translate'])
        self.assertTrue(all(b['translate'] for b in r['blocks'][2:]))

    def test_single_column_not_inferred_from_author_columns(self):
        def build(doc):
            p=doc.new_page(width=600,height=800)
            p.insert_text((50,80),'Alice Smith',fontsize=11)
            p.insert_text((350,80),'Peter Jones',fontsize=11)
            p.insert_text((60,140),'Abstract',fontsize=14)
            p.insert_textbox(fitz.Rect(60,180,540,270),
                'This is a single column paragraph spanning the center of the page. '
                'Its reading order must not be inferred from the short author cells.',fontsize=11)
        r=self.parse(build)
        self.assertFalse(r['issues'],r['issues'])
        self.assertTrue(any(b['translate'] and 'single column' in b['text'] for b in r['blocks']))

    def test_arxiv_margin_stamp_is_furniture_but_other_rotated_text_stops(self):
        def build(doc):
            p=doc.new_page()
            p.insert_text((25,500),'arXiv:2006.11239v2  [cs.LG]  16 Dec 2020',rotate=90,fontsize=10)
            p.insert_text((60,140),'A normal paragraph contains readable text.',fontsize=11)
        r=self.parse(build)
        self.assertFalse(r['issues'],r['issues'])
        self.assertTrue(any(w['code']=='ARXIV_MARGIN_STAMP' for w in r['warnings']))
        def unknown(doc):
            p=doc.new_page();p.insert_text((100,500),'Important rotated body prose',rotate=90,fontsize=10)
        self.assertTrue(self.parse(unknown)['issues'])

    def parse(self, build):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / 'paper.pdf'
            doc = fitz.open()
            build(doc)
            doc.save(path)
            doc.close()
            return parse_pdf(path)

    def test_reference_heading_in_left_column_applies_in_column_reading_order(self):
        def build(doc):
            p = doc.new_page(width=600, height=800)
            p.insert_text((40, 90), 'Left body paragraph with full discussion.', fontsize=11)
            p.insert_text((320, 90), 'Right reference entry continues here.', fontsize=11)
            p.insert_text((40, 180), 'References', fontsize=14)
            p.insert_text((40, 215), '[1] First original reference entry.', fontsize=11)
            p.insert_text((320, 215), '[2] Second original reference entry.', fontsize=11)
        result = self.parse(build)
        self.assertFalse(result['issues'], result['issues'])
        blocks = result['blocks']
        self.assertEqual([b['type'] for b in blocks], ['body','reference','reference','reference','reference'])
        self.assertEqual([b['text'] for b in blocks][-2:],
                         ['Right reference entry continues here.', '[2] Second original reference entry.'])
        # Column reading order is left-first: right top belongs to references once
        # the reference section starts on the left, independent of vertical y.

    def test_spanning_reference_heading_keeps_both_body_columns_before_it(self):
        def build(doc):
            p = doc.new_page(width=600, height=800)
            p.insert_text((40, 100), 'Left body paragraph with full discussion.', fontsize=11)
            p.insert_text((320, 100), 'Right body paragraph continues here.', fontsize=11)
            p.insert_text((255, 200), 'References', fontsize=16)
            p.insert_text((40, 240), '[1] First original reference entry.', fontsize=11)
            p.insert_text((320, 240), '[2] Second original reference entry.', fontsize=11)
        result = self.parse(build)
        self.assertFalse(result['issues'], result['issues'])
        self.assertEqual([b['type'] for b in result['blocks']],
                         ['body','body','reference','reference','reference'])
        self.assertTrue(all(b['translate'] for b in result['blocks'][:2]))

    def test_front_metadata_and_body_urls(self):
        def build(doc):
            p = doc.new_page()
            p.insert_text((60, 70), 'A Translation Study', fontsize=18)
            p.insert_text((60, 105), 'Alice Smith, Bob Jones', fontsize=11, fontname='hebo')
            p.insert_text((60, 130), 'Department of Science, Example University', fontsize=11)
            p.insert_text((60, 175), 'Abstract', fontsize=14)
            p.insert_text((60, 205), 'Our university uses https://example.org for all experiments.', fontsize=11)
            p.insert_text((60, 240), 'We discuss the DOI metadata in the following paragraph.', fontsize=11)
        result = self.parse(build)
        self.assertFalse(result['issues'], result['issues'])
        blocks = result['blocks']
        self.assertEqual([b['type'] for b in blocks], ['heading','metadata','metadata','heading','body','body'])
        self.assertTrue(all(b['translate'] for b in blocks[-2:]))

    def test_two_footnotes_same_anchor_preserve_citations_and_order(self):
        def build(doc):
            p = doc.new_page()
            x = 60
            for text, size, y in [('The first result',11,180), ('1',7,175),
                                  (' and second result',11,180), ('2',7,175),
                                  (' agree with prior observations [3].',11,180)]:
                p.insert_text((x,y), text, fontsize=size)
                x += fitz.get_text_length(text, fontsize=size)
            p.insert_text((60, 230), 'A second body paragraph provides additional experimental details.', fontsize=11)
            p.insert_text((60, 680), '1 The first explanatory footnote.', fontsize=8)
            p.insert_text((60, 705), '2 The second explanatory footnote.', fontsize=8)
        result = self.parse(build)
        self.assertFalse(result['issues'], result['issues'])
        blocks=result['blocks']
        self.assertEqual([b['type'] for b in blocks], ['body','footnote','footnote','body'])
        anchor=blocks[0]
        self.assertEqual([b['anchorBlockId'] for b in blocks[1:3]], [anchor['blockId']]*2)
        self.assertEqual([p['text'] for p in anchor['protected'].values()], ['1','2','[3]'])
        self.assertTrue(all('{{FN_' in b['text'] for b in blocks[1:3]))


if __name__ == '__main__':
    unittest.main()
