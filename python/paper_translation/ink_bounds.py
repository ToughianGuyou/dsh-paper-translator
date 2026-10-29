"""Exact embedded Type1 outline bounds for conservative crop-boundary checks.

No OCR or raster thresholds are used. Unsupported fonts, glyph mappings, text
directions or transforms return None, so callers keep their review condition.
The document-local cache never outlives its owning open PDF document.
"""
from __future__ import annotations

import math
import re

import fitz
from fontTools.agl import UV2AGL
from fontTools import t1Lib
from fontTools.pens.boundsPen import BoundsPen


def _font_name(name):
    return re.sub(r'^[A-Z]{6}\+', '', name or '')


def _key(font, char, origin, size):
    return (font, char, round(origin[0], 3), round(origin[1], 3), round(size, 3))


def _cache(page):
    doc = page.parent
    cache = getattr(doc, '_paper_ink_cache', None)
    if cache is None:
        cache = {'fonts': {}, 'pages': {}}
        doc._paper_ink_cache = cache
    return cache


def _embedded_font(page, font):
    cache = _cache(page)['fonts']
    if font in cache:
        return cache[font]
    # The same subset can appear under several resource aliases. Distinct
    # embedded streams with the same visible name are ambiguous, not guessed.
    sources = {}
    for entry in page.get_fonts(full=True):
        if _font_name(entry[3]) != font:
            continue
        name, ext, kind, data = page.parent.extract_font(entry[0])
        if kind != 'Type1' or ext not in ('pfa', 'pfb') or not data:
            continue
        sources[data] = (ext, data)
    if len(sources) != 1:
        cache[font] = None
        return None
    ext, data = next(iter(sources.values()))
    try:
        # PDF FontFile streams omit the outer PFA trailer. Read the extracted
        # font program directly with fontTools' restricted PostScript parser.
        if ext != 'pfa':
            raise ValueError('Only embedded PFA programs are supported')
        parsed = t1Lib.T1Font.__new__(t1Lib.T1Font)
        parsed.encoding = 'ascii'
        parsed.data = data
        parsed.parse()
        matrix = parsed.font['FontMatrix']
        if (len(matrix) != 6 or not all(math.isfinite(v) for v in matrix)
                or matrix[0] <= 0 or matrix[3] <= 0
                or any(abs(matrix[i]) > 1e-12 for i in [1, 2, 4, 5])):
            raise ValueError('Unrecognized Type1 transform')
        value = {'glyphs': parsed.getGlyphSet(), 'matrix': matrix, 'bounds': {}}
    except Exception:
        value = None
    cache[font] = value
    return value


def _raw_page(page):
    cache = _cache(page)['pages']
    if page.number in cache:
        return cache[page.number]
    by_char, by_span = {}, {}
    raw = page.get_text('rawdict', flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES)
    for block in raw['blocks']:
        for line in block.get('lines', []):
            for span in line.get('spans', []):
                record = {'span': span, 'dir': tuple(line.get('dir', (1, 0))),
                          'wmode': line.get('wmode', 0)}
                skey = (span['font'], round(span['origin'][0], 3), round(span['origin'][1], 3), round(span['size'], 3))
                by_span.setdefault(skey, []).append(record)
                for char in span.get('chars', []):
                    by_char.setdefault(_key(span['font'],char['c'],char['origin'],span['size']), []).append((record, char))
    value = {'chars': by_char, 'spans': by_span}
    cache[page.number] = value
    return value


def character_ink_bounds(page, font, char, origin, size, logical_bbox=None):
    """Return actual glyph-ink Rect, an empty Rect for no ink, or None.

    Inputs must match a native rawdict character on this page. The optional
    logical_bbox is a further identity check, not an inferred crop tolerance.
    Only axis-aligned horizontal, filled Type1 text is currently supported.
    """
    matches = _raw_page(page)['chars'].get(_key(font,char,origin,size), [])
    if len(matches) != 1:
        return None
    record, raw_char = matches[0]
    if record['dir'] != (1., 0.) or record['wmode'] != 0:
        return None
    if logical_bbox is not None and any(abs(a-b) > .003 for a,b in zip(logical_bbox, raw_char['bbox'])):
        return None
    embedded = _embedded_font(page, font)
    if embedded is None or len(char) != 1:
        return None
    glyph_name = UV2AGL.get(ord(char))
    glyphs = embedded['glyphs']
    if glyph_name is None or glyph_name not in glyphs:
        return None
    try:
        if glyph_name not in embedded['bounds']:
            pen = BoundsPen(glyphs)
            glyphs[glyph_name].draw(pen)
            embedded['bounds'][glyph_name] = (pen.bounds, glyphs[glyph_name].width)
        bounds, advance = embedded['bounds'][glyph_name]
        if bounds is None:
            return fitz.Rect()
        a, _, _, d, _, _ = embedded['matrix']
        box = fitz.Rect(raw_char['bbox'])
        # MuPDF's horizontal logical character rectangle carries the text
        # advance. A shifted x0 indicates an unhandled shear/transform.
        if abs(box.x0-origin[0]) > .003 or advance <= 0:
            return None
        scale_x = box.width/(advance*a)
        scale_y = size
        if not .5 <= scale_x/max(size,1e-9) <= 2:
            return None
        x0,y0,x1,y1 = bounds
        return fitz.Rect(origin[0]+x0*a*scale_x,
                         origin[1]-y1*d*scale_y,
                         origin[0]+x1*a*scale_x,
                         origin[1]-y0*d*scale_y)
    except Exception:
        return None


def block_ink_intersects(page, block, rect):
    """True for a proved ink collision, False for proved separation, else None."""
    rect = fitz.Rect(rect)
    unknown = False
    spans = block.get('_spans')
    if spans is None:
        spans = [s for l in block.get('_raw',{}).get('lines',[]) for s in l.get('spans',[])]
    for span in spans:
        skey = (span.get('font'),round(span.get('origin',(0,0))[0],3),round(span.get('origin',(0,0))[1],3),round(span.get('size',0),3))
        matches = _raw_page(page)['spans'].get(skey, [])
        if len(matches) != 1:
            if fitz.Rect(span.get('bbox', (0,0,0,0))).intersects(rect):
                unknown = True
            continue
        record = matches[0]
        for char in record['span'].get('chars', []):
            logical = fitz.Rect(char['bbox'])
            if not logical.intersects(rect):
                continue
            ink = character_ink_bounds(page,span['font'],char['c'],char['origin'],span['size'],logical)
            if ink is None:
                unknown = True
            elif not ink.is_empty and ink.intersects(rect):
                return True
    return None if unknown else False


# Convenient alias for code that already refers to a character rather than a span.
ink_bbox = character_ink_bounds
