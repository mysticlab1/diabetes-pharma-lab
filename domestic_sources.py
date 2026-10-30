#!/usr/bin/env python3
"""Opt-in Korean OFFICIAL API adapters. Not a reimbursement amendment or safety alert system.

A data.go.kr API key is needed, and permissions must be approved separately.
Only public, non-patient data are processed. Any source failure raises for visible reporting.
"""
import os
import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import pharma_lab as lab

MFDS_ENDPOINT = 'https://apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService08/getDrugPrdtPrmsnInq08'
HIRA_ENDPOINT = 'https://apis.data.go.kr/B551182/msupCmpnMeftInfoService/getMajorCmpnNmCdList'
MFDS_PORTAL = 'https://www.data.go.kr/data/15095677/openapi.do'
HIRA_PORTAL = 'https://www.data.go.kr/data/15021027/openapi.do'


def public_data_xml(url, params):
    req = Request(url + '?' + urlencode(params), headers={'User-Agent':lab.UA,'Accept':'application/xml, application/json'})
    try:
        with urlopen(req, timeout=30) as response:
            blob = response.read()
    except HTTPError as exc:
        # Do not expose a URL containing ServiceKey to public build logs.
        raise RuntimeError(f'공공데이터 API HTTP {exc.code} (키는 비공개)') from None
    except (URLError, TimeoutError):
        raise RuntimeError('공공데이터 API 연결 오류 (키는 비공개)') from None
    root = ET.fromstring(blob)
    code = (root.findtext('.//resultCode') or root.findtext('.//RESULT_CODE') or '').strip()
    if code and code not in ('00', '0000', '0'):
        raise RuntimeError('Public API resultCode=' + re.sub(r'[^0-9A-Za-z_-]', '', code)[:32])
    return root


def response_items(root):
    return root.findall('.//items/item') or root.findall('.//item')


def field(item, *names):
    for name in names:
        el=item.find(name)
        if el is not None and el.text and el.text.strip():
            return el.text.strip()
    return ''


def fetch_mfds(con, config, key=None):
    """Permit-directory *sample* for tracked ingredients: NOT an approvals/change alert."""
    key = key or os.getenv('DATA_GO_KR_API_KEY', '').strip()
    if not key:
        raise ValueError('data.go.kr API key not configured')
    keywords = config.get('mfds_watch_names', ['메트포르민','엠파글리플로진','세마글루티드','티르제파타이드'])
    totals={'baseline':0,'changed':0,'unchanged':0}
    for name in keywords:
        root = public_data_xml(MFDS_ENDPOINT, {
            'serviceKey':key, 'pageNo':1,'numOfRows':20,'type':'xml','item_name':name})
        # Service responses may change; reject unrecognized formats rather than claiming 0 matches.
        if root.tag.lower() not in ('response',) and root.find('.//body') is None:
            raise RuntimeError('Unexpected MFDS API response shape')
        for item in response_items(root):
            label=field(item,'ITEM_NAME','itemName','item_name')
            permit_id=field(item,'ITEM_SEQ','itemSeq','item_seq')
            if not label or not permit_id or name.replace(' ','') not in label.replace(' ',''):
                continue
            company=field(item,'ENTP_NAME','entpName','entp_name')
            permit=field(item,'ITEM_PERMIT_DATE','itemPermitDate','item_permit_date')
            date = f'{permit[:4]}-{permit[4:6]}-{permit[6:8]}' if re.fullmatch(r'\d{8}',permit) else '미상'
            ev={'provider':'MFDS_PERMIT','uid':permit_id,'drug':name,'kind':'국내 품목허가 목록(일부 조회)',
                'event_date':date,'status':'품목정보 조회; 허가 변경·최신 안전성 조치를 증명하지 않음',
                'importance':'참고','title':label,'url':MFDS_PORTAL,
                'summary':f'업체: {company or "미상"}. 식약처 품목기준코드: {permit_id}. 최초 허가일: {date}. 일부 품목 조회이며 사용상의 주의사항 변경감시가 아닙니다.'}
            totals[lab.store_event(con,ev)]+=1
        time.sleep(.2)
    return totals


def fetch_hira(con, config, key=None):
    """Ingredient classification, *not* insurance reimbursement standard amendments."""
    key = key or os.getenv('DATA_GO_KR_API_KEY', '').strip()
    if not key:
        raise ValueError('data.go.kr API key not configured')
    names=config.get('hira_watch_names',['메트포르민','엠파글리플로진','다파글리플로진','세마글루티드'])
    totals={'baseline':0,'changed':0,'unchanged':0}
    for name in names:
        root=public_data_xml(HIRA_ENDPOINT, {
            'ServiceKey':key,'numOfRows':30,'pageNo':1,'gnlNm':name})
        if root.tag.lower() not in ('response',) and root.find('.//body') is None:
            raise RuntimeError('Unexpected HIRA API response shape')
        for item in response_items(root):
            label=field(item,'gnlNm')
            code=field(item,'gnlNmCd')
            if not code or not label or name.replace(' ','') not in label.replace(' ',''):
                continue
            typ=field(item,'divNm'); strength=field(item,'iqtyTxt'); route=field(item,'injcPthNm')
            ev={'provider':'HIRA_INGREDIENT','uid':code,'drug':name,'kind':'국내 주성분·약효 분류조회',
                'event_date':'미상','status':'성분분류 조회; 급여기준 변경을 의미하지 않음',
                'importance':'참고','title':f'{label} · {code}', 'url':HIRA_PORTAL,
                'summary':f'분류: {typ or "미상"}, 함량: {strength or "미상"}, 투여경로: {route or "미상"}. 급여 인정기준·약가 변경감시와 별도 데이터입니다.'}
            totals[lab.store_event(con,ev)]+=1
        time.sleep(.2)
    return totals
