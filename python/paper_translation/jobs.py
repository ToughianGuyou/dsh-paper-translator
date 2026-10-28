"""Durable jobs with atomic commits and an exclusive per-job lock."""
from pathlib import Path
from contextlib import contextmanager
from collections import Counter
import hashlib
import json
import os
import re
import shutil
import time
import uuid

VERSION = '1'
STOP = {'NEEDS_REVIEW', 'UNSUPPORTED', 'FAILED'}
TOKEN = re.compile(r'\{\{[^{}]+\}\}')

def response(ok=True, code='OK', message='', job=None, data=None, pages=None):
    result = dict(ok=ok, code=code, message=message, pages=pages or [], retryable=False,
                  nextAction='continue' if ok else 'stop_and_inform_user', data=data or {})
    if job:
        result['jobId'] = job['jobId']
        result['data']['state'] = job['state']
        result['data']['version'] = job['version']
    return result

def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def save(path, value):
    temporary = path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as f:
            json.dump(value, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)

@contextmanager
def lock(directory):
    target = directory / '.lock'
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ValueError('JOB_BUSY: job is locked; if a process was killed, verify no worker is running before removing its .lock')
    try:
        os.write(descriptor, str(os.getpid()).encode())
        os.close(descriptor)
        yield
    finally:
        target.unlink(missing_ok=True)

def integer(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f'INVALID_ARGUMENT: {name} must be {minimum}..{maximum}')
    return value

def check_source(job):
    try:
        unchanged = digest(job['sourcePath']) == job['sourceHash']
    except OSError:
        unchanged = False
    if not unchanged:
        raise ValueError('STALE_VERSION: source changed or is unavailable; prepare a new job')

def summary(job):
    pending = [b['blockId'] for b in job['blocks'] if b['translate'] and b['blockId'] not in job['translations']]
    return dict(totalBlocks=len(job['blocks']), translationBlocks=sum(b['translate'] for b in job['blocks']),
                accepted=len(job['translations']), missingBlocks=pending, issues=job.get('issues', []),
                warnings=job.get('warnings', []), outputs=job.get('outputs', {}),
                canTranslate=job['state'] in {'READY', 'TRANSLATING', 'READY_TO_EXPORT'},
                canExport=job['state'] == 'READY_TO_EXPORT')

def prepare(args, config, root):
    from .parser import parse_pdf
    path = Path(args.get('path', '')).expanduser().resolve(strict=True)
    allowed = config.get('allowedInputDirectories') or [str(Path.cwd())]
    if not any(path.is_relative_to(Path(x).expanduser().resolve()) for x in allowed):
        raise ValueError('PATH_NOT_ALLOWED: input is outside configured allowedInputDirectories')
    if not path.is_file() or path.suffix.lower() != '.pdf':
        raise ValueError('PDF_INVALID: input must be a PDF file')
    if path.stat().st_size > config.get('maxFileBytes', 104857600):
        raise ValueError('FILE_TOO_LARGE: configured PDF size limit exceeded')
    language = args.get('targetLanguage', '')
    if not isinstance(language, str) or not language.strip():
        raise ValueError('INVALID_ARGUMENT: targetLanguage is required')
    language = language.strip().lower()
    aliases = {'chinese': 'zh', '中文': 'zh', '简体中文': 'zh', '繁体中文': 'zh-tw', 'english': 'en', '英语': 'en', 'japanese': 'ja', '日语': 'ja', 'korean': 'ko', '韩语': 'ko'}
    language = aliases.get(language, language)
    if language not in {'zh','zh-cn','zh-tw','en','ja','ko','de','fr','es','it','pt'}:
        raise ValueError('TARGET_LANGUAGE_UNSUPPORTED: supported language codes: zh, zh-cn, zh-tw, en, ja, ko, de, fr, es, it, pt')
    job_id = uuid.uuid4().hex
    directory = root / job_id
    directory.mkdir(mode=0o700)
    job = dict(jobId=job_id, version=VERSION, state='PRECHECKING', sourcePath=str(path),
               sourceHash=digest(path), targetLanguage=language, createdAt=time.time(), blocks=[], translations={}, config=config)
    save(directory / 'job.json', job)
    try:
        parsed = parse_pdf(str(path), config)
        job.update(parsed)
        for order, block in enumerate(job['blocks']):
            block['order'] = order
        check_source(job)
        if parsed.get('issues'):
            parsed['issues'].sort(key=lambda issue: 0 if issue['code'] in {'UNSUPPORTED_SCANNED_PDF', 'UNSUPPORTED_MIXED_PDF'} else 1)
            code = parsed['issues'][0]['code']
            job['state'] = 'NEEDS_REVIEW' if code == 'NEEDS_REVIEW' else 'UNSUPPORTED'
            save(directory / 'job.json', job)
            return response(False, code, '; '.join(x['message'] for x in parsed['issues']), job, summary(job), sorted({p for x in parsed['issues'] for p in x.get('pages', [])}))
        job['state'] = 'READY' if any(b['translate'] for b in job['blocks']) else 'READY_TO_EXPORT'
        save(directory / 'job.json', job)
        return response(job=job, data=summary(job))
    except Exception as exc:
        job['state'] = 'FAILED'
        job['issues'] = [{'code': str(exc).split(':')[0], 'message': str(exc), 'pages': []}]
        save(directory / 'job.json', job)
        return response(False, job['issues'][0]['code'], str(exc), job, summary(job))

def dispatch(request):
    if not isinstance(request, dict) or not isinstance(request.get('args', {}), dict) or not isinstance(request.get('config', {}), dict):
        raise ValueError('INVALID_ARGUMENT: request, args and config must be objects')
    tool, args, config = request.get('tool'), request.get('args', {}), request.get('config', {})
    root = Path(config.get('workDirectory', './work/dsh-pdf-paper-translation-tools')).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if tool == 'pdf_prepare':
        return prepare(args, config, root)
    if tool not in {'pdf_job_status','pdf_read_blocks','pdf_submit_translations','pdf_export'}:
        raise ValueError('INVALID_ARGUMENT: unknown tool')
    job_id = args.get('jobId', '')
    if not isinstance(job_id, str) or not re.fullmatch(r'[a-f0-9]{32}', job_id):
        raise ValueError('INVALID_ARGUMENT: invalid jobId')
    directory = root / job_id
    if not (directory / 'job.json').is_file():
        raise ValueError('JOB_NOT_FOUND: unknown jobId')
    with lock(directory):
        job = json.loads((directory / 'job.json').read_text('utf-8'))
        if tool == 'pdf_job_status':
            return response(job=job, data=summary(job))
        if job['state'] in STOP or job['state'] in {'PRECHECKING', 'EXPORTING'}:
            return response(False, 'JOB_STOPPED', 'Job is not available for translation or export; prepare again after resolving issues.', job, summary(job))
        try:
            check_source(job)
        except ValueError as exc:
            return response(False, 'STALE_VERSION', str(exc), job)
        if tool == 'pdf_read_blocks':
            cursor = integer(args.get('cursor', 0), 'cursor', 0, len(job['blocks']))
            limit = integer(args.get('limit', 10), 'limit', 1, min(config.get('maxBatchSize', 50), 100))
            eligible = [b for b in job['blocks'] if b['translate'] and b['blockId'] not in job['translations'] and b['order'] >= cursor]
            batch = eligible[:limit]
            next_cursor = batch[-1]['order'] + 1 if len(eligible) > len(batch) else None
            indices = {b['order'] for b in batch}
            contexts = [dict(b, readOnly=True) for b in job['blocks'] if b['order'] not in indices and any(abs(b['order'] - i) == 1 for i in indices) and b.get('text')]
            return response(job=job, data={'blocks': batch, 'context': contexts, 'nextCursor': next_cursor})
        if tool == 'pdf_submit_translations':
            if args.get('version') != job['version']:
                return response(False, 'STALE_VERSION', 'Use version returned by pdf_read_blocks.', job)
            items = args.get('translations')
            if not isinstance(items, list) or not 1 <= len(items) <= config.get('maxBatchSize', 50):
                raise ValueError('INVALID_ARGUMENT: translations batch size invalid')
            by_id = {b['blockId']: b for b in job['blocks'] if b['translate']}
            updates = {}
            for item in items:
                if not isinstance(item, dict):
                    raise ValueError('INVALID_ARGUMENT: translation must be an object')
                bid, translated = item.get('blockId'), item.get('text')
                if bid not in by_id or bid in updates or not isinstance(translated, str) or not translated.strip() or len(translated) > 200000:
                    return response(False, 'INVALID_TRANSLATION', 'Invalid, duplicate, empty or oversized translation block.', job)
                if Counter(TOKEN.findall(translated)) != Counter(TOKEN.findall(by_id[bid]['text'])):
                    return response(False, 'PLACEHOLDER_MISMATCH', f'Protected markers differ in {bid}. Batch was not saved.', job)
                updates[bid] = translated
            if job['state'] == 'COMPLETED':
                if all(job['translations'].get(k) == v for k,v in updates.items()):
                    return response(job=job, data=summary(job))
                return response(False, 'JOB_COMPLETED', 'Completed jobs are immutable; prepare a new job.', job)
            job['translations'].update(updates)
            job['state'] = 'TRANSLATING' if summary(job)['missingBlocks'] else 'READY_TO_EXPORT'
            save(directory / 'job.json', job)
            return response(job=job, data=summary(job))
        if tool == 'pdf_export':
            if job['state'] == 'COMPLETED':
                try:
                    valid = all(digest(path) == job['outputHashes'].get(name) for name, path in job['outputs'].items())
                except OSError:
                    valid = False
                if not valid:
                    return response(False, 'OUTPUT_VALIDATION_FAILED', 'A completed output was removed or changed; prepare a new job.', job)
                return response(job=job, data=summary(job))
            if summary(job)['missingBlocks']:
                return response(False, 'TRANSLATION_INCOMPLETE', 'Submit all missing blocks before export.', job, summary(job))
            return export(job, directory)

def export(job, directory):
    from .exporter import export_pdf
    config = job['config']
    outroot = Path(config.get('outputDirectory', './output/dsh-pdf-paper-translation-tools')).expanduser().resolve()
    outroot.mkdir(parents=True, exist_ok=True)
    final = outroot / job['jobId']
    staging = outroot / ('.' + job['jobId'] + '-' + uuid.uuid4().hex)
    staging.mkdir(mode=0o700)
    job['state'] = 'EXPORTING'
    save(directory / 'job.json', job)
    try:
        pdf = staging / 'translated.pdf'
        report = export_pdf(job['sourcePath'], job['blocks'], job['translations'], job['targetLanguage'], str(pdf), config)
        check_source(job)
        if config.get('keepOriginalMarkdown', True):
            lines = ['# Original text', '']
            for b in job['blocks']:
                text = b.get('text', '')
                for token, item in b.get('protected', {}).items():
                    if item.get('kind') != 'math':
                        text = text.replace(token, item.get('text', token))
                lines.extend([f'<!-- {b["blockId"]}; source pages: {", ".join(str(s["page"]) for s in b["sources"])} -->', text or f'[Preserved {b["type"]}: {b["blockId"]}]', ''])
            (staging / 'original.md').write_text('\n'.join(lines), 'utf-8')
        report['outputPath'] = str(final / 'translated.pdf')
        save(staging / 'validation.json', report)
        if final.exists():
            raise ValueError('OUTPUT_EXISTS: refusing to replace prior output')
        staging.rename(final)
        job['state'] = 'COMPLETED'
        job['outputs'] = {f.name: str(f) for f in final.iterdir()}
        job['validation'] = report
        job['outputHashes'] = {name: digest(path) for name, path in job['outputs'].items()}
        save(directory / 'job.json', job)
        return response(job=job, data=summary(job))
    except Exception as exc:
        shutil.rmtree(staging, ignore_errors=True)
        job['state'] = 'FAILED'
        code = str(exc).split(':', 1)[0]
        if not code.isupper(): code = 'OUTPUT_VALIDATION_FAILED'
        job['issues'] = [{'code': code, 'message': str(exc), 'pages': []}]
        save(directory / 'job.json', job)
        return response(False, code, str(exc), job, summary(job))
