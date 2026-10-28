"""Reproduce a controlled synthetic fixture; translations are hand-authored, not API output."""
import json
from pathlib import Path
import shutil
import sys
import tempfile

import fitz
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))
from paper_translation.jobs import dispatch

ROOT = Path(__file__).resolve().parent
source = ROOT / 'synthetic-paper.pdf'
if source.exists(): source.unlink()
doc = fitz.open()
p = doc.new_page()
p.insert_text((60, 75), 'A Controlled Translation Example', fontsize=18)
p.insert_text((60, 130), 'Abstract', fontsize=13)
p.insert_textbox(fitz.Rect(60, 155, 530, 220),
    'This synthetic paper checks reading order, citation protection, and the preservation of a vector figure. No external research findings are asserted.', fontsize=11)
p.insert_text((60, 245), '1. Method', fontsize=13)
p.insert_textbox(fitz.Rect(60, 270, 530, 325),
    'The source paragraph contains a citation [1]. Translation changes the prose while keeping the citation unchanged.', fontsize=11)
p.draw_rect(fitz.Rect(130, 360, 450, 460), color=(.15, .3, .7), fill=(.94,.97,1))
p.draw_line((160, 435), (420, 435), color=(.15,.3,.7))
p.draw_rect(fitz.Rect(190, 400, 230, 435), color=(.15,.3,.7), fill=(.2,.5,.8))
p.draw_rect(fitz.Rect(300, 380, 340, 435), color=(.15,.3,.7), fill=(.2,.5,.8))
p.insert_text((178, 390), 'Group A', fontsize=10)
p.insert_text((292, 370), 'Group B', fontsize=10)
p.insert_text((130, 482), 'Figure 1. An original vector illustration.', fontsize=10)
p.insert_text((60, 535), '2. Conclusion', fontsize=13)
p.insert_textbox(fitz.Rect(60, 560, 530, 610),
    'The figure and its caption stay in the original language. This example uses fixed translations for reproducible software verification.', fontsize=11)
p.insert_text((60, 660), 'References', fontsize=13)
p.insert_text((60, 690), '[1] Example Author. A synthetic reference. 2026.', fontsize=10)
doc.save(source)
doc.close()
translations = {
'A Controlled Translation Example':'受控翻译示例',
'Abstract':'摘要',
'This synthetic paper':'本文为合成测试论文，用于检查阅读顺序、引用标记保护及矢量图保留功能，不涉及任何外部研究结论。',
'1. Method':'1. 方法',
'The source paragraph':'原文段落包含引用 {{CITE_00001}}。翻译会改变正文语言，同时保持引用标记不变。',
'2. Conclusion':'2. 结论',
'The figure and its caption':'图及其图注保留原文。本示例采用固定译文，便于重复验证软件功能。',
}
with tempfile.TemporaryDirectory() as td:
    config = dict(workDirectory=str(Path(td)/'work'), outputDirectory=str(Path(td)/'output'), allowedInputDirectories=[str(ROOT)])
    def call(tool, **args):
        result = dispatch(dict(tool=tool,args=args,config=config))
        if not result['ok']: raise RuntimeError(json.dumps(result,ensure_ascii=False))
        return result
    prepared=call('pdf_prepare',path=str(source),targetLanguage='zh')
    job_id=prepared['jobId']
    blocks=call('pdf_read_blocks',jobId=job_id)['data']['blocks']
    items=[]
    for block in blocks:
        matches=[v for k,v in translations.items() if block['text'].startswith(k)]
        if len(matches)!=1: raise RuntimeError('Unmapped fixture block: '+block['text'])
        items.append(dict(blockId=block['blockId'],text=matches[0]))
    call('pdf_submit_translations',jobId=job_id,version=prepared['data']['version'],translations=items)
    result=call('pdf_export',jobId=job_id)
    for name,path in result['data']['outputs'].items():
        shutil.copyfile(path,ROOT/name)
    validation=json.loads((ROOT/'validation.json').read_text())
    validation['outputPath']='translated.pdf'
    (ROOT/'validation.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
with fitz.open(ROOT/'translated.pdf') as output:
    output[0].get_pixmap(matrix=fitz.Matrix(1.3,1.3),alpha=False).save(ROOT/'preview.png')
print('Generated controlled synthetic English/Chinese demo and preview.')
