"""DOM-preserving HTML translation. Source scripts never execute."""
from pathlib import Path
import base64
import hashlib
import html
import json
import re
import urllib.parse
from bs4 import BeautifulSoup, NavigableString, Tag, Comment
from .html_input import fetch, permitted_url

TOKEN = re.compile(r'\{\{[^{}]+\}\}')

def parse_html(path, directory, config, source_url=None):
    path = Path(path)
    soup = BeautifulSoup(path.read_bytes(), 'html.parser')
    article = soup.select_one('article.ltx_document,article,main,.ltx_document')
    if article is None:
        raise ValueError('NEEDS_REVIEW: no article/main document')
    if article.find(['iframe', 'object', 'embed', 'canvas']):
        raise ValueError('NEEDS_REVIEW: unsupported embedded content')
    # MathML and pre-rendered SVG survive unchanged; script-only math needs explicit conversion.
    for node in soup.find_all('script'):
        if node.get('type', '').split(';')[0].strip().lower() == 'math/tex':
            raise ValueError('NEEDS_REVIEW: script-only TeX must first be rendered to MathML or SVG')
        node.decompose()
    for node in soup.find_all(['base', 'iframe', 'object', 'embed', 'form']):
        node.decompose()
    for node in soup.find_all(True):
        for attr in list(node.attrs):
            if attr.lower().startswith('on') or attr.lower() in {'srcdoc', 'nonce', 'integrity'}:
                del node[attr]
        for attr in ('href', 'src', 'xlink:href'):
            if str(node.get(attr, '')).lstrip().lower().startswith(('javascript:', 'vbscript:')):
                del node[attr]
    for comment in soup.find_all(string=lambda s:isinstance(s,Comment)): comment.extract()
    resources=[]
    def resource(url, base=source_url):
        if url.startswith('data:'): return url
        if url.startswith('#'): return url
        if base:
            absolute=urllib.parse.urljoin(base,url)
            permitted_url(absolute,urllib.parse.urlsplit(source_url).hostname)
            data=fetch(absolute,20*1024*1024,urllib.parse.urlsplit(source_url).hostname)
        else:
            parsed=urllib.parse.urlsplit(url)
            if parsed.scheme or parsed.netloc: raise ValueError('HTML_RESOURCE_UNSUPPORTED: remote resource in local HTML')
            target=(path.parent/urllib.parse.unquote(parsed.path)).resolve(strict=True)
            if not target.is_relative_to(path.parent.resolve()): raise ValueError('PATH_NOT_ALLOWED: HTML resource escapes source directory')
            if target.stat().st_size>20*1024*1024: raise ValueError('LIMIT_EXCEEDED: resource too large')
            data=target.read_bytes();resources.append({'path':str(target),'sha256':hashlib.sha256(data).hexdigest()})
        import mimetypes
        mime=mimetypes.guess_type(url.split('?')[0])[0] or 'application/octet-stream'
        return 'data:'+mime+';base64,'+base64.b64encode(data).decode()
    def css(text, base=source_url):
        if re.search(r'@import',text,re.I): raise ValueError('HTML_RESOURCE_UNSUPPORTED: CSS imports must be flattened first')
        return re.sub(r'url\(\s*[\"\']?([^\)\"\']+)[\"\']?\s*\)',lambda m:'url("'+resource(m[1],base)+'")',text)
    for link in list(soup.find_all('link')):
        if 'stylesheet' in link.get('rel',[]):
            href=link.get('href','')
            if source_url:
                absolute=urllib.parse.urljoin(source_url,href)
                raw=fetch(absolute,4*1024*1024,urllib.parse.urlsplit(source_url).hostname).decode('utf-8')
                value=css(raw,absolute)
            else:
                target=(path.parent/urllib.parse.unquote(href)).resolve(strict=True)
                if not target.is_relative_to(path.parent.resolve()): raise ValueError('PATH_NOT_ALLOWED: stylesheet escapes source directory')
                resources.append({'path':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
                # Relative CSS resources need a base path; reject rather than silently break them.
                raw=target.read_text('utf-8')
                if re.search(r'url\(|@import',raw,re.I): raise ValueError('HTML_RESOURCE_UNSUPPORTED: local stylesheet resources must be embedded')
                value=raw
            style=soup.new_tag('style');style.string=value;link.replace_with(style)
        else: link.decompose()
    for style in soup.find_all('style'): style.string=css(style.get_text())
    for node in soup.find_all(True):
        if node.has_attr('style'): node['style']=css(node['style'])
        if node.has_attr('srcset'): raise ValueError('HTML_RESOURCE_UNSUPPORTED: srcset must be resolved first')
        if node.has_attr('src'): node['src']=resource(node['src'])
        if node.name in {'image','use'}:
            for attr in ('href','xlink:href'):
                if node.has_attr(attr): node[attr]=resource(node[attr])
        if source_url and node.name=='a' and node.get('href') and not node['href'].startswith('#'):
            node['href']=urllib.parse.urljoin(source_url,node['href'])
    blocks=[];nodes={};math_count=len(article.find_all('math'))+len(article.select('svg'))
    candidates=article.find_all(['h1','h2','h3','h4','h5','h6','p','figcaption','caption','td','th','li'])
    for node in candidates:
        if node.find(['p','li','td','th','figcaption','caption']): continue
        if node.find_parent(['math','svg']) or any('ltx_bibliography' in p.get('class',[]) or 'ltx_equation' in p.get('class',[]) for p in [node]+list(node.parents) if isinstance(p,Tag)): continue
        bid=f'h{len(blocks)+1:06d}';protected={};events={}
        def marker(value,kind,event=None):
            token='{{HTML_'+bid+'_'+str(len(protected))+'}}';protected[token]={'kind':kind,'html':value}
            if event: events[token]=event
            return token
        def flatten(child):
            if isinstance(child,NavigableString): return str(child)
            if child.name in {'math','svg','img','br','code','pre'} or (child.name=='a' and ('ltx_ref' in child.get('class',[]) or 'ltx_cite' in child.get('class',[]) or re.fullmatch(r'\s*\[[^]]+\]\s*',child.get_text()))) or 'ltx_Math' in child.get('class',[]):
                return marker(str(child),'math' if child.name in {'math','svg'} or 'ltx_Math' in child.get('class',[]) else 'node')
            opening=str(child).split('>',1)[0]+'>'
            key=str(len(protected))
            return marker(opening,'open',['open',key])+''.join(flatten(c) for c in child.children)+marker('</'+child.name+'>','close',['close',key])
        text=''.join(flatten(c) for c in node.children)
        if not TOKEN.sub('',text).strip(): continue
        node['data-dsh-block']=bid;nodes[bid]={'protected':protected,'events':events}
        blocks.append(dict(blockId=bid,type=node.name,text=text,translate=True,protected=protected,sources=[{'anchor':node.get('id',bid)}]))
    if not blocks: raise ValueError('NEEDS_REVIEW: no translatable article text')
    # Refuse untranslated prose outside supported blocks instead of silently omitting it.
    for text_node in article.find_all(string=True):
        if not text_node.strip(): continue
        ancestors=[p for p in text_node.parents if isinstance(p,Tag)]
        if any(p.has_attr('data-dsh-block') or p.name in {'math','svg','style','pre','code'} or any(c in p.get('class',[]) for c in ('ltx_bibliography','ltx_equation','ltx_Math','ltx_authors','ltx_dates')) for p in ancestors): continue
        raise ValueError('NEEDS_REVIEW: article text outside supported paragraph/table/heading blocks')
    template=directory/'template.html';template.write_text(str(soup),'utf-8')
    return dict(blocks=blocks,issues=[],warnings=['HTML layout and formula preservation are checked structurally; translation meaning requires review.'],pages=0,inputFormat='html',parserVersion='html-dom-1',sourceUrl=source_url,mathCount=math_count,inputResources=resources,htmlNodes=nodes,htmlTemplate=str(template),htmlTemplateHash=hashlib.sha256(template.read_bytes()).hexdigest())

def export_html(job, output):
    template=Path(job['htmlTemplate'])
    if hashlib.sha256(template.read_bytes()).hexdigest()!=job['htmlTemplateHash']: raise ValueError('STALE_VERSION: HTML template changed')
    soup=BeautifulSoup(template.read_text('utf-8'),'html.parser')
    for bid, spec in job['htmlNodes'].items():
        text=job['translations'][bid];stack=[]
        for token in TOKEN.findall(text):
            event=spec['events'].get(token)
            if event:
                if event[0]=='open': stack.append(event[1])
                elif not stack or stack.pop()!=event[1]: raise ValueError('PLACEHOLDER_MISMATCH: inline formatting is improperly nested')
        if stack: raise ValueError('PLACEHOLDER_MISMATCH: unclosed inline formatting')
        value=html.escape(text)
        for token,item in spec['protected'].items(): value=value.replace(token,item['html'])
        node=soup.find(attrs={'data-dsh-block':bid});node.clear()
        fragment=BeautifulSoup(value,'html.parser')
        for child in list(fragment.contents): node.append(child)
        del node['data-dsh-block']
    root=soup.find('html')
    if root: root['lang']=job['targetLanguage']
    original=BeautifulSoup(template.read_text('utf-8'),'html.parser')
    for tag in ('math','svg'):
        if [str(n) for n in soup.find_all(tag)] != [str(n) for n in original.find_all(tag)]:
            raise ValueError('OUTPUT_VALIDATION_FAILED: formula nodes changed')
    output.write_text(str(soup),'utf-8')
    return dict(valid=True,inputFormat='html',mathCount=job['mathCount'],translatedBlocks=len(job['translations']),warnings=job['warnings'],formulaOrigin='Original HTML nodes; no formula recognition or re-typesetting')
