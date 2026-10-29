"""Conservative native-font math runs, including TeX delimiters and vectors.

These helpers do not infer arbitrary mathematics from prose.  Unidentified math
in ordinary text remains a review condition for the caller.
"""
from __future__ import annotations

import re
import statistics
from collections import Counter

import fitz

STRONG_MATH = re.compile(r'(?:math|symbol|cmmi|cmsy|cmex|msam|msbm|stix.*(?:math|symbol))', re.I)
TEX_AUX = re.compile(r'^(?:[A-Z]{6}\+)?(?:CMR|CMBX|CMB|CMM|CMSS|CMTT|LMMath|LMRoman)\d', re.I)
MATH_CHAR = re.compile('[=∑∏∫√∞≈≠≤≥∂∇∈∉⊂⊆±×÷α-ωΑ-Ω]')
OPERATORS = {'log', 'ln', 'exp', 'max', 'min', 'arg', 'argmax', 'argmin',
             'sin', 'cos', 'tan', 'lim', 'sup', 'inf', 'det', 'diag', 'tr',
             'var', 'cov', 'uniform', 'bernoulli', 'normal', 'softmax', 'relu'}


def is_math_span(span, body_size=None):
    """Recognize dedicated symbol fonts and restricted TeX auxiliary spans.

    CMR digits/brackets and CMBX vectors belong to the same mathematical run as
    CMMI variables; preserving only the latter corrupts formula boundaries.
    Full-size multiword prose in Roman fonts is deliberately excluded.
    """
    if STRONG_MATH.search(span.get('font', '')):
        return True
    if not TEX_AUX.search(span.get('font', '')):
        return False
    words = re.findall(r'[A-Za-z]{2,}', span.get('text', ''))
    if not words or all(w.lower() in OPERATORS for w in words):
        return True
    # TeX renders textual subscripts such as L_simple in a smaller Roman font.
    return bool(body_size and span.get('size', body_size) < body_size * .85
                and len(words) == 1 and len(words[0]) <= 16)


def _union(spans):
    r = fitz.Rect(spans[0]['bbox'])
    for span in spans[1:]:
        r |= fitz.Rect(span['bbox'])
    return r


def visual_lines(lines):
    """Coalesce adjacent fragments on the same visual line, preserving spans.

    PDF extractors can split a formula at an integral/large delimiter into
    several native lines.  Merge only fragments with closely aligned bbox tops,
    comparable sizes, and at most a small overlap for scripts. Never merge successive prose
    rows merely because their tall glyph rectangles overlap.
    """
    rows = []
    for line in lines:
        spans = line.get('spans', [])
        if not spans:
            continue
        r = _union(spans)
        size = max(s.get('size', 10) for s in spans)
        candidate = None
        for row in rows:
            a = row['rect']
            gap = max(r.x0 - a.x1, a.x0 - r.x1)
            if (-size * .8 <= gap <= size * .8 and abs(r.y0 - a.y0) <= size * .55
                    and abs(r.y1 - a.y1) <= size * .55
                    and tuple(line.get('dir', (1, 0))) == row['dir']):
                candidate = row
                break
        if candidate is None:
            rows.append({'spans': list(spans), 'rect': r,
                         'dir': tuple(line.get('dir', (1, 0)))})
        else:
            candidate['spans'].extend(spans)
            candidate['spans'].sort(key=lambda s: (s['bbox'][0], s['bbox'][1]))
            candidate['rect'] |= r
    # Native order is meaningful for consecutive body rows; sorting only merged
    # spans avoids reordering wrapped paragraphs by superscript heights.
    return rows


def protect_math_lines(block, page, counters):
    """Return (text, protected, uncertain_spans) for one native text block.

    The caller still adds citation protection and blocks export on uncertainty.
    Literal footnote markers from the parser's linking pass take precedence.
    """
    protected, rendered, uncertain = {}, [], []
    all_spans = [s for l in block['_raw'].get('lines', []) for s in l.get('spans', [])]
    sizes = Counter(round(s.get('size', 10), 1) for s in all_spans
                    if len(s.get('text', '').strip()) > 15)
    body_size = sizes.most_common(1)[0][0] if sizes else max([s.get('size', 10) for s in all_spans] or [10])
    footnotes = block.get('_footnoteTokens', {})
    for row in visual_lines(block['_raw'].get('lines', [])):
        spans = row['spans']
        bits, i = [], 0
        while i < len(spans):
            span = spans[i]
            text = span.get('text', '')
            if id(span) in footnotes:
                token = footnotes[id(span)]
                protected[token] = {'kind': 'literal', 'text': text.strip()}
                bits.append(token)
                i += 1
            elif is_math_span(span, body_size):
                run = [span]
                i += 1
                while i < len(spans) and id(spans[i]) not in footnotes and is_math_span(spans[i], body_size):
                    a, b = fitz.Rect(run[-1]['bbox']), fitz.Rect(spans[i]['bbox'])
                    if b.x0 - a.x1 > body_size * 1.5:
                        break
                    run.append(spans[i])
                    i += 1
                rect = _union(run)
                counters['MATH'] += 1
                token = '{{MATH_%05d}}' % counters['MATH']
                baseline_spans = [s for s in run if s.get('size', 10) >= max(t.get('size', 10) for t in run) * .95
                                  and not re.search('cmex', s.get('font', ''), re.I)]
                baseline = statistics.median([s.get('origin', (0, rect.y1))[1] for s in baseline_spans or run])
                protected[token] = {'kind': 'math', 'page': page,
                                    'bbox': [rect.x0, rect.y0, rect.x1, rect.y1],
                                    'baseline': baseline}
                # A math font may contain leading inter-word space.  Keep one
                # textual separator outside the image token for agent legibility.
                if run[0].get('text', '').startswith(' '):
                    bits.append(' ')
                bits.append(token)
                if run[-1].get('text', '').endswith(' '):
                    bits.append(' ')
            else:
                if MATH_CHAR.search(text) or re.search(r'[A-Za-z0-9][+^_][A-Za-z0-9]', text) or (
                        span.get('flags', 0) & 2 and re.fullmatch(r'\s*[A-Za-z][0-9]*\s*', text)):
                    uncertain.append(span)
                # Unknown TeX words adjacent to formulas may be meaningful labels;
                # do not silently translate them as ordinary prose.
                if TEX_AUX.search(span.get('font', '')) and text.strip():
                    uncertain.append(span)
                bits.append(text)
                i += 1
        rendered.append(''.join(bits))
    return ' '.join(s.strip().replace('\u00ad', '') for s in rendered if s.strip()), protected, uncertain


def display_equation_regions(texts, body_size, page_width):
    """Assemble whole isolated displays, including limits and fractions.

    Native PDF blocks frequently split every numerator, denominator and large
    operator into separate lines.  They must be assembled before preservation;
    treating each fragment as a new inline token loses its relative offsets.
    Prose rows are barriers and math fragments beside prose are excluded.
    """
    lines = [l for b in texts for l in b['_raw'].get('lines', [])]
    rows = visual_lines(lines)
    def annotation(span):
        # Short logical labels form part of a displayed definition/case, not a
        # reason to crop half of its denominator.  Full explanatory prose is
        # never admitted by this rule.
        return bool(re.fullmatch(r'\s*(?:where|and|with|for)\s*[:,]?\s*',
                                 span.get('text', ''), re.I))
    def equation_row(row):
        return all(is_math_span(s, body_size) or annotation(s)
                   or re.fullmatch(r'\s*\(\d+[a-z]?\)\s*', s.get('text', ''))
                   for s in row['spans'])
    prose = [row for row in rows
             if not equation_row(row) and any(not is_math_span(s, body_size)
                    and re.search(r'[A-Za-z]{3,}', s.get('text', ''))
                    for s in row['spans'])]
    candidates = []
    for row in rows:
        spans = [s for s in row['spans'] if s.get('text', '').strip()]
        if not spans:
            continue
        if not equation_row(row):
            continue
        r = row['rect']
        # An integral or subscript extracted separately from an ordinary body
        # line still belongs to that line, rather than to a display asset.
        if any(abs(other['rect'].y0-r.y0) < body_size*.75 for other in prose):
            continue
        strong = any(STRONG_MATH.search(s.get('font', '')) for s in spans)
        candidates.append({'rect': fitz.Rect(r), 'strong': strong})
    components = []
    for row in candidates:
        r, strong = row['rect'], row['strong']
        changed = True
        while changed:
            changed = False
            for i, component in enumerate(components):
                a = component['rect']
                vgap = max(r.y0-a.y1, a.y0-r.y1, 0)
                hgap = max(r.x0-a.x1, a.x0-r.x1, 0)
                # Rows separated by prose cannot form a single display.
                between = any(min(a.y1,r.y1) <= p['rect'].y0 <= max(a.y0,r.y0)
                              for p in prose)
                if vgap <= body_size*.45 and hgap <= page_width*.75 and not between:
                    r |= a
                    strong = strong or component['strong']
                    components.pop(i)
                    changed = True
                    break
        components.append({'rect': r, 'strong': strong})
    return [c['rect'] for c in components if c['strong'] and c['rect'].width >= body_size*1.5]
