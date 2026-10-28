#!/usr/bin/env python3
"""One request per process, bounded JSON stdin/stdout protocol."""
import json
from contextlib import redirect_stdout
import sys

def main():
    try:
        from paper_translation.jobs import dispatch
        raw = sys.stdin.buffer.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError('INVALID_ARGUMENT: request exceeds 8 MiB')
        request = json.loads(raw)
        with redirect_stdout(sys.stderr):
            result = dispatch(request)
    except ModuleNotFoundError as exc:
        result = {'ok': False, 'code': 'DEPENDENCY_MISSING', 'message': str(exc), 'pages': [], 'retryable': False, 'nextAction': 'install_dependencies', 'data': {}}
    except Exception as exc:
        message = str(exc)
        code = message.split(':', 1)[0] if ':' in message and message.split(':', 1)[0].isupper() else 'INTERNAL_ERROR'
        result = {'ok': False, 'code': code, 'message': message, 'pages': [], 'retryable': False, 'nextAction': 'stop_and_inform_user', 'data': {}}
    sys.stdout.write(json.dumps(result, ensure_ascii=False))

if __name__ == '__main__':
    main()
