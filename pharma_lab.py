#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diabetes Pharma Intelligence Lab v0.1 (standard-library only).

Official public sources: PubMed E-utilities, ClinicalTrials.gov API v2,
openFDA labelling API. MFDS items are curated/manual in this version.
The program does not submit patient data and never edits dispensing systems.
"""
import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
from pathlib import Path
import sqlite3
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
UA = "DiabetesPharmaIntelligenceLab/0.1 (local clinical research monitor)"
DB_DEFAULT = HERE / "pharma_lab.sqlite3"


def now_kst():
    try:
        return dt.datetime.now(ZoneInfo("Asia/Seoul"))
    except Exception:
        return dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))


def get_json(url, params=None, headers=None, tries=3):
    final = url + (("&" if "?" in url else "?") + urlencode(params) if params else "")
    for attempt in range(tries):
        req = Request(final, headers={"User-Agent": UA, "Accept": "application/json", **(headers or {})})
        try:
            with urlopen(req, timeout=22) as res:
                return json.loads(res.read().decode("utf-8"))
        except HTTPError as ex:
            if ex.code == 404 and "api.fda.gov" in final:
                return {}  # no matches is normal for openFDA only
            if ex.code not in (429, 500, 502, 503, 504) or attempt == tries-1:
                raise
            time.sleep(2 ** attempt + 1)
        except (URLError, TimeoutError):
            if attempt == tries-1:
                raise
            time.sleep(2 ** attempt + 1)
    return {}


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(obj):
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


def open_db(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript("""
    CREATE TABLE IF NOT EXISTS events(
      provider TEXT NOT NULL, uid TEXT NOT NULL, drug TEXT NOT NULL,
      kind TEXT NOT NULL, event_date TEXT NOT NULL, status TEXT NOT NULL,
      importance TEXT NOT NULL, title TEXT NOT NULL, url TEXT NOT NULL,
      summary TEXT NOT NULL, fingerprint TEXT NOT NULL,
      first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
      PRIMARY KEY(provider, uid));
    CREATE TABLE IF NOT EXISTS change_log(
      change_id INTEGER PRIMARY KEY AUTOINCREMENT,
      provider TEXT NOT NULL, uid TEXT NOT NULL,
      detected_at TEXT NOT NULL, old_fingerprint TEXT, new_fingerprint TEXT NOT NULL,
      change_type TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS runs(
      run_id INTEGER PRIMARY KEY AUTOINCREMENT, ran_at TEXT NOT NULL,
      source TEXT NOT NULL, result TEXT NOT NULL, info TEXT NOT NULL);
    """)
    return con


def record_run(con, source, result, info):
    con.execute("INSERT INTO runs(ran_at,source,result,info) VALUES(?,?,?,?)",
                (now_kst().isoformat(timespec="seconds"), source, result, info[:1200]))
    con.commit()


def store_event(con, raw):
    d = {key: str(raw.get(key, "")) for key in (
        "provider", "uid", "drug", "kind", "event_date", "status",
        "importance", "title", "url", "summary")}
    for required in ("provider", "uid", "title", "url"):
        if not d[required]:
            raise ValueError(f"Event missing {required}: {d}")
    if not d["url"].startswith("https://"):
        raise ValueError("Only https sources are accepted")
    h = digest({k: d[k] for k in d if k != "importance"} | {"importance": d["importance"]})
    old = con.execute("SELECT fingerprint FROM events WHERE provider=? AND uid=?",
                      (d["provider"], d["uid"])).fetchone()
    now = now_kst().isoformat(timespec="seconds")
    if old is None:
        con.execute("""INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            d["provider"], d["uid"], d["drug"], d["kind"], d["event_date"],
            d["status"], d["importance"], d["title"], d["url"], d["summary"], h, now, now))
        # Baseline import; deliberately NOT called a newly published drug development.
        action = "baseline"
    elif old["fingerprint"] != h:
        con.execute("""UPDATE events SET drug=?,kind=?,event_date=?,status=?,importance=?,
          title=?,url=?,summary=?,fingerprint=?,last_seen=? WHERE provider=? AND uid=?""", (
            d["drug"], d["kind"], d["event_date"], d["status"], d["importance"],
            d["title"], d["url"], d["summary"], h, now, d["provider"], d["uid"]))
        con.execute("""INSERT INTO change_log(provider,uid,detected_at,old_fingerprint,new_fingerprint,change_type)
          VALUES(?,?,?,?,?,?)""", (d["provider"], d["uid"], now, old["fingerprint"], h, "changed"))
        action = "changed"
    else:
        con.execute("UPDATE events SET last_seen=? WHERE provider=? AND uid=?",
                    (now, d["provider"], d["uid"]))
        action = "unchanged"
    con.commit()
    return action


def seed_sources(con):
    events = json.loads((HERE / "verified_events.json").read_text(encoding="utf-8"))
    out = {"baseline": 0, "changed": 0, "unchanged": 0}
    for e in events:
        out[store_event(con, e)] += 1
    record_run(con, "curated", "ok", str(out))
    return out


def normalize_pubmed_date(rec):
    """Use stable ISO dates for filtering; don't compare free-form date strings."""
    for field in ("sortpubdate", "epubdate", "pubdate"):
        value = str(rec.get(field, "")).strip()
        m = re.search(r"(\d{4})[/-](\d{1,2})(?:[/-](\d{1,2}))?", value)
        if m:
            yyyy, mm, dd = m.groups()
            return f"{int(yyyy):04d}-{int(mm):02d}-{int(dd or 1):02d}"
        for fmt in ("%Y %b %d", "%Y %B %d", "%Y %b", "%Y %B"):
            try:
                return dt.datetime.strptime(value, fmt).date().isoformat()
            except ValueError:
                pass
        m = re.match(r"^(\d{4})$", value)
        if m:
            return m.group(1) + "-01-01"
    return "미상"


def fetch_pubmed(con, config, contact, max_per_query=8):
    if contact and "@" not in contact:
        raise ValueError("PHARMA_CONTACT_EMAIL must be valid when provided")
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    until = now_kst().date()
    since = until - dt.timedelta(days=int(config["pubmed_days"]))
    common = {"tool": "DiabetesPharmaLab"}
    if contact:
        common["email"] = contact
    counts = {"baseline": 0, "changed": 0, "unchanged": 0}
    gathered = {}
    for group in config["pubmed_queries"]:
        query = group["query"]
        data = get_json(base + "esearch.fcgi", {
            **common, "db": "pubmed", "retmode": "json", "retmax": max_per_query,
            "sort": "pub_date", "datetype": "edat", "mindate": since.isoformat(),
            "maxdate": until.isoformat(), "term": query})
        ids = data.get("esearchresult", {}).get("idlist", [])
        time.sleep(0.4)  # under NCBI no-key 3-requests/second threshold
        if not ids:
            continue
        summary = get_json(base + "esummary.fcgi", {
            **common, "db": "pubmed", "retmode": "json", "id": ",".join(ids)})
        time.sleep(0.4)
        records = summary.get("result", {})
        for pmid in ids:
            rec = records.get(str(pmid), {})
            if not isinstance(rec, dict) or not rec.get("title"):
                continue
            d = {
                "provider": "PUBMED", "uid": pmid, "drug": group["name"],
                "kind": "논문 색인", "event_date": normalize_pubmed_date(rec),
                "status": "서지정보 등록 (연구결과 검증 전)", "importance": "검토 필요",
                "title": rec["title"].strip(), "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "summary": f"저널: {rec.get('fulljournalname') or rec.get('source','미상')}. "
                           "자동 수집한 제목·서지정보만 저장. 연구의 유효성/안전성 결과를 제목으로부터 추론하지 않음."
            }
            if pmid in gathered:
                old = gathered[pmid]
                names = set(old["drug"].split(" / "))
                names.add(group["name"])
                old["drug"] = " / ".join(sorted(names))
            else:
                gathered[pmid] = d
    for d in gathered.values():
        counts[store_event(con, d)] += 1
    return counts


def fetch_trials(con, config, per_drug=8):
    counts = {"baseline": 0, "changed": 0, "unchanged": 0}
    gathered = {}
    for drug in config["clinical_trials_drugs"]:
        res = get_json("https://clinicaltrials.gov/api/v2/studies", {
            "query.cond": "Type 2 Diabetes", "query.intr": drug,
            "format": "json", "pageSize": per_drug,
            "sort": "LastUpdatePostDate:desc"})
        for st in res.get("studies", []):
            p = st.get("protocolSection", {})
            ident = p.get("identificationModule", {})
            status = p.get("statusModule", {})
            nct = ident.get("nctId")
            if not nct:
                continue
            title = ident.get("briefTitle", "제목 없음")
            date = status.get("lastUpdatePostDateStruct", {}).get("date", "")
            enrollment = p.get("designModule", {}).get("enrollmentInfo", {}).get("count", "미상")
            arms = p.get("armsInterventionsModule", {}).get("interventions", [])
            interventions = sorted(set(i.get("name", "") for i in arms if i.get("name")))[:8]
            summary = ("연구 등록정보: 단계=" + str(p.get("designModule", {}).get("phases", ["미상"]))
                       + ", 모집상태=" + str(status.get("overallStatus", "미상"))
                       + ", 등록인원=" + str(enrollment)
                       + ", 개입=" + ", ".join(interventions)
                       + ". 임상 효과가 입증됐다는 의미는 아님.")
            d = {"provider": "CTGOV", "uid": nct, "drug": drug, "kind": "임상시험 등록정보",
                 "event_date": date or "미상", "status": status.get("overallStatus", "미상"),
                 "importance": "검토 필요", "title": title,
                 "url": f"https://clinicaltrials.gov/study/{nct}", "summary": summary}
            if nct in gathered:
                old = gathered[nct]
                names = set(old["drug"].split(" / "))
                names.add(drug)
                old["drug"] = " / ".join(sorted(names))
            else:
                gathered[nct] = d
    for d in gathered.values():
        counts[store_event(con, d)] += 1
    return counts


def fetch_fda_labels(con, config, per_drug=5):
    counts = {"baseline": 0, "changed": 0, "unchanged": 0}
    # Multiple label versions or generic products may match one ingredient.
    # Group by label SET ID and retain only the most recent edition per SET ID.
    gathered = {}
    for drug in config["fda_label_drugs"]:
        res = get_json("https://api.fda.gov/drug/label.json", {
            "search": f'openfda.generic_name:"{drug}"',
            "sort": "effective_time:desc", "limit": per_drug})
        for r in res.get("results", []):
            uid = r.get("set_id")
            if not uid:
                continue
            datestr = r.get("effective_time", "")
            if uid in gathered and datestr <= gathered[uid][0]:
                continue
            gathered[uid] = (datestr, drug, r)
    for uid, (datestr, drug, r) in gathered.items():
        label = r.get("openfda", {})
        strength = ", ".join(label.get("substance_name", [])[:3])
        title = (label.get("brand_name") or label.get("generic_name") or [drug])[0]
        if not isinstance(title, str):
            title = drug
        date = f"{datestr[:4]}-{datestr[4:6]}-{datestr[6:8]}" if len(datestr) == 8 else "미상"
        # Fingerprint changes based on clinically relevant label sections,
        # excluding copyrighted paragraphs from local storage.
        fields = ("boxed_warning", "contraindications", "warnings", "warnings_and_cautions",
                  "indications_and_usage", "adverse_reactions", "dosage_and_administration")
        clinical_hash = digest({k: r.get(k, []) for k in fields})[:14]
        d = {"provider": "OPENFDA_LABEL", "uid": uid, "drug": drug, "kind": "미국 라벨 버전",
             "event_date": date, "status": "미국 라벨 데이터 (동일 SET ID 기준)",
             "importance": "검토 필요", "title": title,
             "url": f"https://api.fda.gov/drug/label.json?search=set_id%3A%22{uid}%22&limit=1",
             "summary": f"성분: {strength or drug}. 임상 관련 라벨 항목 식별값: {clinical_hash}. "
                        "동일 SET ID의 라벨 변경 감지용이며 국내 허가 여부/임상 조치 판단 근거가 아님."}
        counts[store_event(con, d)] += 1
    return counts


def safe(text):
    return html.escape(str(text), quote=True)


def get_state(con):
    return [dict(r) for r in con.execute(
        "SELECT * FROM events ORDER BY event_date DESC, provider, uid").fetchall()]


def latest_runs(con):
    return [dict(r) for r in con.execute(
        "SELECT * FROM runs ORDER BY run_id DESC LIMIT 15").fetchall()]


def report_html(con, reportfile, only_recent_days=60):
    events = get_state(con)
    today = now_kst().date()
    cutoff = (today - dt.timedelta(days=only_recent_days)).isoformat()
    subset = [e for e in events if e["event_date"] >= cutoff or e["event_date"] == "미상"]
    runs = latest_runs(con)
    n = len(subset)
    def pills(event):
        status = "잠정" if "진행중" in event["status"] or "사전" in event["status"] else event["status"]
        return (f'<article class="event"><header><span class="tag">{safe(event["kind"])}</span>'
                f'<span class="tag subdued">{safe(event["provider"])}</span>'
                f'<span class="date">{safe(event["event_date"])}</span></header>'
                f'<h3><a href="{safe(event["url"])}" rel="noopener noreferrer" target="_blank">'
                f'{safe(event["title"])}</a></h3><div class="metadata">'
                f'<strong>{safe(event["drug"])}</strong> · {safe(status)}</div>'
                f'<p>{safe(event["summary"])}</p>'
                f'<small>최초 수집: {safe(event["first_seen"][:16])} · 최근 확인: '
                f'{safe(event["last_seen"][:16])} (KST)</small></article>')
    groups = {}
    for e in subset:
        groups.setdefault(e["kind"], []).append(e)
    sections = "".join(f'<section><h2>{safe(k)} <span class="count">{len(vals)}</span></h2>'
                       + "\n".join(pills(e) for e in vals) + '</section>' for k, vals in groups.items())
    errruns = [r for r in runs if r["result"] != "ok"]
    health = '<p class="warning">수집 오류 또는 누락 발생: ' + safe(
             "; ".join(f'{r["source"]}: {r["info"][:110]}' for r in errruns)) + '</p>' if errruns else ""
    no_events = '<p>선택 기간에 등록된 항목이 없습니다. 이는 의약품 변경이 없었다는 증거가 아닙니다.</p>'
    css = """body{font-family:system-ui,-apple-system,'Malgun Gothic',sans-serif;background:#f4f7fb;color:#182435;margin:0}
    main{max-width:980px;margin:auto;padding:32px 20px 70px}h1{font-size:29px;letter-spacing:-.4px;margin:8px 0}
    .top{background:#152941;color:white;padding:27px;border-radius:16px}.top p{color:#c9d4e2}
    .headline{display:flex;gap:15px;flex-wrap:wrap;margin:20px 0}.metric{background:white;padding:18px 21px;border-radius:12px;min-width:158px;box-shadow:0 1px 6px #d6dfeb}
    .metric b{font-size:28px;display:block;color:#12447a}.metric span{color:#657589;font-size:12px}
    section{margin-top:28px}section h2{font-size:20px}.count{font-size:13px;background:#e1ebf4;border-radius:20px;padding:3px 10px}
    article.event{background:white;border:1px solid #e3e9f1;border-radius:13px;padding:17px 20px;margin:12px 0}
    article h3{font-size:17px;margin:11px 0 8px;line-height:1.42}a{color:#155697;text-decoration:none}a:hover{text-decoration:underline}
    p{line-height:1.65}.tag{font-size:11px;padding:4px 7px;border-radius:4px;background:#deecfa;color:#22527c;margin-right:6px}
    .tag.subdued{background:#eef0f5;color:#66758c}.date{float:right;font-size:13px;color:#7b8796}
    .metadata{color:#526174;font-size:13px}.event p{font-size:14px}.event small{color:#84909f}
    .warning{background:#fff4df;border:1px solid #efcf92;padding:14px;border-radius:10px}
    .footer{font-size:13px;color:#6b798a;margin-top:30px;line-height:1.6}table{border-collapse:collapse;width:100%;background:white}
    th,td{padding:10px;text-align:left;border-bottom:1px solid #e3e9f1;font-size:12px;word-break:break-word}
    @media(max-width:550px){.top{padding:18px}.metric{flex:1;min-width:120px}article{padding:13px}.date{float:none;display:inline-block}}"""
    changed = [dict(r) for r in con.execute(
        "SELECT * FROM change_log ORDER BY change_id DESC LIMIT 20").fetchall()]
    row_changes = ''.join(
        f'<tr><td>{safe(x["detected_at"][:16])}</td><td>{safe(x["provider"])}</td>'
        f'<td>{safe(x["uid"])}</td><td>{safe(x["change_type"])}</td></tr>' for x in changed)
    row_runs = ''.join(f'<tr><td>{safe(r["ran_at"][:16])}</td><td>{safe(r["source"])}</td>'
                       f'<td>{safe(r["result"])}</td><td>{safe(r["info"][:160])}</td></tr>' for r in runs)
    body = f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>당뇨병 치료제 정보분석실</title><style>{css}</style></head><body><main>
    <div class="top"><div>DIABETES • PHARMA INTELLIGENCE</div><h1>당뇨병 치료제 정보분석실</h1>
    <p>분석 기준: {safe(today)} (한국시간) · 지난 {only_recent_days}일 자료 표시 · 원문 확인 필수</p></div>
    <div class="headline"><div class="metric"><b>{n}</b><span>표시 항목</span></div>
    <div class="metric"><b>{len(set(e["drug"] for e in subset))}</b><span>관심 약물·약물군</span></div>
    <div class="metric"><b>{len([e for e in subset if e["kind"]=="국내 허가변경 절차"])}</b><span>국내 규제 관련 항목</span></div></div>
    {health}
    <p class="warning">이 자료는 정보검색 보조용이다. 목록은 전체 의약품·논문·규제 변경을 망라하지 않으며, 임상적 권고·국내 허가·급여 적용을 확정하지 않는다. 특히 최초 수집된 자료는 새로 발생한 사건이 아닌 과거 자료의 기초 적재다.</p>
    {sections or no_events}
    <section><h2>변경 감지 기록 <span class="count">{len(changed)}</span></h2>
    <p>같은 자료 ID에서 정보가 변했을 때 기록합니다. 변경 사실 자체가 안전성 위험 증가를 뜻하지는 않습니다.</p>
    <table><thead><tr><th>탐지일(KST)</th><th>제공처</th><th>자료 ID</th><th>유형</th></tr></thead>
    <tbody>{row_changes or '<tr><td colspan="4">아직 감지한 변경 없음 (초기 적재 상태)</td></tr>'}</tbody></table></section>
    <section><h2>수집 상태</h2><table><thead><tr><th>실행시각(KST)</th><th>출처</th><th>결과</th><th>설명</th></tr></thead><tbody>{row_runs}</tbody></table></section>
    <div class="footer">공식 원문 링크를 반드시 확인. 환자 개인정보·처방내역을 입력하지 마세요. NCBI의 PubMed 서지정보 이용은 저작권 및 NLM 정책을 준수해야 합니다. 마지막 보고서 생성: {safe(now_kst().isoformat(timespec="seconds"))}</div>
    </main></body></html>'''
    reportfile.write_text(body, encoding="utf-8")
    return len(subset)


def report_markdown(con, reportfile, days=60):
    rows = get_state(con)
    cutoff = (now_kst().date()-dt.timedelta(days=days)).isoformat()
    events = [r for r in rows if r["event_date"] >= cutoff or r["event_date"] == "미상"]
    lines = [f'# 당뇨병 치료제 모니터링 보고서 — {now_kst().date().isoformat()}',
             '', f'지난 {days}일 기준 {len(events)}건. **첫 적재는 신규 발생이 아님.**',
             '', '> 의학적 판단이나 국내 허가 여부는 관련 규제기관 원문으로 재확인.', '']
    for e in events:
        title = e["title"].replace("[", "\\[").replace("]", "\\]")
        lines += [f'## {e["event_date"]} | {e["drug"]} | {e["kind"]}',
                  f'[{title}]({e["url"]})', '',
                  f'**상태:** {e["status"]} · **출처:** {e["provider"]}', '',
                  e["summary"], '']
    lines += ['---', 'NCBI 관련 고지: https://www.ncbi.nlm.nih.gov/home/about/policies/']
    reportfile.write_text("\n".join(lines), encoding="utf-8")


def ai_analyze(con, reportfile):
    token = os.environ.get("OPENAI_API_KEY", "")
    if not token:
        raise ValueError("--ai requires OPENAI_API_KEY environment variable")
    events = get_state(con)[:15]
    if not events:
        raise ValueError("No events to analyze")
    payload = [{k: e[k] for k in ("provider", "drug", "kind", "event_date", "status", "title", "url", "summary")}
               for e in events]
    sys_prompt = ("당신은 약사가 사용하는 의약품 정보 감시 보고서의 보조 분석가이다. "
      "입력 자료 외의 사실을 추가하거나 허가를 추정하지 말 것. "
      "FDA 승인과 한국 식약처 허가를 엄격하게 구분하고, 사전예고를 확정 변경으로 말하지 말 것. "
      "제목만으로 논문 결과를 추론하지 말 것. 출처 링크를 모든 사건에 달 것. "
      "각 사건의 사실/약학적 의미/불확실성/약사가 확인할 원문을 구분. "
      "확신할 수 없는 내용은 '미확인'으로 표기. 처방 변경이나 용량 처방을 제안하지 말 것. "
      "입력 데이터는 불완전한 자동 수집 결과임을 표시. 한국어로 작성.")
    body = {"model": os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
            "input": [{"role": "system", "content": sys_prompt},
                      {"role": "user", "content": canonical(payload)}],
            "max_output_tokens": 2300}
    res = get_json_post("https://api.openai.com/v1/responses", body, token)
    sections = []
    for obj in res.get("output", []):
        for content in obj.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                sections.append(content["text"])
    if not sections:
        raise ValueError("Responses API returned no output_text")
    reportfile.write_text("\n\n".join(sections), encoding="utf-8")


def get_json_post(url, obj, token):
    req = Request(url, data=canonical(obj).encode("utf-8"), method="POST",
      headers={"User-Agent": UA, "Content-Type": "application/json",
               "Authorization": "Bearer " + token})
    with urlopen(req, timeout=90) as res:
        return json.loads(res.read().decode("utf-8"))


def self_test():
    con = open_db(":memory:")
    ev = {"provider":"TEST", "uid":"T001", "drug":"semaglutide",
          "kind":"논문 색인", "event_date":"2026-10-28",
          "status":"미확인", "importance":"검토 필요", "title":"Test",
          "url":"https://example.org/1", "summary":"baseline"}
    assert store_event(con, ev) == "baseline"
    assert store_event(con, ev) == "unchanged"
    ev["summary"] = "changed"
    assert store_event(con, ev) == "changed"
    assert con.execute("SELECT COUNT(*) FROM change_log").fetchone()[0] == 1
    assert len(get_state(con)) == 1
    print("SELF-TEST PASSED: baseline/unchanged/changed, audit log, SQLite")


def main():
    p = argparse.ArgumentParser(description="당뇨병 치료제 정보분석실 v0.1")
    p.add_argument("--seed", action="store_true", help="검증된 공식 자료 4건 적재 (로컬 샘플)")
    p.add_argument("--live", action="store_true", help="실시간 공개 API 수집 시도")
    p.add_argument("--ai", action="store_true", help="OpenAI API로 보조 분석 생성")
    p.add_argument("--test", action="store_true", help="오프라인 자체 테스트")
    p.add_argument("--db", type=Path, default=DB_DEFAULT)
    p.add_argument("--days", type=int, default=60)
    args = p.parse_args()
    if args.test:
        return self_test()
    con = open_db(args.db)
    config = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
    if args.seed:
        print("Curated records:", seed_sources(con))
    if args.live:
        jobs = [("PubMed", lambda: fetch_pubmed(con, config, os.getenv("PHARMA_CONTACT_EMAIL", ""))),
                ("ClinicalTrials.gov", lambda: fetch_trials(con, config)),
                ("openFDA labels", lambda: fetch_fda_labels(con, config))]
        for name, job in jobs:
            try:
                result = job()
                print(name, result)
                record_run(con, name, "ok", str(result))
            except Exception as ex:
                reason = f"{type(ex).__name__}: {ex}"
                print("SOURCE ERROR", name, reason, file=sys.stderr)
                record_run(con, name, "ERROR", reason)
        if any(r["result"] == "ERROR" for r in latest_runs(con)[:len(jobs)]):
            print("Some sources failed; partial data only. Check source status in the report.", file=sys.stderr)
    htmlfile = HERE / "dashboard.html"
    mdfile = HERE / "latest_report.md"
    count = report_html(con, htmlfile, args.days)
    report_markdown(con, mdfile, args.days)
    print(f"Wrote {htmlfile} and {mdfile} / {count} visible records")
    if args.ai:
        try:
            ai_file = HERE / "ai_review.md"
            ai_analyze(con, ai_file)
            print(f"Wrote AI draft: {ai_file}")
        except Exception as ex:
            print("AI review failed:", ex, file=sys.stderr)
            record_run(con, "OpenAI API", "ERROR", str(ex))


if __name__ == "__main__":
    main()
