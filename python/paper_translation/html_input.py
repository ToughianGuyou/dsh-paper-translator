"""Versioned, same-origin HTML retrieval helpers.

Only versioned arXiv/ar5iv URLs are fetched. Local inputs and their resources
remain inside administrator-authorized directories. No scripts or CSS execute.
"""
from pathlib import Path
import hashlib
import html
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request

import fitz
from bs4 import BeautifulSoup, NavigableString, Tag

HOSTS = {'arxiv.org', 'ar5iv.labs.arxiv.org'}
VERSIONED = re.compile(r'^/html/(\d{4}\.\d{4,5}v\d+)/?$')


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def permitted_url(url, host=None):
    p=urllib.parse.urlsplit(url)
    if p.scheme!='https' or p.hostname not in HOSTS or p.username or p.password or p.port not in (None,443) or (host and p.hostname!=host):
        raise ValueError('HTML_RESOURCE_UNSUPPORTED: only same-origin HTTPS arXiv/ar5iv resources are allowed')
    return p


class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        permitted_url(newurl,urllib.parse.urlsplit(req.full_url).hostname)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def fetch(url,limit,host=None):
    permitted_url(url,host)
    with urllib.request.build_opener(Redirects()).open(urllib.request.Request(url,headers={'User-Agent':'dsh-paper-translation/0.2'}),timeout=20) as response:
        permitted_url(response.url,host)
        data=response.read(limit+1)
    if len(data)>limit: raise ValueError('LIMIT_EXCEEDED: HTML/resource exceeds byte limit')
    return data


def snapshot_url(url,directory,config):
    parsed=permitted_url(url)
    if not VERSIONED.fullmatch(parsed.path) or parsed.query or parsed.fragment:
        raise ValueError('INVALID_ARGUMENT: use an explicit versioned arXiv/ar5iv /html/IDvN URL')
    dest=directory/'source.html'
    dest.write_bytes(fetch(url,min(config.get('maxFileBytes',104857600),20*1024*1024),parsed.hostname))
    return dest

