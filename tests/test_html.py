import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

import fitz
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'python'))
from paper_translation.jobs import dispatch
from paper_translation.html_input import permitted_url, snapshot_url


ARTICLE='''<article class="ltx_document"><h1>Structured paper</h1>
<p>The formula <math alttext="x_t=\\sqrt{\\alpha_t}x_0+\\epsilon"><mi>x</mi></math> uses a root and cites <a href="#bib">[1]</a>.</p>
<div class="ltx_equation"><math display="block" alttext="L=\\frac{1}{2}\\sum_{t=1}^{T}x_t^2"><mi>L</mi></math><span class="ltx_tag">(1)</span></div>
<table><caption>Table 1. Original results</caption><tr><th>Method</th><th>Value</th></tr><tr><td>Ours</td><td><math><mi>β</mi><msub><mi>x</mi><mn>0</mn></msub></math></td></tr></table>
<section class="ltx_bibliography"><h2>References</h2><p id="bib">[1] Untranslated Reference.</p></section>
<section><h2>A Appendix</h2><p>Additional details must be translated.</p></section></article>'''


class HtmlTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.path=self.root/'paper.html';self.path.write_text(ARTICLE)
        self.config={'allowedInputDirectories':[str(self.root)],'workDirectory':str(self.root/'work'),'outputDirectory':str(self.root/'out')}
    def tearDown(self):self.tmp.cleanup()
    def call(self,tool,**args):return dispatch({'tool':tool,'args':args,'config':self.config})
    def prepare(self):
        r=self.call('html_prepare',path=str(self.path),targetLanguage='zh')
        self.assertTrue(r['ok'],r);return r

    def test_mathml_latex_restore_appendix_and_export(self):
        before=hashlib.sha256(self.path.read_bytes()).hexdigest();r=self.prepare();j=r['jobId']
        blocks=self.call('pdf_read_blocks',jobId=j)['data']['blocks']
        self.assertTrue(any('Additional details' in b['text'] for b in blocks))
        self.assertFalse(any('Untranslated Reference' in b['text'] for b in blocks))
        self.assertNotIn('sqrt',json.dumps(blocks));self.assertNotIn('protected',blocks[0])
        translations=[{'blockId':b['blockId'],'text':('这是中文测试。 '+b['text'])} for b in blocks]
        self.assertTrue(self.call('pdf_submit_translations',jobId=j,version=r['data']['version'],translations=translations)['ok'])
        ex=self.call('pdf_export',jobId=j);self.assertTrue(ex['ok'],ex)
        paths=ex['data']['outputs']
        from bs4 import BeautifulSoup
        result=BeautifulSoup(Path(paths['translated.html']).read_text(),'html.parser')
        original=BeautifulSoup(ARTICLE,'html.parser')
        self.assertEqual([str(n) for n in result.find_all('math')],[str(n) for n in original.find_all('math')])
        self.assertIn('这是中文测试',result.get_text())
        self.assertIn('Untranslated Reference',result.get_text())
        self.assertEqual(result.find('a')['href'],'#bib')
        self.assertNotIn('{{',str(result))
        self.assertNotIn('translated.pdf',paths)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),before)
        self.assertEqual(self.call('pdf_export',jobId=j)['data']['outputs'],paths)

    def test_missing_formula_marker_is_rejected(self):
        r=self.prepare();bs=self.call('pdf_read_blocks',jobId=r['jobId'])['data']['blocks'];b=next(b for b in bs if b['protectedTokens'])
        x=self.call('pdf_submit_translations',jobId=r['jobId'],version=r['data']['version'],translations=[{'blockId':b['blockId'],'text':'lost all markers'}])
        self.assertEqual(x['code'],'PLACEHOLDER_MISMATCH')

    def test_script_only_math_requires_review(self):
        self.path.write_text('<article><p>Formula <script type="math/tex">x^2</script></p></article>')
        r=self.call('html_prepare',path=str(self.path),targetLanguage='zh')
        self.assertFalse(r['ok']);self.assertEqual(r['code'],'NEEDS_REVIEW')

    def test_inline_formatting_images_and_scripts(self):
        import base64
        image=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
        (self.root/'a.png').write_bytes(image)
        self.path.write_text('<html><head><style>p{color:black}</style></head><body><article><p onclick="bad()">Hello <em>important <strong>word</strong></em>.</p><figure><img src="a.png"><figcaption>A caption</figcaption></figure><script>bad()</script></article></body></html>')
        r=self.prepare();j=r['jobId'];bs=self.call('pdf_read_blocks',jobId=j)['data']['blocks']
        self.assertTrue(any('A caption' in b['text'] for b in bs))
        self.call('pdf_submit_translations',jobId=j,version=r['data']['version'],translations=[{'blockId':b['blockId'],'text':'中文 '+b['text']} for b in bs])
        ex=self.call('pdf_export',jobId=j);self.assertTrue(ex['ok'],ex)
        from bs4 import BeautifulSoup
        doc=BeautifulSoup(Path(ex['data']['outputs']['translated.html']).read_text(),'html.parser')
        self.assertIsNotNone(doc.select_one('em strong'))
        self.assertTrue(doc.img['src'].startswith('data:image/png;base64,'))
        self.assertIsNone(doc.find('script'));self.assertNotIn('onclick',str(doc));self.assertEqual(doc.html['lang'],'zh')

    def test_unsupported_prose_stops_and_translation_cannot_inject_html(self):
        self.path.write_text('<article><div>Uncovered prose</div><p>Supported</p></article>')
        r=self.call('html_prepare',path=str(self.path),targetLanguage='zh')
        self.assertEqual(r['code'],'NEEDS_REVIEW')
        self.path.write_text('<article><p>Hello</p></article>');r=self.prepare();j=r['jobId']
        b=self.call('pdf_read_blocks',jobId=j)['data']['blocks'][0]
        self.call('pdf_submit_translations',jobId=j,version=r['data']['version'],translations=[{'blockId':b['blockId'],'text':'<script>bad()</script> 中文'}])
        ex=self.call('pdf_export',jobId=j);self.assertTrue(ex['ok'],ex)
        from bs4 import BeautifulSoup
        doc=BeautifulSoup(Path(ex['data']['outputs']['translated.html']).read_text(),'html.parser')
        self.assertIsNone(doc.find('script'));self.assertIn('<script>',doc.get_text())

    def test_local_image_paths_are_fenced_and_inputs_rechecked(self):
        (self.root/'sub').mkdir();self.path=self.root/'sub'/'paper.html'
        self.path.write_text('<article><p>Hello</p><img src="../outside.png"></article>')
        (self.root/'outside.png').write_bytes(b'bad')
        try:
            r=self.call('html_prepare',path=str(self.path),targetLanguage='zh');self.assertFalse(r['ok']);self.assertEqual(r['code'],'PATH_NOT_ALLOWED')
        finally:(self.root/'outside.png').unlink()
        self.path.write_text(ARTICLE);r=self.prepare();self.path.write_text(ARTICLE+'changed')
        self.assertEqual(self.call('pdf_read_blocks',jobId=r['jobId'])['code'],'STALE_VERSION')

    def test_remote_urls_are_versioned_and_strictly_allowlisted(self):
        for url in ['http://arxiv.org/html/2006.11239v2','https://localhost/html/2006.11239v2','https://arxiv.org@127.0.0.1/html/2006.11239v2','https://arxiv.org:8080/html/2006.11239v2']:
            with self.assertRaises(ValueError):permitted_url(url)
        with self.assertRaises(ValueError):snapshot_url('https://arxiv.org/html/2006.11239',self.root,self.config)
        with self.assertRaises(ValueError):permitted_url('https://arxiv.org/image.png','ar5iv.labs.arxiv.org')


if __name__=='__main__':unittest.main()
