#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Optional limited AI triage of PUBLIC bibliographic/registry metadata; not medical conclusions.

Requires OPENAI_API_KEY in GitHub Actions secrets. The review is public on GitHub Pages.
"""
import datetime as dt
import html
import json
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
import pharma_lab as lab

ROOT = Path(__file__).resolve().parent
SITE = ROOT / 'site'

def build():
    key = os.getenv('OPENAI_API_KEY','').strip()
    if not key:
        print('AI brief disabled (no OPENAI_API_KEY)')
        # No false promise that optional AI report is live.
        (SITE/'ai_review.html').unlink(missing_ok=True)
        return
    db=ROOT/'data'/'pharma_lab.sqlite3'
    con=lab.open_db(db)
    rows=lab.get_state(con)
    if not rows:
        print('No source items; AI brief omitted')
        return
    today=dt.datetime.now(ZoneInfo('Asia/Seoul'))
    # Only public metadata and safe excerpts, no patient data and no full text.
    items=[]
    for x in rows[:24]:
        items.append({'id':x['provider']+':'+x['uid'],'source':x['provider'],
             'date':x['event_date'],'drug':x['drug'],'title':x['title'][:240],
             'source_url':x['url'],'metadata_note':x['summary'][:250]})
    msg = ('당신은 약사 대상 공개 의약품 서지정보 모니터링 보조 편집자입니다. 입력에는 논문 초록이나 전문, 임상결과 표, ' 
           '식약처 허가원문이 없습니다. 입력된 제목과 등록/라벨 메타데이터만으로 효능·안전성 결론을 내리지 마세요. ' 
           '제공된 출처 외의 사실, 권고·용량·국내 허가여부를 추정하지 마세요. ' 
           '최대 8건을 선택하여 1) 관심을 가질 이유(자료 유형과 변화 중심), 2) 확실히 확인된 사실, ' 
           '3) 추가로 직접 확인할 사항(연구 대상, 결과, 식약처 허가 적용 등), 4) 공식 원문 URL을 각각 작성하세요. ' 
           '문구는 짧고 한국어로. 모든 아이템은 ID와 출처 URL을 명시하세요. ' 
           '전체 자료는 자동 수집된 일부 목록이며 미수집 자료가 있을 수 있다고 첫 줄에 적으세요.')
    payload={'model':(os.getenv('OPENAI_MODEL') or 'gpt-4.1-mini'),
             'instructions':msg,'input':json.dumps(items, ensure_ascii=False),
             'max_output_tokens':2300,'store':False}
    req=Request('https://api.openai.com/v1/responses',
                data=json.dumps(payload,ensure_ascii=False).encode('utf-8'),method='POST',
                headers={'Authorization':'Bearer '+key,'Content-Type':'application/json',
                         'User-Agent':'DiabetesPharmaLab/1.0'})
    with urlopen(req,timeout=120) as f:
        data=json.loads(f.read().decode('utf-8'))
    texts=[]
    for out in data.get('output',[]):
        for c in out.get('content',[]):
            if c.get('type')=='output_text' and c.get('text'):
                texts.append(c['text'])
    if not texts:
        raise ValueError('No output_text in model response')
    body='\n\n'.join(texts)
    document=f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>AI 선별 초안 · 당뇨병 치료제</title><style>body{{font:16px/1.75 system-ui,'Malgun Gothic',sans-serif;max-width:840px;margin:38px auto;padding:0 18px;color:#1a2c43;background:#f8fafc}}h1{{font-size:29px}}.box{{white-space:pre-wrap;background:white;padding:23px;border:1px solid #dce5ef;border-radius:12px;overflow-wrap:anywhere}}.warn{{padding:15px;background:#fff5e0;border:1px solid #e5c791;border-radius:10px;font-size:14px}}a{{color:#1b588c}}</style></head><body><p><a href="index.html">← 자료 대시보드</a></p><h1>AI 선별·검토 질문 초안</h1><p>{html.escape(today.strftime('%Y-%m-%d %H:%M'))} KST · 모델 {html.escape(str(payload['model']))}</p><p class="warn">이 페이지는 AI가 공개 서지·임상등록 메타데이터만으로 만든 <b>검증 전 편집 초안</b>입니다. 논문의 실제 결과·국내 허가·안전성을 판단하는 자료가 아닙니다. 약사의 공식 원문 대조가 필요합니다.</p><div class="box">{html.escape(body)}</div></body></html>'''
    (SITE/'ai_review.html').write_text(document,encoding='utf-8')
    print('Optional AI brief generated')

if __name__=='__main__':
    try:
        build()
    except Exception as e:
        print('AI brief failed; source dashboard unaffected:',e,file=sys.stderr)
        # Do not publish a stale AI report when API request has failed.
        (SITE/'ai_review.html').unlink(missing_ok=True)
        sys.exit(0)
