import sys
from pathlib import Path
import tempfile
import unittest
import fitz
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))
from paper_translation.exporter import export_pdf

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

if __name__=='__main__':unittest.main()
