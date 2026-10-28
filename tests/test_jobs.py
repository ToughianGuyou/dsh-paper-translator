"""Job protocol regression tests; all PDF inputs are generated here."""
import hashlib
import json
import pathlib
import re
import sys
import subprocess
import tempfile
import unittest

import fitz

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'python'))
from paper_translation.jobs import dispatch


class JobsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.source = self.root / 'paper.pdf'
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((60, 70), 'A Translation Study', fontsize=18)
        page.insert_text((60, 140), 'The proposed method improves the observed result [1].', fontsize=11)
        page.insert_text((60, 190), 'A second paragraph preserves the experimental details.', fontsize=11)
        doc.save(self.source)
        doc.close()
        self.config = dict(workDirectory=str(self.root / 'work'), outputDirectory=str(self.root / 'output'),
                           allowedInputDirectories=[str(self.root)], maxBatchSize=50)

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, tool, **args):
        return dispatch(dict(tool=tool, args=args, config=self.config))

    def prepare(self):
        result = self.call('pdf_prepare', path=str(self.source), targetLanguage='zh')
        self.assertTrue(result['ok'], result)
        self.job = result['jobId']
        self.version = result['data']['version']
        return result

    def read(self):
        result = self.call('pdf_read_blocks', jobId=self.job)
        self.assertTrue(result['ok'], result)
        return result['data']['blocks']

    def submit(self, blocks):
        items = [dict(blockId=b['blockId'], text='这是完整的中文译文。' + ''.join(re.findall(r'\{\{[^{}]+\}\}', b['text']))) for b in blocks]
        result = self.call('pdf_submit_translations', jobId=self.job, version=self.version, translations=items)
        self.assertTrue(result['ok'], result)
        return items

    def test_closed_loop_source_hash_and_idempotency(self):
        before = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.prepare()
        items = self.submit(self.read())
        result = self.call('pdf_export', jobId=self.job)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['data']['state'], 'COMPLETED')
        outputs = result['data']['outputs']
        self.assertIn('original.md', outputs)
        with fitz.open(outputs['translated.pdf']) as doc:
            text = ''.join(p.get_text() for p in doc)
            self.assertIn('中文', text)
            self.assertNotIn('{{', text)
            self.assertIn('[1]', text)
        self.assertEqual(before, hashlib.sha256(self.source.read_bytes()).hexdigest())
        duplicate = self.call('pdf_export', jobId=self.job)
        self.assertEqual(outputs, duplicate['data']['outputs'])
        resubmitted = self.call('pdf_submit_translations', jobId=self.job, version=self.version, translations=items)
        self.assertTrue(resubmitted['ok'], resubmitted)
        items[0]['text'] += '修改'
        refused = self.call('pdf_submit_translations', jobId=self.job, version=self.version, translations=items)
        self.assertEqual(refused['code'], 'JOB_COMPLETED')

    def test_markdown_disabled(self):
        self.config['keepOriginalMarkdown'] = False
        self.prepare()
        self.submit(self.read())
        result = self.call('pdf_export', jobId=self.job)
        self.assertTrue(result['ok'], result)
        self.assertNotIn('original.md', result['data']['outputs'])
        self.assertFalse(list((self.root / 'output').rglob('*.md')))

    def test_incomplete_export(self):
        self.prepare()
        result = self.call('pdf_export', jobId=self.job)
        self.assertEqual(result['code'], 'TRANSLATION_INCOMPLETE')
        self.assertFalse((self.root / 'output').exists())

    def test_placeholder_mismatch_is_atomic(self):
        self.prepare()
        blocks = self.read()
        self.assertTrue(any('{{' in b['text'] for b in blocks))
        result = self.call('pdf_submit_translations', jobId=self.job, version=self.version,
                           translations=[dict(blockId=b['blockId'], text='删除了标记') for b in blocks])
        self.assertEqual(result['code'], 'PLACEHOLDER_MISMATCH')
        status = self.call('pdf_job_status', jobId=self.job)
        self.assertEqual(status['data']['accepted'], 0)

    def test_stale_version_and_changed_source(self):
        self.prepare()
        blocks = self.read()
        bad = self.call('pdf_submit_translations', jobId=self.job, version='old',
                        translations=[dict(blockId=blocks[0]['blockId'], text='translation')])
        self.assertEqual(bad['code'], 'STALE_VERSION')
        with self.source.open('ab') as f:
            f.write(b'\n% changed')
        for tool in ['pdf_read_blocks', 'pdf_export', 'pdf_submit_translations']:
            result = self.call(tool, jobId=self.job)
            self.assertEqual(result['code'], 'STALE_VERSION')

    def test_stopped_job_enforced(self):
        self.prepare()
        path = self.root / 'work' / self.job / 'job.json'
        job = json.loads(path.read_text())
        for state in ['NEEDS_REVIEW', 'UNSUPPORTED', 'FAILED']:
            job['state'] = state
            path.write_text(json.dumps(job))
            for tool in ['pdf_read_blocks', 'pdf_submit_translations', 'pdf_export']:
                result = self.call(tool, jobId=self.job)
                self.assertEqual(result['code'], 'JOB_STOPPED')

    def test_duplicate_block_batch_rejected(self):
        self.prepare()
        block = self.read()[0]
        item = dict(blockId=block['blockId'], text=block['text'])
        result = self.call('pdf_submit_translations', jobId=self.job, version=self.version, translations=[item, item])
        self.assertEqual(result['code'], 'INVALID_TRANSLATION')
        self.assertEqual(self.call('pdf_job_status', jobId=self.job)['data']['accepted'], 0)

    def test_resume_skips_accepted_blocks(self):
        self.prepare()
        batch = self.call('pdf_read_blocks', jobId=self.job, limit=1)
        first = batch['data']['blocks']
        self.submit(first)
        remaining = self.read()
        self.assertNotIn(first[0]['blockId'], [b['blockId'] for b in remaining])
        self.assertTrue(all(b.get('readOnly') for b in batch['data']['context']))

    def test_input_boundary_and_job_path_validation(self):
        self.config['allowedInputDirectories'] = [str(self.root / 'different')]
        with self.assertRaisesRegex(ValueError, 'PATH_NOT_ALLOWED'):
            self.call('pdf_prepare', path=str(self.source), targetLanguage='zh')
        with self.assertRaisesRegex(ValueError, 'INVALID_ARGUMENT'):
            self.call('pdf_job_status', jobId='../paper.pdf')

    def test_worker_stdout_is_one_json_document(self):
        worker = pathlib.Path(__file__).resolve().parents[1] / 'python' / 'worker.py'
        def request(tool, **args):
            req = dict(tool=tool, args=args, config=self.config)
            result = subprocess.run([sys.executable, str(worker)], input=json.dumps(req), text=True, capture_output=True, check=True)
            payload = json.loads(result.stdout)
            self.assertTrue(payload['ok'], payload)
            return payload
        prepared = request('pdf_prepare', path=str(self.source), targetLanguage='zh')
        job_id = prepared['jobId']
        blocks = request('pdf_read_blocks', jobId=job_id)['data']['blocks']
        request('pdf_submit_translations', jobId=job_id, version=prepared['data']['version'],
                translations=[dict(blockId=b['blockId'], text='中文译文。' + ''.join(re.findall(r'\{\{[^{}]+\}\}', b['text']))) for b in blocks])
        exported = request('pdf_export', jobId=job_id)
        self.assertEqual(exported['data']['state'], 'COMPLETED')
        self.assertEqual(request('pdf_job_status', jobId=job_id)['data']['state'], 'COMPLETED')

    def test_linked_footnote_translated_after_anchor(self):
        self.source.unlink()
        doc = fitz.open()
        page = doc.new_page()
        prose = 'An observation has an associated explanatory note'
        page.insert_text((60, 160), prose, fontsize=11)
        x = 60 + fitz.get_text_length(prose, fontsize=11)
        page.insert_text((x, 156), '1', fontsize=7)
        page.insert_text((60, 210), 'The second paragraph establishes the document body font.', fontsize=11)
        page.insert_text((60, 690), '1 This note explains the experimental detail.', fontsize=8)
        doc.save(self.source)
        doc.close()
        self.prepare()
        blocks = self.read()
        notes = [b for b in blocks if b['type'] == 'footnote']
        self.assertEqual(len(notes), 1, blocks)
        note = notes[0]
        anchor = next(b for b in blocks if b['blockId'] == note['anchorBlockId'])
        self.assertEqual(note['order'], anchor['order'] + 1)
        self.assertIn('{{FN_', anchor['text'])
        items = [dict(blockId=b['blockId'], text=('脚注说明。' if b['type'] == 'footnote' else '正文段落。') + ''.join(re.findall(r'\{\{[^{}]+\}\}',b['text']))) for b in blocks]
        result = self.call('pdf_submit_translations', jobId=self.job, version=self.version, translations=items)
        self.assertTrue(result['ok'], result)
        result = self.call('pdf_export', jobId=self.job)
        self.assertTrue(result['ok'], result)
        with fitz.open(result['data']['outputs']['translated.pdf']) as output:
            text = ''.join(p.get_text() for p in output)
        self.assertIn('脚注说明', text)
        self.assertNotIn('{{FN_', text)

    def test_scanned_and_mixed_jobs_stop_before_read_submit_export(self):
        raster_doc = fitz.open()
        raster_page = raster_doc.new_page()
        for row in range(35):
            raster_page.insert_text((60, 80 + row*18),
                                    'This scanned body text contains repeated experimental observations.', fontsize=11)
        image = raster_page.get_pixmap().tobytes('png')
        raster_doc.close()
        for mixed in (False, True):
            with self.subTest(mixed=mixed):
                self.source.unlink()
                doc=fitz.open()
                if mixed:
                    page=doc.new_page()
                    page.insert_text((60,150), 'This is a selectable body paragraph before the scan.', fontsize=11)
                page=doc.new_page()
                page.insert_image(page.rect, stream=image)
                doc.save(self.source)
                doc.close()
                result=self.call('pdf_prepare', path=str(self.source), targetLanguage='zh')
                expected='UNSUPPORTED_MIXED_PDF' if mixed else 'UNSUPPORTED_SCANNED_PDF'
                self.assertEqual(result['code'], expected, result)
                self.assertEqual(result['pages'], [2 if mixed else 1])
                job_id=result['jobId']
                for tool, arguments in [('pdf_read_blocks', {}),
                                        ('pdf_submit_translations', {'version':result['data']['version'], 'translations':[]}),
                                        ('pdf_export', {})]:
                    stopped=self.call(tool, jobId=job_id, **arguments)
                    self.assertFalse(stopped['ok'], stopped)
                self.assertFalse((self.root/'output').exists())

    def test_page_and_size_limits(self):
        self.config['maxFileBytes'] = 1
        with self.assertRaisesRegex(ValueError, 'FILE_TOO_LARGE'):
            self.call('pdf_prepare', path=str(self.source), targetLanguage='en')
        self.config['maxFileBytes'] = 10000000
        self.config['maxPages'] = 0
        result = self.call('pdf_prepare', path=str(self.source), targetLanguage='en')
        self.assertFalse(result['ok'], result)

    def test_unsupported_target(self):
        with self.assertRaisesRegex(ValueError, 'TARGET_LANGUAGE_UNSUPPORTED'):
            self.call('pdf_prepare', path=str(self.source), targetLanguage='ar')


if __name__ == '__main__':
    unittest.main()
