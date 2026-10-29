"""Native resource regions: crops, ruled tables and caption ownership."""
import pathlib
import sys
import unittest

import fitz

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'python'))
from paper_translation.regions import asset_regions, ruled_regions, visible_image_rects, CAPTION_START


def text_blocks(page):
    result = []
    for b in page.get_text('dict')['blocks']:
        if b['type'] != 0:
            continue
        groups = []
        for line in b['lines']:
            group = next((g for g in groups if abs(g[0]['bbox'][0] - line['bbox'][0]) < page.rect.width * .2), None)
            if group is None:
                groups.append([line])
            else:
                group.append(line)
        for lines in groups:
            rect = fitz.Rect(lines[0]['bbox'])
            for line in lines[1:]: rect |= fitz.Rect(line['bbox'])
            text = ' '.join(''.join(s['text'] for s in line['spans']) for line in lines)
            result.append({'text': text, '_rect': rect, '_raw': {**b, 'lines': lines}})
    return result


class RegionsTests(unittest.TestCase):
    def test_native_crop_is_applied_to_image_bounds(self):
        with fitz.open() as doc:
            page = doc.new_page(width=400, height=400)
            pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 10, 10), False)
            pix.clear_with(120)
            page.insert_image(fitz.Rect(100, 100, 300, 300), pixmap=pix)
            xref = page.get_contents()[0]
            stream = doc.xref_stream(xref)
            # Native PDF clip: visible top-left quarter of a larger image.
            doc.update_stream(xref, b'q\n100 200 100 100 re W n\n' + stream + b'\nQ\n')
            self.assertAlmostEqual(page.get_image_info()[0]['bbox'][2], 300)
            regions = visible_image_rects(page)
            self.assertEqual(len(regions), 1)
            self.assertEqual(tuple(regions[0]), (100, 100, 200, 200))

    def test_fraction_and_footnote_rules_are_not_tables(self):
        with fitz.open() as doc:
            page = doc.new_page()
            page.draw_line((100, 100), (160, 100))
            page.draw_line((100, 700), (250, 700))
            self.assertEqual(ruled_regions(page), [])

    def test_adjacent_ruled_tables_remain_independent(self):
        with fitz.open() as doc:
            page = doc.new_page()
            for left, right in [(80, 250), (249, 450)]:
                for y in [100, 120, 160]:
                    page.draw_line((left, y), (right, y))
            page.insert_text((80, 94), 'Table 1: First table', fontsize=9)
            page.insert_text((265, 94), 'Table 2: Second table', fontsize=9)
            regions = asset_regions(page, text_blocks(page), 10)
            self.assertEqual(len(regions), 2)
            self.assertLess(regions[0].x1, 252)
            self.assertGreater(regions[1].x0, 247)

    def test_one_caption_groups_panels_without_nearby_prose(self):
        with fitz.open() as doc:
            page = doc.new_page()
            page.draw_rect(fitz.Rect(100, 100, 200, 200))
            page.draw_rect(fitz.Rect(250, 100, 350, 200))
            page.insert_text((100, 220), 'Figure 1: Two related panels with their original data.', fontsize=10)
            page.insert_text((100, 270), 'Ordinary prose stays separate.', fontsize=11)
            regions = asset_regions(page, text_blocks(page), 10)
            self.assertEqual(len(regions), 1)
            self.assertLess(regions[0].y1, 240)
            self.assertEqual(regions[0].x0, 100)
            self.assertEqual(regions[0].x1, 350)

    def test_prose_reference_to_table_is_not_a_caption(self):
        self.assertIsNone(CAPTION_START.match('Table 1 shows our experimental results.'))
        self.assertIsNotNone(CAPTION_START.match('Table 1: Experimental results.'))

    def test_rotated_axis_label_is_part_of_figure_region(self):
        with fitz.open() as doc:
            page = doc.new_page()
            page.draw_rect(fitz.Rect(150, 150, 350, 250))
            page.insert_text((125, 240), 'Accuracy', fontsize=9, rotate=90)
            page.insert_text((150, 275), 'Figure 2: A chart', fontsize=10)
            regions = asset_regions(page, text_blocks(page), 10)
            self.assertEqual(len(regions), 1)
            self.assertLess(regions[0].x0, 130)


if __name__ == '__main__':
    unittest.main()
