import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import hashlib
import fitz
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))
from paper_translation.exporter import export_pdf, _clean_region

class ExporterTests(unittest.TestCase):
    def test_reflow_vector_chinese_and_no_hidden_body(self):
        with tempfile.TemporaryDirectory() as root:
            source, dest = Path(root)/'source.pdf', Path(root)/'target.pdf'
            d=fitz.open(); p=d.new_page()
            p.insert_text((40,40),'SECRET OUTSIDE SOURCE BODY')
            p.draw_rect(fitz.Rect(100,100,300,220),color=(0,0,1),fill=(.9,.95,1))
            p.insert_text((110,140),'Figure 1. Preserved caption')
            d.save(source); d.close()
            blocks=[{'blockId':'b1','type':'body','text':'original','translate':True},
                    {'blockId':'a1','type':'asset','translate':False,'sources':[{'page':1,'bbox':[90,90,310,230]}]}]
            report=export_pdf(source,blocks,{'b1':'这是中文译文。 This is translated text. '*120},'zh',dest,{})
            with fitz.open(dest) as result:
                text=''.join(p.get_text() for p in result)
                self.assertIn('这是中文译文',text)
                self.assertIn('Figure 1',text)
                self.assertNotIn('SECRET',text)
                self.assertGreaterEqual(len(result),2)
            self.assertEqual(report['assets'][0]['outputBbox'][2]-report['assets'][0]['outputBbox'][0],220)
            with self.assertRaisesRegex(ValueError,'OUTPUT_PATH_CONFLICT'):
                export_pdf(source,blocks,{'b1':'again'},'zh',dest,{})

    def test_inline_formula_and_citation(self):
        with tempfile.TemporaryDirectory() as root:
            source, dest = Path(root)/'source.pdf', Path(root)/'target.pdf'
            d=fitz.open(); p=d.new_page(); p.insert_text((100,110),'x + y = 2')
            d.save(source);d.close()
            blocks=[{'blockId':'b1','type':'body','text':'','translate':True,'protected':{
                '{{MATH_1}}':{'kind':'math','page':1,'bbox':[98,96,160,115],'baseline':110},
                '{{CITE_1}}':{'kind':'literal','text':'[1]'}}}]
            report=export_pdf(source,blocks,{'b1':'公式 {{MATH_1}} 成立 {{CITE_1}}。'},'zh',dest,{})
            with fitz.open(dest) as result:
                text=result[0].get_text(); self.assertIn('x + y = 2',text);self.assertIn('[1]',text)
                self.assertNotIn('{{',text)
            self.assertEqual(report['assets'][0]['kind'],'inlineMath')

    def test_invalid_language_and_missing_text(self):
        with self.assertRaisesRegex(ValueError,'TARGET_LANGUAGE_UNSUPPORTED'):
            export_pdf('absent.pdf',[],{},'ar','out.pdf',{})

    def test_clipped_image_preserved_outside_image_removed_and_source_unchanged(self):
        with tempfile.TemporaryDirectory() as root:
            source, dest = Path(root)/'source.pdf', Path(root)/'target.pdf'
            with fitz.open() as doc:
                page = doc.new_page(width=400, height=400)
                page.insert_text((20, 35), 'OUTSIDE SEARCHABLE SOURCE BODY')
                inside = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 10, 10), False)
                inside.clear_with(80)
                page.insert_image(fitz.Rect(100, 100, 300, 300), pixmap=inside)
                xref = page.get_contents()[-1]
                stream = doc.xref_stream(xref)
                # Display only the image's top-left quarter; raw image geometry
                # still extends through the rest of the page.
                doc.update_stream(xref, b'q\n100 200 100 100 re W n\n'+stream+b'\nQ\n')
                outside = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 17, 17), False)
                outside.clear_with(220)
                page.insert_image(fitz.Rect(20, 300, 70, 350), pixmap=outside)
                doc.save(source)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            with fitz.open(source) as doc:
                clean, rect = _clean_region(doc, {'page':1, 'bbox':[99,99,201,201]})
                try:
                    self.assertEqual(clean._paper_sanitization['appearance'], 'exact')
                    self.assertEqual(clean._paper_sanitization['removedOutsideImageObjects'], 1)
                    self.assertNotIn('OUTSIDE', clean[0].get_text())
                    self.assertNotIn((17,17), [(x[2],x[3]) for x in clean[0].get_images()])
                finally:
                    clean.close()
            blocks=[{'blockId':'a','type':'asset','translate':False,
                     'sources':[{'page':1,'bbox':[99,99,201,201]}]}]
            report=export_pdf(source,blocks,{},'en',dest,{})
            self.assertEqual(report['validation']['assetAppearanceBeforePlacement'], 'exact')
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), digest)
            with fitz.open(dest) as doc:
                self.assertNotIn('OUTSIDE', ''.join(p.get_text() for p in doc))

    def test_shared_image_xref_with_visible_occurrence_is_preserved(self):
        with fitz.open() as doc:
            page=doc.new_page(width=400,height=400)
            image=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,10,10),False)
            image.clear_with(80)
            xref=page.insert_image(fitz.Rect(100,100,200,200),pixmap=image)
            page.insert_image(fitz.Rect(250,250,350,350),xref=xref)
            clean,_=_clean_region(doc,{'page':1,'bbox':[99,99,201,201]})
            try:
                self.assertEqual(clean._paper_sanitization['removedOutsideImageObjects'],0)
                self.assertEqual(clean._paper_sanitization['appearance'],'exact')
            finally:
                clean.close()

    def test_actual_resource_pixel_loss_is_still_rejected(self):
        original=fitz.Page.apply_redactions
        def damaged(page, **kwargs):
            # Simulate a sanitizer regression that erases part of a kept asset.
            page.draw_rect(fitz.Rect(120,120,145,145),color=None,fill=(1,1,1))
            return original(page, **kwargs)
        with fitz.open() as doc:
            page=doc.new_page(width=400,height=400)
            page.draw_rect(fitz.Rect(100,100,200,200),color=None,fill=(0,0,1))
            with patch.object(fitz.Page,'apply_redactions',damaged):
                with self.assertRaisesRegex(ValueError,'Sanitization changed the asset appearance'):
                    _clean_region(doc,{'page':1,'bbox':[99,99,201,201]})

if __name__=='__main__':unittest.main()
