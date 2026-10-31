"""Exercise real JSON pipes with Windows-style, non-UTF-8 stdout defaults."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

WORKER = Path(__file__).resolve().parents[1] / 'python' / 'worker.py'
LANGUAGES = '中文 日本語 한국어 Русский 😀'


class WorkerEncodingTests(unittest.TestCase):
    def call(self, encoding, config, tool, args, no_site=False, ok=True):
        env = {**os.environ, 'PYTHONIOENCODING': encoding, 'PYTHONUTF8': '0'}
        command = [sys.executable] + (['-S'] if no_site else []) + ['-u', str(WORKER)]
        request = json.dumps({'tool': tool, 'args': args, 'config': config}, ensure_ascii=False).encode('utf-8')
        process = subprocess.run(command, input=request, capture_output=True, env=env, timeout=20)
        self.assertEqual(process.returncode, 0, process.stderr)
        decoded = process.stdout.decode('utf-8', errors='strict')
        self.assertNotIn('\ufffd', decoded)
        result = json.loads(decoded)
        self.assertEqual(result['ok'], ok, result)
        return result

    def test_prepare_read_submit_export_and_status_preserve_unicode_under_legacy_encodings(self):
        # Force each pipe encoding even on Linux; Windows CI runs this too.
        for encoding in ('cp936', 'cp932', 'cp949', 'cp1251'):
            with self.subTest(encoding=encoding), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / ('论文目录 ' + LANGUAGES)
                root.mkdir()
                source = root / '原文.html'
                source.write_text('<article><h1>' + LANGUAGES + '</h1><p>公式 <math><mi>x</mi></math> 正文。</p></article>', encoding='utf-8')
                config = {'pythonExecutable': sys.executable, 'allowedInputDirectories': [str(root)],
                          'workDirectory': str(root / '工作'), 'outputDirectory': str(root / '译文')}
                prepared = self.call(encoding, config, 'html_prepare', {'path': str(source), 'targetLanguage': 'zh'})
                job_id = prepared['jobId']
                batch = self.call(encoding, config, 'pdf_read_blocks', {'jobId': job_id})
                blocks = batch['data']['blocks']
                self.assertEqual(blocks[0]['text'], LANGUAGES)
                self.assertIn('正文', blocks[1]['text'])
                translated = [{'blockId': b['blockId'], 'text': '译文 ' + b['text']} for b in blocks]
                self.call(encoding, config, 'pdf_submit_translations', {'jobId': job_id, 'version': prepared['data']['version'], 'translations': translated})
                exported = self.call(encoding, config, 'pdf_export', {'jobId': job_id})
                path = Path(exported['data']['outputs']['translated.html'])
                # Windows TEMP can use an 8.3 alias (RUNNER~1), while the
                # exporter resolves it to the long path (runneradmin). Verify
                # filesystem identity without weakening the Unicode checks.
                self.assertTrue(path.parent.parent.samefile(root / '译文'))
                html = path.read_text(encoding='utf-8')
                self.assertIn('译文 ' + LANGUAGES, html)
                self.assertIn('<math><mi>x</mi></math>', html)
                status = self.call(encoding, config, 'pdf_job_status', {'jobId': job_id})
                self.assertEqual(status['data']['outputs'], exported['data']['outputs'])
                self.assertEqual(status['data']['state'], 'COMPLETED')

    def test_dependency_error_preserves_unicode_configuration_without_bridge_help(self):
        config = {'pythonExecutable': 'C:/中文路径/日本語/😀/python.exe'}
        for encoding in ('cp936', 'cp932', 'cp949', 'cp1251'):
            with self.subTest(encoding=encoding):
                result = self.call(encoding, config, 'html_prepare', {}, no_site=True, ok=False)
                self.assertEqual(result['code'], 'DEPENDENCY_MISSING')
                self.assertEqual(result['data']['configuredPythonExecutable'], config['pythonExecutable'])

if __name__ == '__main__':
    unittest.main()
