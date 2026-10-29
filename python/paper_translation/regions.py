"""Native graphic regions, with image clipping and ruled-table reconstruction.

These are candidate regions, not permission to discard intersecting text. The
parser must still reject any resource boundary that splits a text block.
"""
from __future__ import annotations

import re
from collections import defaultdict

import fitz

CAPTION_START = re.compile(r'^(?:fig(?:ure)?\.?|table|algorithm|图|表)\s*[\dIVXivx]+\s*[:.：)]', re.I)


def _area(r):
    return max(0, r.width) * max(0, r.height)


def _cluster(rectangles, gap=4):
    result = []
    for rect in rectangles:
        r = fitz.Rect(rect)
        changed = True
        while changed:
            changed = False
            for i, other in enumerate(result):
                if not (r & (other + (-gap, -gap, gap, gap))).is_empty:
                    r |= other
                    result.pop(i)
                    changed = True
                    break
        result.append(r)
    return result


def visible_image_rects(page, include_empty=False):
    """Intersect raw image bounds with a uniquely matching native clip.

    PyMuPDF's image info reports the *unclipped* transformed image rectangle.
    A common PDF crop anchors its rectangular clipping path at that same top
    left corner. Only this directly evidenced case is reduced here. Unmatched
    or conflicting clips remain at raw bounds and will hit normal review checks.
    """
    clips = [fitz.Rect(d['scissor']) for d in page.get_drawings(extended=True)
             if d['type'] == 'clip' and 'scissor' in d]
    out = []
    for image in page.get_image_info():
        raw = fitz.Rect(image['bbox'])
        matches = []
        for clip in clips:
            if abs(raw.x0 - clip.x0) > .05 or abs(raw.y0 - clip.y0) > .05:
                continue
            clipped = raw & clip
            if clipped.is_empty or _area(clipped) < _area(raw) * .05:
                continue
            if clip.x1 <= raw.x1 + .1 and clip.y1 <= raw.y1 + .1:
                if not any(max(abs(a - b) for a, b in zip(clipped, m)) < .1 for m in matches):
                    matches.append(clipped)
        rect = matches[0] if len(matches) == 1 else raw
        rect &= page.rect
        if include_empty or not rect.is_empty:
            out.append(rect)
    return out


def ruled_regions(page):
    """Three or more aligned horizontal rules delimit tables/algorithms.

    Isolated equation fraction bars and footnote rules do not qualify. Keep
    adjacent tables separate even when their rule ends touch.
    """
    groups = []
    for drawing in page.get_drawings():
        r = fitz.Rect(drawing['rect'])
        if r.height > 1.5 or r.width < 60:
            continue
        group = next((g for g in groups if abs(g[0].x0 - r.x0) < 1.5
                      and abs(g[0].x1 - r.x1) < 1.5), None)
        if group is None:
            groups.append([r])
        else:
            group.append(r)
    result = []
    for rules in groups:
        ys = sorted({round(r.y0, 1) for r in rules})
        # A large vertical gap breaks a repeated rule style into distinct tables.
        runs = [[]]
        for y in ys:
            if runs[-1] and y - runs[-1][-1] > 130:
                runs.append([])
            runs[-1].append(y)
        for run in runs:
            if len(run) >= 3 and run[-1] - run[0] >= 15:
                result.append(fitz.Rect(rules[0].x0, run[0] - 1,
                                        rules[0].x1, run[-1] + 1))
    return result


def _complete_region_glyphs(page, regions):
    """Complete slightly protruding glyphs; join resources sharing glyphs.

    Font bounding boxes commonly protrude a point past a table rule. Expanding
    by at most three points is safe only for a mostly included character. A
    tiny fragment of a neighboring caption is not pulled in; when that caption
    belongs to an overlapping resource, both resources form one preserved group.
    """
    chars = [fitz.Rect(c['bbox']) for b in page.get_text('rawdict')['blocks']
             for line in b.get('lines', []) for span in line['spans'] for c in span['chars']]
    out = [fitz.Rect(r) for r in regions]
    for i, r in enumerate(out):
        for cr in chars:
            intersection = r & cr
            if not intersection.is_empty and not r.contains(cr):
                if _area(intersection) >= _area(cr) * .75:
                    expanded = r | cr
                    if max(abs(a - b) for a, b in zip(expanded, r)) <= 3:
                        r = expanded
        out[i] = r
    changed = True
    while changed:
        changed = False
        for i, a in enumerate(out):
            for j in range(i + 1, len(out)):
                b = out[j]
                if (a & b).is_empty:
                    continue
                shared = any(not (a & cr).is_empty and not (b & cr).is_empty
                             and (a.contains(cr) or b.contains(cr)) for cr in chars)
                if shared:
                    out[i] = a | b
                    out.pop(j)
                    changed = True
                    break
            if changed:
                break
    return out


def asset_regions(page, texts, body_size):
    """Return figure/table candidates grouped by an actual nearby caption.

    ``texts`` uses parser dictionaries with ``_rect``, ``text`` and ``_raw``.
    This helper does not mark text as assigned or suppress boundary diagnostics.
    """
    images = visible_image_rects(page)
    drawing_rects = []
    for d in page.get_drawings():
        r = fitz.Rect(d['rect'])
        if r.width > 3 and r.height > 3:
            # Wide solid title/separator bars are page furniture, not figures.
            if r.height <= 5 and r.width > r.height * 20:
                continue
            drawing_rects.append(r)
    # Do not geometrically cluster ruled tables: adjacent independent tables can
    # have overlapping borders. Caption matching will group panels deliberately.
    regions = _cluster(images + drawing_rects, gap=4) + ruled_regions(page)
    try:
        for t in page.find_tables().tables:
            if t.row_count >= 2 and t.col_count >= 2:
                r = fitz.Rect(t.bbox)
                if not any(_area(r & other) >= _area(r) * .98 for other in regions):
                    regions.append(r)
    except Exception:
        # The parser separately reports a failed table detector.
        pass

    captions = [b for b in texts if CAPTION_START.match(b.get('text', ''))]
    # Match graphics to their nearest caption first. A chart beside another
    # chart must not claim the neighbor's caption or duplicate either resource.
    owners = defaultdict(list)
    unowned = []
    for region in regions:
        choices = []
        for i, caption in enumerate(captions):
            c = caption['_rect']
            overlap = max(0, min(c.x1, region.x1) - max(c.x0, region.x0))
            if overlap < min(c.width, region.width) * .4:
                continue
            is_table = re.match(r'^(?:table|algorithm|表)', caption['text'], re.I)
            # Tables/algorithms use a caption above; figures normally below.
            gap = region.y0 - c.y1 if is_table else c.y0 - region.y1
            if -min(region.height, c.height) - 2 <= gap <= body_size * 4:
                # Distance must not cross an unrelated long prose line.
                top, bottom = sorted((c.y1, region.y0)) if is_table else sorted((region.y1, c.y0))
                obstructed = any(b is not caption and len(b.get('text', '')) > 100
                                 and b['_rect'].y0 >= top and b['_rect'].y1 <= bottom
                                 and not (b['_rect'] & region).is_empty for b in texts)
                if not obstructed:
                    choices.append((max(0, gap), i))
        choices.sort()
        if choices and (len(choices) == 1 or choices[0][0] + .5 < choices[1][0]):
            owners[choices[0][1]].append(region)
        else:
            unowned.append(region)

    output = list(unowned)
    for owner, panels in owners.items():
        rect = fitz.Rect(captions[owner]['_rect'])
        for panel in panels:
            rect |= panel
        # Graphic labels immediately beside the panel (especially rotated axes)
        # belong to the preserved figure. Long prose is never pulled in here.
        for b in texts:
            br = b['_rect']
            rotated = any(tuple(line.get('dir', (1, 0))) != (1, 0)
                          for line in b.get('_raw', {}).get('lines', []))
            if rotated and len(b.get('text', '')) < 80:
                for panel in panels:
                    if not (br & (panel + (-body_size * 3, 0, body_size * 3, 0))).is_empty:
                        rect |= br
                        break
        output.append(rect)
    return _complete_region_glyphs(page, output)
