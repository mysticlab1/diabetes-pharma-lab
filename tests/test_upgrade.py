import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pharma_lab as lab
import domestic_sources as d
import pubmed_evidence as pe
import update_site as up

ABSTRACT=b'''<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>1234</PMID><Article><Abstract><AbstractText Label="OBJECTIVE">Compare interventions.</AbstractText><AbstractText Label="RESULTS">Difference 2% versus 3%.</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>'''
HIRA='''<response><header><resultCode>00</resultCode></header><body><items><item><gnlNm>메트포르민</gnlNm><gnlNmCd>123456789</gnlNmCd><divNm>당뇨병용제</divNm></item></items></body></response>'''.encode('utf-8')

class UpgradeTest(unittest.TestCase):
    def test_abstract_parsing_structured(self):
        actual=pe.parse_abstracts(ABSTRACT)
        self.assertIn('OBJECTIVE: Compare interventions.', actual['1234'])
        self.assertIn('RESULTS: Difference 2% versus 3%.', actual['1234'])
    def test_hira_parsing_mocked_response(self):
        with mock.patch.object(d,'urlopen') as response:
            response.return_value.__enter__.return_value.read.return_value=HIRA
            root=d.public_data_xml(d.HIRA_ENDPOINT, {'ServiceKey':'not-a-real-key'})
            self.assertEqual(d.field(d.response_items(root)[0],'gnlNm'),'메트포르민')
    def test_secret_not_in_api_error(self):
        from urllib.error import HTTPError
        with mock.patch.object(d,'urlopen', side_effect=HTTPError('https://example.test/?ServiceKey=private',403,'Forbidden',{},None)):
            with self.assertRaises(RuntimeError) as ex:
                d.public_data_xml(d.HIRA_ENDPOINT, {'ServiceKey':'private'})
            self.assertNotIn('private',str(ex.exception))
    def test_html_status_and_recent_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)
            conn=lab.open_db(path/'db.sqlite3')
            lab.store_event(conn,{'provider':'PUBMED','uid':'1234','drug':'semaglutide','kind':'논문 색인',
                'event_date':'2026-12-31','status':'서지','importance':'검토 필요','title':'Title <demo>',
                'url':'https://pubmed.ncbi.nlm.nih.gov/1234/','summary':'Abstract not verified'})
            lab.record_run(conn,'PubMed','ok','count=1')
            with mock.patch.object(up,'SITE',path/'site'):
                with mock.patch.object(up.lab,'now_kst',return_value=lab.now_kst()):
                    up.render(conn)
            page=(path/'site'/'index.html').read_text()
            self.assertIn('미래 서지 날짜',page)
            self.assertIn('id="state"',page)
            self.assertIn('id="category"',page)
            self.assertIn('국내 자료 연결',page)
            self.assertIn('Title &lt;demo&gt;',page)
            self.assertNotIn('Title <demo>',page)

if __name__=='__main__': unittest.main()
