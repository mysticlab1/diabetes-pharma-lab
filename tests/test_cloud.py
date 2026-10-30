import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pharma_lab as lab
import update_site as app

CFG=json.loads((Path(__file__).resolve().parents[1]/'config.json').read_text(encoding='utf-8'))

def fake_get_json(url, params=None, headers=None, tries=3):
    if 'esearch.fcgi' in url:
        return {'esearchresult':{'idlist':['76543210']}}
    if 'esummary.fcgi' in url:
        return {'result':{'76543210':{'title':'Trial in Type 2 diabetes of a public medicine', 'pubdate':'2026 Oct 29', 'source':'Test Index'}}}
    if '/api/v2/studies' in url:
        return {'studies':[{'protocolSection': {
            'identificationModule':{'nctId':'NCT12345678','briefTitle':'Phase III study'},
            'statusModule':{'lastUpdatePostDateStruct':{'date':'2026-10-28'},'overallStatus':'RECRUITING'},
            'designModule':{'phases':['PHASE3'],'enrollmentInfo':{'count':300}},
            'armsInterventionsModule':{'interventions':[{'name':'metformin'}]}}}]}
    if '/drug/label.json' in url:
        return {'results':[{'set_id':'ab-001','effective_time':'20261020','openfda':{'brand_name':['Sample US label']},'boxed_warning':['Do not infer conclusions']}]}
    raise AssertionError(url)

class CloudTest(unittest.TestCase):
    def test_idempotence_and_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp); con=lab.open_db(p/'db.sqlite3')
            with patch.object(lab,'get_json',side_effect=fake_get_json), patch.object(lab.time,'sleep',return_value=None), patch.object(app,'SITE',p/'site'):
                self.assertEqual(app.run_fetches(con,CFG),[])
                self.assertEqual(con.execute('select count(*) from events').fetchone()[0],3)
                self.assertEqual(app.run_fetches(con,CFG),[])
                self.assertEqual(con.execute('select count(*) from change_log').fetchone()[0],0)
                app.render(con,days=1000)
                out=(p/'site'/'index.html').read_text(encoding='utf-8')
                self.assertIn('당뇨병 치료제 정보분석실',out)
                self.assertIn('NCT12345678', (p/'site'/'feed.json').read_text(encoding='utf-8'))
                self.assertIn('openFDA',out)

    def test_failed_source_is_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp); con=lab.open_db(p/'db.sqlite3')
            with patch.object(lab,'get_json',side_effect=RuntimeError('source unavailable')),patch.object(app,'SITE',p/'site'):
                failed=app.run_fetches(con,CFG)
                self.assertEqual(len(failed),3)
                app.render(con)
                self.assertIn('일부 자료원의 자동 수집에 문제가', (p/'site'/'index.html').read_text(encoding='utf-8'))

    def test_html_escaped(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp); con=lab.open_db(p/'db.sqlite3')
            lab.store_event(con,{'provider':'PUBMED','uid':'2222','drug':'x','kind':'test',
                'event_date':'2026-10-29','status':'test','importance':'test',
                'title':'<img src=x onerror=alert(1)>','url':'https://pubmed.ncbi.nlm.nih.gov/2222/',
                'summary':'<script>alert(1)</script>'})
            with patch.object(app,'SITE',p/'site'):
                app.render(con,days=1000)
                body=(p/'site'/'index.html').read_text(encoding='utf-8')
                self.assertNotIn('<img src=x',body)
                self.assertNotIn('<script>alert(1)</script>',body)
                self.assertIn('&lt;img',body)

if __name__=='__main__':
    unittest.main()
