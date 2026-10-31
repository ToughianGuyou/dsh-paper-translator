import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))
from paper_translation.environment import install_command


class EnvironmentTests(unittest.TestCase):
    def test_worker_without_site_packages_reports_all_dependencies_before_creating_job(self):
        with tempfile.TemporaryDirectory() as root:
            request = {'tool': 'html_prepare', 'args': {'path': 'missing.html', 'targetLanguage': 'zh'},
                       'config': {'pythonExecutable': sys.executable, 'workDirectory': root + '/jobs'}}
            run = subprocess.run([sys.executable, '-S', str(Path(__file__).resolve().parents[1] / 'python/worker.py')],
                                 input=json.dumps(request), text=True, capture_output=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
            result = json.loads(run.stdout)
            self.assertFalse(result['ok'])
            self.assertEqual(result['code'], 'DEPENDENCY_MISSING')
            self.assertEqual(result['nextAction'], 'stop_and_inform_user')
            self.assertEqual(result['data']['pythonExecutable'], sys.executable)
            self.assertEqual(result['data']['missingPackages'], ['PyMuPDF==1.26.6', 'beautifulsoup4==4.13.5', 'fonttools==4.61.1'])
            self.assertIn('-m pip install', result['data']['installCommand'])
            self.assertFalse(Path(root, 'jobs').exists())

    def test_install_commands_quote_interpreter_paths(self):
        path = "C:/Users/O'Brien/Python 312/python.exe"
        self.assertEqual(install_command(path, ['beautifulsoup4==4.13.5'], windows=True),
                         "& 'C:/Users/O''Brien/Python 312/python.exe' -m pip install beautifulsoup4==4.13.5")
        self.assertEqual(install_command('/opt/Python 312/python', ['fonttools==4.61.1'], windows=False),
                         "'/opt/Python 312/python' -m pip install fonttools==4.61.1")

if __name__ == '__main__':
    unittest.main()
