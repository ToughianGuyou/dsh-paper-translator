#!/usr/bin/env python3
"""Explicit cache maintenance. Defaults to preview; never deletes source/output PDFs."""
import argparse
import json
from pathlib import Path
import re
import shutil
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--work-directory', required=True)
p.add_argument('--older-than-days', type=int, default=30)
p.add_argument('--apply', action='store_true', help='Actually remove listed completed/failed job caches')
a = p.parse_args()
if a.older_than_days < 1:
    p.error('--older-than-days must be positive')
root = Path(a.work_directory).expanduser().resolve(strict=True)
cutoff = time.time() - a.older_than_days * 86400
for directory in sorted(root.iterdir()):
    if directory.is_symlink() or not directory.is_dir() or not re.fullmatch('[a-f0-9]{32}', directory.name):
        continue
    if (directory / '.lock').exists():
        continue
    state = directory / 'job.json'
    try:
        job = json.loads(state.read_text('utf-8'))
        if job.get('state') not in {'COMPLETED', 'FAILED', 'UNSUPPORTED', 'NEEDS_REVIEW'} or state.stat().st_mtime > cutoff:
            continue
        print(json.dumps({'jobId': directory.name, 'state': job['state'], 'deleted': a.apply}))
        if a.apply:
            shutil.rmtree(directory)
    except (OSError, ValueError):
        continue
