#!/usr/bin/env python3
"""Fetch PubMed abstracts into memory for optional AI review; no abstracts persisted to public git repo."""
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import pharma_lab as lab


def parse_abstracts(xml_bytes):
    root=ET.fromstring(xml_bytes)
    extracted={}
    for art in root.findall('.//PubmedArticle'):
        pmid=(art.findtext('.//MedlineCitation/PMID') or '').strip()
        parts=[]
        for element in art.findall('.//Article/Abstract/AbstractText'):
            raw=''.join(element.itertext()).strip()
            label=element.attrib.get('Label','').strip()
            if raw:
                parts.append((label+': ' if label else '') + re.sub(r'\s+',' ',raw))
        if pmid and parts:
            extracted[pmid]='\n'.join(parts)[:6000]
    return extracted


def fetch_abstracts(pmids):
    ids=list(dict.fromkeys(x for x in pmids if re.fullmatch(r'\d{1,12}',str(x))))[:10]
    if not ids: return {}
    url='https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?' + urlencode({
        'db':'pubmed','id':','.join(ids),'retmode':'xml','tool':'DiabetesPharmaLab'})
    req=Request(url, headers={'User-Agent':lab.UA})
    with urlopen(req,timeout=35) as resp:
        return parse_abstracts(resp.read())
