#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Refresh public-source data, preserve history, and build a standalone GitHub Pages website.

No clinical advice or inference from paper titles; no patient records; standard library only.
"""
import argparse
import datetime as dt
import html
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pharma_lab as lab
import domestic_sources as domestic

ROOT = Path(__file__).resolve().parent
SITE = ROOT / 'site'
DATA = ROOT / 'data' / 'pharma_lab.sqlite3'
PROVIDERS = ('PubMed', 'ClinicalTrials.gov', 'openFDA labels', '식약처 품목정보', '심평원 성분정보')
PROVIDER_NAMES = {'PUBMED':'PubMed', 'CTGOV':'ClinicalTrials.gov', 'OPENFDA_LABEL':'openFDA', 'MFDS_PERMIT':'식약처', 'HIRA_INGREDIENT':'심평원'}
VALID_DOMAINS = {'pubmed.ncbi.nlm.nih.gov','clinicaltrials.gov','api.fda.gov','nedrug.mfds.go.kr','www.data.go.kr'}

def esc(value):
    return html.escape(str(value or ''), quote=True)

def sanitize_url(url):
    try:
        p = urlsplit(url)
        if p.scheme == 'https' and p.hostname in VALID_DOMAINS:
            return esc(url)
    except Exception:
        pass
    return '#'

def run_fetches(con, config):
    jobs = [
        ('PubMed', lambda: lab.fetch_pubmed(con, config, os.getenv('PHARMA_CONTACT_EMAIL',''))),
        ('ClinicalTrials.gov', lambda: lab.fetch_trials(con, config)),
        ('openFDA labels', lambda: lab.fetch_fda_labels(con, config)),
    ]
    key = os.getenv('DATA_GO_KR_API_KEY', '').strip()
    if key:
        jobs.extend([
            ('식약처 품목정보', lambda: domestic.fetch_mfds(con, config, key)),
            ('심평원 성분정보', lambda: domestic.fetch_hira(con, config, key)),
        ])
    else:
        # Never count unconfigured adapters as successful sources.
        for name in ('식약처 품목정보','심평원 성분정보'):
            lab.record_run(con, name, 'NOT_CONFIGURED', '공공데이터포털 API 인증키 필요')
    errors = []
    for name, job in jobs:
        try:
            result = job()
            lab.record_run(con, name, 'ok', json.dumps(result, ensure_ascii=False))
            print(name, result)
        except Exception as ex:
            msg = f'{type(ex).__name__}: {ex}'
            lab.record_run(con, name, 'ERROR', msg)
            errors.append(name)
            print(f'[SOURCE FAILED] {name}: {msg}', file=sys.stderr)
    return errors

def render(con, days=90, max_events=300):
    SITE.mkdir(exist_ok=True, parents=True)
    rows = lab.get_state(con)
    now = lab.now_kst()
    cutoff = (now.date() - dt.timedelta(days=days)).isoformat()
    recent = [x for x in rows if x['event_date'] >= cutoff or x['event_date'] == '미상'
              or x['first_seen'][:10] >= (now.date()-dt.timedelta(days=14)).isoformat()][:max_events]
    runs = lab.latest_runs(con)
    # Verify source health based ONLY on the newest row per provider.
    by_source = {}
    for run in runs:
        if run['source'] in PROVIDERS and run['source'] not in by_source:
            by_source[run['source']] = run
    errors = [x for x in by_source.values() if x['result'] == 'ERROR']
    optional_ready = ('식약처 품목정보' in by_source and by_source['식약처 품목정보']['result'] != 'NOT_CONFIGURED')
    configured = [s for s in PROVIDERS if s in by_source and by_source[s]['result'] != 'NOT_CONFIGURED']
    passed = [s for s in configured if by_source[s]['result'] == 'ok']
    changes = [dict(x) for x in con.execute('''SELECT change_log.detected_at, change_log.provider, change_log.uid,
       events.title, events.url, events.drug FROM change_log
       LEFT JOIN events ON events.provider=change_log.provider AND events.uid=change_log.uid
       ORDER BY change_log.change_id DESC LIMIT 30''').fetchall()]
    last_collection = max((x['ran_at'] for x in by_source.values()), default=None)
    recent_first_seen = (now - dt.timedelta(days=2)).isoformat()
    cards = []
    for e in recent:
        date = e['event_date']
        first = e['first_seen']
        is_recently_discovered = bool(last_collection and first >= recent_first_seen)
        label = ('최근 수집' if is_recently_discovered else '이전 수집')
        is_future_issue = bool(re.match(r'^\d{4}-\d{2}-\d{2}$', date) and date > now.date().isoformat() and e['provider'] == 'PUBMED')
        date_note = '예정된 서지·권호 날짜' if is_future_issue else ('최종 게시/라벨 날짜 등' if e['provider']!='PUBMED' else '논문 색인 날짜')
        is_fresh_publication = bool(not is_future_issue and re.match(r'^\d{4}-\d{2}-\d{2}$',date) and
                                    (now.date()-dt.timedelta(days=7)).isoformat() <= date <= now.date().isoformat())
        marker = '최근 날짜' if is_fresh_publication else ('미래 서지 날짜' if is_future_issue else '자료')
        name = PROVIDER_NAMES.get(e['provider'], e['provider'])
        title = esc(e['title'])
        summary = esc(e['summary'])
        href = sanitize_url(e['url'])
        cards.append(f'''<article class="item" data-category="{esc(e['provider'])}" data-state="{('recent ' if is_recently_discovered else 'archive ') + ('pub7' if is_fresh_publication else '')}" data-search="{esc((e['title']+' '+e['drug']+' '+e['summary']).lower())}">
        <div class="topline"><span class="source">{esc(name)}</span><span class="date" title="{esc(date_note)}">{esc(date)} · {esc(marker)}</span></div>
        <h3><a href="{href}" target="_blank" rel="noopener noreferrer">{title}</a></h3>
        <div class="drug">{esc(e['drug'])} · {esc(e['kind'])}</div>
        <p>{summary}</p><div class="footline"><span>{esc(label)} · 최초 수집 {esc(first[:16])} KST</span><a href="{href}" rel="noopener noreferrer" target="_blank">공식 원문 ↗</a></div></article>''')
    # Technical review queue: newly updated records and recent discoveries. This
    # is not a clinical safety or treatment priority ranking.
    changed_keys={(x['provider'],x['uid']) for x in changes}
    priority_candidates=sorted(recent, key=lambda e:(
        (e['provider'],e['uid']) in changed_keys,
        e['first_seen'][:10]>=(now.date()-dt.timedelta(days=2)).isoformat(),
        e['provider'] in ('OPENFDA_LABEL','CTGOV'),
        e['first_seen']), reverse=True)[:5]
    priority_html=''.join('<li><span class="source">'+esc(PROVIDER_NAMES.get(e['provider'],e['provider']))+'</span> '
      + '<a href="'+sanitize_url(e['url'])+'" target="_blank" rel="noopener noreferrer">'+esc(e['title'])+'</a>'
      + '<small> · '+('기존 자료의 변경 감지' if (e['provider'],e['uid']) in changed_keys else '수집 후보')+'</small></li>'
      for e in priority_candidates)
    runs_html = ''.join(f'<li class="{("good" if r["result"]=="ok" else "error")}"><b>{esc(r["source"])}</b> {"정상" if r["result"]=="ok" else ("인증키 미설정" if r["result"]=="NOT_CONFIGURED" else "오류")} <small>{esc(r["ran_at"][:16])} KST</small></li>' for r in by_source.values())
    changes_html = ''.join(f'<li><span class="chgdate">{esc(c["detected_at"][:16])}</span><a href="{sanitize_url(c["url"] or "")}" target="_blank" rel="noopener noreferrer">{esc(c["title"] or c["uid"])}</a><small>{esc(c["provider"])}</small></li>' for c in changes)
    status = '수집 실행 전' if not by_source else ('일부 자료원 오류' if errors else f'{len(passed)}개 활성 자료원 마지막 실행 성공')
    info = '첫 자동 수집을 실행하면 이 자리에 공식 자료가 나타납니다.' if not by_source else ('오류가 있는 자료원은 최신성 보장 불가. 아래 상태 확인.' if errors else '마지막 실행 결과이며 포괄적 정보 감시를 보장하지 않습니다.')
    ai_link = ('<div class="alert note"><a href="ai_review.html"><b>AI 선별·검토 질문 초안 보기 →</b></a> (API 키가 설정된 경우에만 생성, 약사 검토 필요)</div>' if (SITE/'ai_review.html').exists() else '')
    health = ('<div class="alert warn">일부 자료원의 자동 수집에 문제가 있어 최신성을 보장할 수 없습니다. 자료원 상태를 확인하세요.</div>' if errors else '')
    if not by_source:
        health = '<div class="alert warn">초기 화면: 실제 자동 수집을 아직 수행하지 않았습니다. 배포 후 Actions를 실행하세요.</div>'
    css = '''
:root{color-scheme:light;--ink:#17233a;--muted:#64748b;--line:#dce5ef;--accent:#1658a7;--bg:#f5f8fc;--white:#fff}
*{box-sizing:border-box}body{font-family:system-ui,-apple-system,BlinkMacSystemFont,"Malgun Gothic",sans-serif;background:var(--bg);color:var(--ink);margin:0;line-height:1.65}
.container{max-width:1080px;margin:auto;padding:28px 20px 76px}.hero{border-radius:20px;background:linear-gradient(120deg,#122a49,#1e5687);color:white;padding:30px 34px}.eyebrow{letter-spacing:.15em;font-size:11px;color:#b6cfe9;font-weight:700}
h1{font-size:clamp(24px,3vw,38px);letter-spacing:-.04em;margin:4px 0}.hero p{max-width:720px;color:#d9e8f6;margin:6px 0}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:18px 0 24px}.metric{padding:18px 20px;background:white;border:1px solid var(--line);border-radius:14px}.metric strong{font-size:26px;display:block;line-height:1.3}.metric span{color:var(--muted);font-size:12px}
.alert{padding:13px 16px;border-radius:12px;font-size:13px;margin:14px 0}.warn{border:1px solid #efd8a6;background:#fff8e6;color:#624619}.note{border:1px solid #d4e4f2;background:#ecf5ff;color:#264c6f}
.sectionHead{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin:28px 0 12px}.sectionHead h2{font-size:20px;margin:0}.sectionHead small{color:var(--muted)}
.toolbar{display:flex;gap:10px;margin:16px 0;flex-wrap:wrap}input,select{font:inherit;border:1px solid #cdd9e5;border-radius:10px;background:white;padding:11px 13px;color:var(--ink)}input{flex:2;min-width:220px}select{flex:1;min-width:160px}
.items{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}.item{background:var(--white);border:1px solid var(--line);border-radius:14px;padding:18px 20px;min-width:0}
.topline,.footline{display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap}.source{background:#e5eff9;border-radius:6px;padding:2px 8px;font-size:12px;color:#205483;font-weight:700}.date{font-size:12px;color:var(--muted)}
h3{font-size:16px;line-height:1.48;margin:13px 0 8px;overflow-wrap:anywhere}a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}.drug{font-size:12px;color:#42607e;font-weight:650}
.item p{font-size:13px;color:#43526a;line-height:1.72}.footline{border-top:1px solid var(--line);padding-top:11px;margin-top:14px;font-size:11px;color:var(--muted)}.footline a{white-space:nowrap}
.panel{background:white;border:1px solid var(--line);border-radius:14px;padding:18px 22px}.statuses{list-style:none;padding:0;margin:0;display:grid;gap:8px}.statuses li{padding:8px 10px;background:#f6f8fa;border-radius:8px}.statuses .error{border-left:4px solid #b45309}.statuses .good{border-left:4px solid #1d8161}.statuses small{display:block;color:var(--muted)}
.changes{padding-left:20px}.changes li{margin-bottom:10px}.changes small{color:var(--muted);display:block}.chgdate{display:inline-block;width:132px;color:var(--muted);font-size:12px}
.empty{padding:28px;text-align:center;color:var(--muted);background:white;border:1px solid var(--line);border-radius:14px}.footer{color:var(--muted);font-size:12px;margin-top:34px}.label{font-size:12px;color:var(--muted)}
@media(max-width:760px){.metrics{grid-template-columns:repeat(2,1fr)}.items{grid-template-columns:1fr}.hero{padding:26px 21px}.chgdate{display:block}}'''
    cards_html = '\n'.join(cards) if cards else '<div class="empty">표시할 자료가 없습니다. 이는 새로운 의약품 정보가 없다는 뜻이 아닙니다.</div>'
    full_html = f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="refresh" content="1800"><meta name="description" content="당뇨병 치료제 PubMed, ClinicalTrials.gov, openFDA 공식 공개 정보 모니터링"><title>당뇨병 치료제 AI 정보분석실</title><style>{css}</style></head><body>
<main class="container"><header class="hero"><div class="eyebrow">DIABETES PHARMA INTELLIGENCE</div><h1>당뇨병 치료제 정보분석실</h1><p>공식 자료를 정기 수집하고 변경을 기록하는 개인 약학 정보 대시보드</p><div class="label" style="color:#d4e4f5">생성 시각: {esc(now.strftime('%Y-%m-%d %H:%M'))} KST · {esc(days)}일 이내 사건 표시</div></header>
<div class="metrics"><div class="metric"><strong>{len(recent)}</strong><span>표시된 사건</span></div><div class="metric"><strong>{len({x['uid'] for x in recent})}</strong><span>고유 자료 ID</span></div><div class="metric"><strong>{len(changes)}</strong><span>최근 변경 기록(최대 30건)</span></div><div class="metric"><strong>{len(passed)}/{len(configured)}</strong><span>활성 자료원 성공</span></div></div>
{health}{ai_link}<div class="alert note"><b>국내 자료 연결:</b> {'공공데이터포털 인증키로 식약처 품목목록·심평원 성분분류 시범 조회 중' if optional_ready else '인증키 미설정 — 현재 국내 자료 자동 수집 없음'}. <b>중요:</b> 이 두 API는 안전성서한·허가사항 변경대비표·급여기준 개정의 감시가 아닙니다. <a href="https://nedrug.mfds.go.kr/" target="_blank" rel="noopener noreferrer">의약품안전나라</a> · <a href="https://www.hira.or.kr/" target="_blank" rel="noopener noreferrer">심평원</a> 원문을 확인하세요.</div>
<div class="alert note"><b>날짜 해석:</b> '최근 수집'은 이 프로그램이 처음 본 시점이며 자료의 실제 최초 발표일이 아닙니다. 논문의 미래 날짜는 예정 권호·서지 날짜일 수 있습니다. 임상시험의 날짜는 등록정보 갱신일입니다.</div>
<section><div class="sectionHead"><h2>우선 확인할 자료</h2><small>자료 변경·최근 수집 중심의 기술적 정렬 — 임상 중요도 판정 아님</small></div><div class="panel"><ul class="changes">{priority_html or '<li>검토 후보 없음</li>'}</ul></div></section>
<section><div class="sectionHead"><h2>자료 목록</h2><small>제목·서지·등록·라벨 버전의 정보 수집이며 임상적 결론 아님</small></div><div class="toolbar"><input id="q" type="search" placeholder="약물명·논문 제목 검색" aria-label="자료 검색"><select id="category" aria-label="자료원"><option value="">모든 자료원</option><option value="PUBMED">PubMed 논문</option><option value="CTGOV">ClinicalTrials.gov 임상시험</option><option value="OPENFDA_LABEL">openFDA 미국 라벨</option><option value="MFDS_PERMIT">식약처 품목정보</option><option value="HIRA_INGREDIENT">심평원 성분분류</option></select><select id="state" aria-label="최근 여부"><option value="">전체 수집 자료</option><option value="recent">이 시스템에서 최근 수집</option><option value="pub7">최근 7일 자료일</option><option value="archive">이전 수집 자료</option></select></div><p id="count" class="label" aria-live="polite">전체 {len(recent)}건</p><div id="items" class="items">{cards_html}</div></section>
<section><div class="sectionHead"><h2>자료원 실행 상태</h2><small>마지막 수집: {esc(last_collection[:16] if last_collection else '아직 없음')} KST</small></div><div class="panel"><p>{esc(status)} — {esc(info)}</p><ul class="statuses">{runs_html or '<li>아직 수집 내역 없음</li>'}</ul></div></section>
<section><div class="sectionHead"><h2>동일 자료의 변경 이력</h2><small>최근 {len(changes)}건 표시</small></div><div class="panel"><p class="label">기존에 저장한 자료 ID에서 변경된 내용이 감지되면 기록됩니다. 새로운 자료가 추가됐다는 뜻이나 위험성 증가를 의미하지 않습니다.</p><ol class="changes">{changes_html or '<li>아직 변경 감지 기록이 없습니다.</li>'}</ol></div></section>
<footer class="footer">⚕ 정보수집·연구 보조용. 환자 개인 진료 및 처방 변경 판단에 직접 사용하지 마세요. FDA 라벨은 미국 자료이며 국내 허가·급여와 다릅니다. PubMed 서지자료는 연구 결과를 검증하지 않습니다. 논문 전문은 해당 저작권과 NLM 이용정책을 따라야 합니다. <a href="https://www.ncbi.nlm.nih.gov/home/about/policies/" rel="noopener" target="_blank">NCBI policies</a></footer></main>
<script>(function(){{const q=document.getElementById('q'),c=document.getElementById('category'),s=document.getElementById('state'),items=[...document.querySelectorAll('.item')],count=document.getElementById('count');function render(){{let n=0;for(const el of items){{const hit=el.dataset.search.includes(q.value.toLowerCase().trim())&&(!c.value||c.value===el.dataset.category)&&(!s.value||el.dataset.state.split(' ').includes(s.value));el.hidden=!hit;if(hit)n++;}}count.textContent='검색 결과 '+n+'건';}}q.addEventListener('input',render);c.addEventListener('change',render);s.addEventListener('change',render);}})();</script>
<style>.item[hidden]{{display:none!important}}</style></body></html>'''
    (SITE/'index.html').write_text(full_html, encoding='utf-8')
    (SITE/'.nojekyll').write_text('',encoding='utf-8')
    data = {
        'generated_at_kst': now.isoformat(timespec='seconds'),
        'last_collection_kst': last_collection,
        'source_health': [{'source':s, 'result':by_source[s]['result'] if s in by_source else 'NOT_RUN', 'ran_at':by_source[s]['ran_at'] if s in by_source else None} for s in PROVIDERS],
        'limitations': ['국내 품목·성분 API는 인증키 설정 시 일부 조회만 지원; 허가/급여변경 감시 아님', 'AI 분석은 별도 API 키 필요; 초록 없으면 결과분석 불가', '임상시험 등록은 효과 입증이 아님'],
        'events': [{k: e[k] for k in ('provider','uid','drug','kind','event_date','status','title','url','summary','first_seen','last_seen')} for e in recent],
        'changes': changes,
    }
    (SITE/'feed.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    lines = [f'# 당뇨병 치료제 정보 브리핑 — {now.strftime("%Y-%m-%d %H:%M")} KST','',
             f'최근 {days}일 이내 자료 {len(recent)}건 / 마지막 수집 {last_collection or "실행 전"}', '',
             '**주의:** 국내 품목·성분 시범 API는 별도 키 필요. 허가사항·급여기준 변경을 완전히 감시하지 않으며 진료·처방 판단용이 아닙니다.','']
    for e in recent[:60]:
        title = e['title'].replace('\\','\\\\').replace('[','\\[').replace(']','\\]')
        lines += [f'## {e["event_date"]} · {e["drug"]}',f'[{title}]({e["url"]})','',f'자료원: {e["provider"]} · {e["kind"]}',e['summary'],'']
    (SITE/'latest_report.md').write_text('\n'.join(lines),encoding='utf-8')
    print('Rendered', len(recent), 'events', '→', SITE)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--live',action='store_true',help='공식 API 조회 후 사이트 생성')
    p.add_argument('--db',type=Path,default=DATA)
    p.add_argument('--days',type=int,default=90)
    args=p.parse_args()
    args.db.parent.mkdir(exist_ok=True,parents=True)
    config=json.loads((ROOT/'config.json').read_text('utf-8'))
    con=lab.open_db(args.db)
    failed=run_fetches(con,config) if args.live else []
    render(con,days=args.days)
    if failed:
        print('PARTIAL DATA WARNING:',failed,file=sys.stderr)
    # One/all sources may fail but publish error status, rather than a stale green dashboard.
    return 0

if __name__=='__main__':
    sys.exit(main())
