"""Dependency diagnostics using only the Python standard library."""
import importlib
import sys

# Keep in sync with requirements.txt; these are the supported installation pins.
DEPENDENCIES = (
    ('pymupdf', 'PyMuPDF==1.26.6'),
    ('bs4', 'beautifulsoup4==4.13.5'),
    ('fontTools', 'fonttools==4.61.1'),
)


def install_command(executable, packages, windows=None):
    windows = sys.platform == 'win32' if windows is None else windows
    if windows:
        quoted = "'" + executable.replace("'", "''") + "'"
        return '& ' + quoted + ' -m pip install ' + ' '.join(packages)
    import shlex
    return shlex.quote(executable) + ' -m pip install ' + ' '.join(packages)


def check_environment(config):
    """Return one actionable failure covering all missing/broken dependencies."""
    details = {
        'pythonExecutable': sys.executable,
        'configuredPythonExecutable': config.get('pythonExecutable', 'python3'),
        'pythonVersion': sys.version.split()[0],
        'canTranslate': False,
        'canExport': False,
    }
    if sys.version_info < (3, 10):
        return dict(ok=False, code='PYTHON_VERSION_UNSUPPORTED',
                    message='Python 3.10+ is required. Actual interpreter: ' + sys.executable + '. Set pythonExecutable to a supported Python absolute path.',
                    pages=[], retryable=False, nextAction='stop_and_inform_user', data=details)
    missing = []
    for module, package in DEPENDENCIES:
        try:
            importlib.import_module(module)
        except Exception:
            # Do not leak module diagnostics or traceback; native import failures
            # also need the environment repaired before a job is created.
            missing.append(package)
    if not missing:
        return None
    command = install_command(sys.executable, missing)
    details.update(missingPackages=missing, installCommand=command,
                   commandShell='PowerShell' if sys.platform == 'win32' else 'POSIX shell')
    return dict(ok=False, code='DEPENDENCY_MISSING',
                message='Python: ' + sys.executable + '; missing or unusable packages: ' + ', '.join(missing) + '. Install in this interpreter: ' + command,
                pages=[], retryable=False, nextAction='stop_and_inform_user', data=details)
