"""Geometry-led, deliberately conservative PDF paper parser (no OCR).

The recognizers are heuristics, not layout-model confidence probabilities. Unknown
page roles and math/asset boundaries are blocking issues, never silent fallbacks.
Coordinates are PDF points in PyMuPDF's unrotated page coordinate system.
"""
from __future__ import annotations
import re
import math
import statistics
from collections import Counter
from pathlib import Path

import fitz

from .math_runs import protect_math_lines, display_equation_regions
from .regions import visible_image_rects, asset_regions

PARSER_VERSION = '1.1.0'
CAPTION = re.compile(r'^(?:fig(?:ure)?\.?|table|图|表)\s*[\dIVXivx]+\s*[:.：)]', re.I)
REFERENCE = re.compile(r'^(?:references|bibliography|参考文献)\s*$', re.I)
CITATION = re.compile(r'\[(?:\d+[a-z]?(?:\s*[,;–−-]\s*\d+[a-z]?)*)(?:\s*)\]|【\d+(?:\s*[,，、–-]\s*\d+)*】')
MATH_FONT = re.compile(r'(?:math|symbol|cmmi|cmsy|cmex|msam|msbm|stix.*(?:math|symbol))', re.I)
MATH_CHAR = re.compile('[=∑∏∫√∞≈≠≤≥∂∇∈∉⊂⊆±×÷]')
APPENDIX = re.compile(r'^(?:appendix\b|appendices\b|supplement(?:ary)?\b|additional\s+(?:information|results|experiments)\b|extra\s+information\b)', re.I)


def _appendix_heading(text):
    return bool(APPENDIX.match(text) or re.match(r'^[A-Z](?:\.|\s)\s*[A-Z][a-z]',text))


def _rect(v): return fitz.Rect(v)
def _box(v): return [math.floor(v[0]*1000)/1000, math.floor(v[1]*1000)/1000, math.ceil(v[2]*1000)/1000, math.ceil(v[3]*1000)/1000]
def _area(v): return max(0, v.width) * max(0, v.height)
def _overlap(a, b): return _area(a & b)
def _union(items):
    r = fitz.Rect(items[0])
    for item in items[1:]: r |= item
    return r


def _issue(issues, page, message, code='NEEDS_REVIEW'):
    issues.append({'code': code, 'message': message, 'pages': [page]})


def _join_lines(lines):
    # Only soft hyphens are unambiguously discretionary; real '-' stays intact.
    return ' '.join(s.strip().replace('\u00ad', '') for s in lines if s.strip())


def _text_block(raw, number):
    lines = raw.get('lines', [])
    spans = [s for line in lines for s in line.get('spans', [])]
    text = _join_lines([''.join(s.get('text', '') for s in ln.get('spans', [])) for ln in lines])
    if not text.strip(): return None
    sizes = [s['size'] for s in spans if s.get('text', '').strip()]
    return {'_raw': raw, '_spans': spans, '_number': number, '_rect': _rect(raw['bbox']),
            '_size': statistics.median(sizes) if sizes else 11, 'text': text}


def _cluster_rects(rectangles, gap=3):
    clusters = []
    for r in rectangles:
        r = fitz.Rect(r)
        changed = True
        while changed:
            changed = False
            for i, other in enumerate(clusters):
                expanded = other + (-gap, -gap, gap, gap)
                if not (r & expanded).is_empty:
                    r |= other
                    clusters.pop(i)
                    changed = True
                    break
        clusters.append(r)
    return clusters


def _partition_text_regions(texts, regions):
    """Split native blocks at *whole-line* asset boundaries without losing lines.

    A PDF text block can contain a display followed by ordinary prose. Keeping
    its large union bbox would falsely imply that the crop slices that prose.
    Individual line intersections remain blocking; this is no clipping waiver.
    """
    output=[]
    for block in texts:
        groups=[]
        for line in block['_raw'].get('lines',[]):
            rect=_rect(line['bbox'])
            owners=tuple(i for i,r in enumerate(regions)
                         if _overlap(rect,r) >= _area(rect)*.98)
            if groups and groups[-1][0]==owners:
                groups[-1][1].append(line)
            else:
                groups.append((owners,[line]))
        for _,lines in groups:
            raw={**block['_raw'],'lines':lines,'bbox':_box(_union([_rect(l['bbox']) for l in lines]))}
            item=_text_block(raw,len(output))
            if item: output.append(item)
    return output


def _scan_rows(page):
    """Detect repeated narrow dark bands in large raster pages, without OCR."""
    pix = page.get_pixmap(matrix=fitz.Matrix(.65, .65), colorspace=fitz.csGRAY, alpha=False)
    data = pix.samples
    w, h = pix.width, pix.height
    counts = []
    x0, x1 = int(w*.08), int(w*.92)
    for y in range(int(h*.08), int(h*.92)):
        row = data[y*w+x0:y*w+x1]
        density=sum(v < 160 for v in row) / max(1, len(row))
        transitions=sum(row[i]<160 and row[i-1]>=160 for i in range(1,len(row)))
        counts.append(density if transitions>=8 else 0)
    runs, start = [], None
    for i, density in enumerate(counts + [0]):
        if .012 < density < .48:
            if start is None: start = i
        elif start is not None:
            runs.append(i-start)
            start = None
    return sum(2 <= n <= 14 for n in runs) >= 12


def _ordered(items, width, issues, page):
    """Split at spanning blocks, then read each vertical band column-wise."""
    if not items: return []
    # Columns require independent blocks on both sides of a real center gutter.
    mid = width / 2
    left = [b for b in items if b['_rect'].x1 <= mid + 6]
    right = [b for b in items if b['_rect'].x0 >= mid - 6]
    def prose_column(b):
        # A formula number, author cell, chart label or math fragment is not a
        # column. Infer gutters only from independently readable prose runs.
        text = b.get('text', '')
        return (b.get('type') in ('body', 'reference')
                and b['_rect'].width >= width * .22
                and len(re.findall(r'[A-Za-z]{2,}', text)) >= 4
                and not re.search(r'@|https?://', text)
                and not any(MATH_FONT.search(s.get('font', '')) for s in b.get('_spans', [])))
    paired = any(min(a['_rect'].y1,b['_rect'].y1) > max(a['_rect'].y0,b['_rect'].y0)
                 for a in left if prose_column(a) for b in right if prose_column(b))
    if not paired:
        return sorted(items, key=lambda b: (b['_rect'].y0,b['_rect'].x0))
    spanning = [b for b in items if b not in left and b not in right]
    spanning.sort(key=lambda b:b['_rect'].y0)
    output, pending = [], [b for b in items if b not in spanning]
    for s in spanning:
        before = [b for b in pending if b['_rect'].y1 <= s['_rect'].y0 + 2]
        crossing = [b for b in pending if b['_rect'].y0 < s['_rect'].y1 - 2 and b not in before]
        if crossing:
            _issue(issues,page,'A spanning region crosses column content; reading order is ambiguous.')
        output += sorted(before,key=lambda b:(b['_rect'].x0 >= mid-6,b['_rect'].y0))
        output.append(s)
        pending = [b for b in pending if b not in before]
    output += sorted(pending,key=lambda b:(b['_rect'].x0 >= mid-6,b['_rect'].y0))
    # Three independent starts / floating boxes cannot be inferred as two columns.
    for side in (left,right):
        starts = sorted({round(b['_rect'].x0/18)*18 for b in side if len(b.get('text','')) > 60})
        if starts and starts[-1]-starts[0] > width*.16:
            _issue(issues,page,'Non-standard columns or floating text boxes require review.')
    return output


def _protect(block, page, counters, issues):
    text, protected, uncertain = protect_math_lines(block, page, counters)
    if uncertain:
        _issue(issues,page,'Mathematical expression boundary cannot be established from font spans.')
    def replace(match):
        counters['CITE'] += 1
        token = '{{CITE_%05d}}' % counters['CITE']
        protected[token] = {'kind':'literal','text':match.group()}
        return token
    text = CITATION.sub(replace,text)
    return text,protected


def parse_pdf(path, config=None):
    config = config or {}
    issues, warnings, blocks = [], [], []
    result = {'blocks':blocks,'issues':issues,'warnings':warnings,'pages':0,'parserVersion':PARSER_VERSION}
    try:
        doc = fitz.open(path)
    except Exception as exc:
        _issue(issues,1,'Cannot open PDF: '+str(exc),'PDF_INVALID')
        return result
    try:
        if not doc.is_pdf:
            _issue(issues,1,'Input is not a PDF.','PDF_INVALID'); return result
        if doc.needs_pass:
            _issue(issues,1,'Encrypted PDF requires a password.','PDF_ENCRYPTED'); return result
        if doc.permissions >= 0 and not doc.permissions & fitz.PDF_PERM_COPY:
            _issue(issues,1,'PDF extraction permission is disabled.','PDF_PERMISSION_DENIED'); return result
        result['pages'] = len(doc)
        if len(doc) > int(config.get('maxPages',500)):
            _issue(issues,1,'PDF exceeds configured maxPages.','LIMIT_EXCEEDED'); return result
        all_pages = []
        scanned = []
        for index,page in enumerate(doc):
            num = index+1
            if page.rotation:
                _issue(issues,num,'Rotated page coordinates require review before region preservation.')
            data = page.get_text('dict', flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES)
            expanded=[]
            for native in data['blocks']:
                if native['type']!=0: continue
                # Native math/prose blocks can contain a displaced integral or
                # subscript tail. A change of x-start is not a new column there.
                if any(MATH_FONT.search(s.get('font','')) for line in native.get('lines',[]) for s in line.get('spans',[])):
                    expanded.append(native)
                    continue
                groups=[]
                for line in native.get('lines',[]):
                    r=_rect(line['bbox'])
                    group=next((g for g in groups if abs(g[0]['bbox'][0]-r.x0)<page.rect.width*.20),None)
                    if group is None: groups.append([line])
                    else: group.append(line)
                for group in groups:
                    expanded.append({**native,'lines':group,'bbox':_box(_union([_rect(l['bbox']) for l in group]))})
            raw = [_text_block(b,i) for i,b in enumerate(expanded)]
            texts = [b for b in raw if b]
            content = ''.join(b['text'] for b in texts)
            bad = sum(c=='\ufffd' or 0xE000 <= ord(c) <= 0xF8FF or ord(c)<32 and c not in '\n\t\r' for c in content)
            if bad > max(2,len(content)*float(config.get('maxInvalidCharacterRatio',.015))):
                _issue(issues,num,'Text contains replacement/private-use characters; mapping is unusable.','TEXT_LAYER_UNUSABLE')
            images = visible_image_rects(page)
            coverage = max([_area(r & page.rect)/max(1,_area(page.rect)) for r in images] or [0])
            if coverage >= float(config.get('scanImageCoverage',.75)):
                traces = page.get_texttrace()
                hidden = any(s.get('type')==3 or s.get('opacity',1)==0 for s in traces)
                if hidden or _scan_rows(page):
                    scanned.append(num)
                else:
                    _issue(issues,num,'Large raster page could be a scan or full-page illustration; review required.')
            all_pages.append((texts,images))
        if scanned:
            code = 'UNSUPPORTED_SCANNED_PDF' if len(scanned)==len(doc) else 'UNSUPPORTED_MIXED_PDF'
            issues.append({'code':code,'message':'Raster body/OCR page detected; no partial translation is allowed.','pages':scanned})
        # Recurring margin strings are layout furniture; isolated unknown text stays.
        furniture = Counter()
        for page,(texts,_) in zip(doc,all_pages):
            for b in texts:
                if b['_rect'].y1 < page.rect.height*.075 or b['_rect'].y0 > page.rect.height*.925:
                    furniture[re.sub(r'\d+','#',b['text'])] += 1
        sizes = [s['size'] for texts,_ in all_pages for b in texts for s in b['_spans'] if len(s.get('text',''))>25]
        font_counts=Counter()
        for texts,_ in all_pages:
            for b in texts:
                for span in b['_spans']:
                    font_counts[round(span['size'],1)] += min(20,len(span.get('text','').strip()))
        body_size = font_counts.most_common(1)[0][0] if font_counts else 11
        counters = Counter()
        in_references = False
        front_matter_end = None
        if all_pages:
            boundaries = [b['_rect'].y0 for b in all_pages[0][0]
                          if re.match(r'^(?:abstract|introduction|1[. ]+introduction|摘要)(?:\s|$|[.:：])', b['text'], re.I)]
            front_matter_end = min(boundaries) if boundaries else doc[0].rect.height*.25
        for page,(texts,images) in zip(doc,all_pages):
            num = page.number+1
            # Recognize only the well-defined arXiv margin stamp, not arbitrary
            # rotated prose. Chart-axis labels are handled after asset grouping.
            stamps = [b for b in texts if b['_rect'].x1 < page.rect.width*.08
                      and re.fullmatch(r'arXiv:\d{4}\.\d{4,5}v\d+\s+\[[^\]]+\]\s+\d{1,2}\s+[A-Za-z]{3}\s+\d{4}', b['text'])]
            if stamps:
                warnings.append({'code':'ARXIV_MARGIN_STAMP','pages':[num], 'message':'Recognized non-body arXiv margin stamp omitted.'})
                texts=[b for b in texts if b not in stamps]
            texts = [b for b in texts if not ((b['_rect'].y1<page.rect.height*.075 or b['_rect'].y0>page.rect.height*.925)
                     and (re.fullmatch(r'\s*\d+\s*',b['text']) or furniture[re.sub(r'\d+','#',b['text'])]>=max(2,len(doc)*.6)))]
            # Rule-based table detection uses lines plus native text geometry.
            table_rects=[]
            try:
                for table in page.find_tables().tables:
                    if table.row_count>=2 and table.col_count>=2: table_rects.append(_rect(table.bbox))
            except Exception as exc:
                _issue(issues,num,'Table detection failed: '+type(exc).__name__)
            regions = asset_regions(page, texts, body_size)
            for region in display_equation_regions(texts, body_size, page.rect.width):
                if not any(_overlap(region, r) >= _area(region)*.98 for r in regions):
                    regions.append(region)
            texts=_partition_text_regions(texts,regions)
            assigned=set()
            for ri,region in enumerate(regions):
                inside=[b for b in texts if _overlap(b['_rect'],region)/max(1,_area(b['_rect']))>=.98]
                if inside: region |= _union([b['_rect'] for b in inside])
                assigned.update(b['_number'] for b in inside)
                captions=[]
                for b in texts:
                    if b['_number'] in assigned or not CAPTION.match(b['text']): continue
                    if any(_overlap(b['_rect'], other) >= _area(b['_rect'])*.98 for j,other in enumerate(regions) if j != ri): continue
                    r=b['_rect']
                    gap=min(abs(r.y0-region.y1),abs(region.y0-r.y1))
                    horizontal=max(0,min(r.x1,region.x1)-max(r.x0,region.x0))
                    if gap<=max(32,body_size*3) and horizontal>min(r.width,region.width)*.45 and b['_size']<=body_size*1.12:
                        captions.append(b)
                if len(captions)>1:
                    _issue(issues,num,'Multiple candidate captions for one asset.')
                elif captions:
                    b=captions[0]; region |= b['_rect']; assigned.add(b['_number'])
                regions[ri]=region
            items=[]
            for region in regions:
                # Expanding an asset must not take a fragment of unrelated prose.
                for b in texts:
                    fraction=_overlap(b['_rect'],region)/max(1,_area(b['_rect']))
                    if .01 < fraction < .98:
                        _issue(issues,num,'Asset boundary intersects a text block; clipping could lose or duplicate text.')
                    if fraction>=.98: assigned.add(b['_number'])
                items.append({'type':'asset','text':'','translate':False,'sources':[{'page':num,'bbox':_box(region)}],
                              '_rect':region,'protected':{},'evidence':['image/vector/table/display geometry']})
            for b in texts:
                if b['_number'] in assigned: continue
                text=b['text']
                if any(line.get('dir',(1,0)) != (1,0) for line in b['_raw'].get('lines',[])):
                    _issue(issues,num,'Vertical or rotated text outside a preserved asset requires review.')
                if CAPTION.match(text):
                    _issue(issues,num,'Caption has no confidently associated image/table region.')
                if re.search(r'\b(?:page|pp?\.)\s+\d+|第\s*\d+\s*页',text,re.I):
                    warnings.append({'code':'PAGE_REFERENCE_UNRESOLVED','pages':[num],'message':'Source page-number reference may change after reflow.'})
                kind='body'
                if REFERENCE.fullmatch(text): kind='reference'
                elif b['_size'] > body_size*1.18 or (len(text)<120 and any(s.get('flags',0)&16 for s in b['_spans'])): kind='heading'
                # Metadata cues apply only before the first abstract/introduction.
                # A URL, DOI mention or affiliation word in prose must not exempt it.
                front = num == 1 and b['_rect'].y0 < front_matter_end
                author_line = re.fullmatch(r'[A-Z][a-z]+(?: [A-Z]\.)? [A-Z][a-z]+(?:[,;] (?:and )?[A-Z][a-z]+ [A-Z][a-z]+)*', text)
                if front and (author_line or re.search(r'\b(?:university|institute|department|laboratory)\b|@|^(?:doi\s*[:.]|https?://doi\.)', text, re.I)):
                    kind='metadata'
                protected={}
                translate=kind not in ('reference','metadata')
                # Protection is deferred until final reading order/reference classification.
                item={**b,'type':kind,'text':text,'translate':translate,'protected':protected,
                      'sources':[{'page':num,'bbox':_box(b['_rect'])}], 'evidence':['native text geometry/font']}
                if b['_size']<body_size*.84 and b['_rect'].y0>page.rect.height*.72 and re.match(r'^\d+\s',text):
                    item['type']='footnote'
                    item['_footnoteMarker']=re.match(r'^(\d+)\s',text).group(1)
                items.append(item)
            # Short, aligned cell-like lines outside recognized assets are unsafe unruled tables.
            candidates=[b for b in items if b['type']=='body' and len(b['text'])<45
                        and not any(MATH_FONT.search(s.get('font','')) for s in b.get('_spans',[]))
                        and not re.fullmatch(r'\s*\(\d+[a-z]?\)\s*',b['text'])]
            for b in candidates:
                peers=[c for c in candidates if abs(c['_rect'].y0-b['_rect'].y0)<3]
                if len(peers)>=3:
                    _issue(issues,num,'Aligned short text cells may form an unruled table; boundary review required.')
                    break
            ordered=_ordered(items,page.rect.width,issues,num)
            notes_by_anchor = {}
            for note in list(ordered):
                marker=note.get('_footnoteMarker')
                if marker is None: continue
                matches=[]
                for candidate in ordered:
                    if candidate is note or candidate['type']=='footnote' or not candidate.get('translate'): continue
                    for span in candidate.get('_spans',[]):
                        if span.get('text','').strip()==marker and span.get('flags',0)&1:
                            matches.append((candidate,span))
                if len(matches)!=1:
                    _issue(issues,num,'Footnote anchor is absent or ambiguous.')
                    continue
                anchor,span=matches[0]
                counters['FN']+=1
                token='{{FN_%05d}}' % counters['FN']
                anchor.setdefault('_footnoteTokens',{})[id(span)]=token
                note['_anchor']=anchor
                notes_by_anchor.setdefault(id(anchor),[]).append(note)
            # Insert all notes together, retaining their source order and all tokens.
            linked_notes={id(note) for notes in notes_by_anchor.values() for note in notes}
            ordered=[entry for item in ordered if id(item) not in linked_notes
                     for entry in [item]+notes_by_anchor.get(id(item),[])]
            for item in ordered:
                if in_references and item.get('type') == 'heading' and _appendix_heading(item.get('text','')):
                    in_references=False
                    item['evidence'].append('post-reference appendix/supplement heading')
                if item['type']=='reference': in_references=True
                if in_references and item['type']!='asset':
                    item['type']='reference'
                    item['translate']=False
                    item['text']=_join_lines([''.join(s.get('text','') for s in line.get('spans',[])) for line in item['_raw'].get('lines',[])])
                    item['protected']={}
                elif item.get('translate'):
                    item['text'],item['protected']=_protect(item,num,counters,issues)
                    if item.get('_footnoteMarker'):
                        counters['FN']+=1
                        token='{{FN_%05d}}' % counters['FN']
                        marker=item['_footnoteMarker']
                        item['text']=re.sub(r'^'+re.escape(marker)+r'(?=\s)', lambda _:token, item['text'],count=1)
                        item['protected'][token]={'kind':'literal','text':marker}
                item['blockId']='b%06d' % (len(blocks)+1)
                item['order']=len(blocks)
                if item.get('_anchor'): item['anchorBlockId']=item['_anchor']['blockId']
                blocks.append({k:v for k,v in item.items() if not k.startswith('_')})
        # Keep paragraph spans explicit rather than guessing cross-page continuations.
        result['diagnostics']={'scanPages':scanned,'bodyFontSize':body_size,'pageRoles':['review' if any(n+1 in i['pages'] for i in issues) else 'text_or_vector' for n in range(len(doc))]}
        return result
    finally:
        doc.close()
