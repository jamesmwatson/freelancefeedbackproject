import hashlib
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer
from triage import Inventory, handler

def fixture(path):
    # Relevant columns from the existing attachment runner, with synthetic data.
    with sqlite3.connect(path) as db:
        db.executescript('''
        CREATE TABLE attachments(attachment_id INTEGER PRIMARY KEY,sha256 TEXT,
          extension TEXT,first_filename TEXT,decoded_bytes INTEGER,content_kind TEXT,
          parse_status TEXT,eligible INTEGER,screen_summary TEXT,structure_json TEXT);
        CREATE TABLE occurrences(occurrence_id INTEGER PRIMARY KEY,attachment_id INTEGER,
          message_id INTEGER,date_utc TEXT,direction TEXT,filename TEXT,subject TEXT,email_context TEXT);
        ''')
        for aid in range(1,6):
            db.execute('INSERT INTO attachments VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (aid,'hash-'+str(aid),'.xlsx' if aid<4 else '.docx','same-name.xlsx' if aid<3 else 'file-'+str(aid),2048,'spreadsheet','extracted',1,'Cached text','{}'))
        for oid,aid,direction in [(1,1,'incoming'),(2,2,'outgoing'),(3,3,'unknown'),(4,4,'incoming'),(5,4,'outgoing'),(6,5,'incoming')]:
            db.execute('INSERT INTO occurrences VALUES(?,?,?,?,?,?,?,?)',
                       (oid,aid,oid,'2026-09-01',direction,'file-'+str(aid),'Feedback review','Existing email text'))

class Workflow(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.source=Path(self.tmp.name)/'source.sqlite'
        self.decisions=Path(self.tmp.name)/'decisions.sqlite'
        fixture(self.source)
        self.before=hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.start()

    def start(self):
        self.inventory=Inventory(self.source,self.decisions)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.inventory))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.base='http://127.0.0.1:'+str(self.server.server_port)

    def stop(self):
        self.server.shutdown();self.server.server_close();self.thread.join()

    def tearDown(self):
        self.stop()
        self.assertEqual(self.before,hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.tmp.cleanup()

    def get(self,path='/api/data'):
        with urlopen(self.base+path) as response:
            return json.load(response)

    def post(self,**data):
        req=Request(self.base+'/api/decision',data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
        with urlopen(req) as response:return json.load(response)

    def test_http_load_context_and_export(self):
        self.assertEqual(len(self.get()['rows']),5)
        with urlopen(self.base) as response:self.assertIn(b'Attachment triage',response.read())
        self.assertEqual(self.get('/api/detail?id=1')['contexts'][0]['context'],'Existing email text')
        with urlopen(self.base+'/decisions.csv') as response:self.assertIn(b'attachment_id,sha256,triage_status,template,updated_utc',response.read())

    def test_decisions_independent_and_restart(self):
        self.post(ids=['1'],triage_status='possible_feedback')
        self.post(ids=['2'],triage_status='rejected')
        self.post(ids=['3'],template=True)
        self.post(ids=['1'],template=True)
        self.post(ids=['1'],template=False)
        self.stop();self.start()
        rows={str(r['attachment_id']):r for r in self.get()['rows']}
        self.assertEqual(rows['1']['triage_status'],'possible_feedback')
        self.assertFalse(rows['1']['template'])
        self.assertEqual(rows['2']['triage_status'],'rejected')
        self.assertEqual(rows['3']['triage_status'],'unreviewed')
        self.assertTrue(rows['3']['template'])
        self.assertEqual(rows['5']['triage_status'],'unreviewed')
        self.assertIsNone(rows['5']['updated_utc'])
        self.assertTrue(rows['1']['updated_utc'])

    def test_bulk_and_validation(self):
        self.post(ids=['1','4'],triage_status='rejected')
        self.assertEqual([r['attachment_id'] for r in self.get()['rows'] if r['triage_status']=='rejected'],[1,4])
        with self.assertRaises(ValueError):self.inventory.update({'ids':['1','999'],'triage_status':'possible_feedback'})
        self.assertEqual(self.get()['rows'][0]['triage_status'],'rejected')
        with self.assertRaises(ValueError):Inventory(self.source,self.source)

    def test_hash_prevents_id_reuse(self):
        self.post(ids=['1'],triage_status='possible_feedback')
        # Test another source using the same numeric ID but a different content hash.
        other=Path(self.tmp.name)/'other.sqlite';fixture(other)
        with sqlite3.connect(other) as db:db.execute("UPDATE attachments SET sha256='different' WHERE attachment_id=1")
        inv=Inventory(other,self.decisions)
        self.assertEqual(inv.data()['rows'][0]['triage_status'],'unreviewed')

    def test_corpus_adapter(self):
        cp=Path(self.tmp.name)/'corpus.sqlite'
        with sqlite3.connect(cp) as db:
            db.executescript('''CREATE TABLE attachments(id INTEGER PRIMARY KEY,sha256 TEXT,extension TEXT,first_filename TEXT,decoded_bytes INTEGER);
              CREATE TABLE attachment_occurrences(id INTEGER PRIMARY KEY,attachment_id INTEGER,message_id INTEGER,filename TEXT);
              CREATE TABLE messages(id INTEGER PRIMARY KEY,date_utc TEXT,subject TEXT,from_header TEXT,to_header TEXT,cc_header TEXT,is_sent INTEGER);
              CREATE TABLE identities(address TEXT);
              CREATE TABLE message_bodies(message_id INTEGER,visible_text TEXT);''')
            db.execute("INSERT INTO identities VALUES('owner@example.test')")
            for aid in range(1,6):
                db.execute('INSERT INTO attachments VALUES(?,?,?,?,?)',(aid,'hash-'+str(aid),'.xlsx','file.xlsx',2048))
                db.execute('INSERT INTO attachment_occurrences VALUES(?,?,?,?)',(aid,aid,aid,'file.xlsx'))
                sender='owner@example.test' if aid==2 else ('client@example.test' if aid!=3 else '')
                db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)',(aid,'2026-09-01','Feedback',sender,'owner@example.test','',0))
                db.execute('INSERT INTO message_bodies VALUES(?,?)',(aid,'Existing text'))
        inv=Inventory(cp,self.decisions)
        self.assertEqual([r['occurrences'][0]['direction'] for r in inv.data()['rows']][:3],['incoming','outgoing','unknown'])
        self.assertEqual(inv.detail('1')['contexts'][0]['context'],'Existing text')
        enriched=Inventory(self.source,self.decisions,cp)
        self.assertTrue(enriched.data()['sender_available'])
        self.assertEqual(enriched.data()['rows'][1]['occurrences'][0]['direction'],'outgoing')
        with sqlite3.connect(cp) as db:db.execute("UPDATE attachments SET sha256='mismatch' WHERE id=1")
        with self.assertRaises(ValueError):Inventory(self.source,self.decisions,cp)

if __name__=='__main__':unittest.main()
