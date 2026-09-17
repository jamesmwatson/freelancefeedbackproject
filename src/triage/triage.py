#!/usr/bin/env python3
"""Local attachment inventory viewer; source read-only, decisions stored separately."""
import argparse
import csv
import io
import json
import sqlite3
from datetime import datetime, timezone
from email.utils import getaddresses
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

STATUSES = ('unreviewed', 'possible_feedback', 'rejected')

def readonly(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    return db

class Inventory:
    def __init__(self, source, decisions, corpus=None):
        self.source, self.decisions = Path(source).resolve(), Path(decisions).resolve()
        self.corpus = Path(corpus).resolve() if corpus else None
        if self.decisions in (self.source, self.corpus):
            raise ValueError('Decisions must use a separate database.')
        with readonly(self.source) as db:
            columns = {r['name'] for r in db.execute('PRAGMA table_info(attachments)')}
            self.kind = 'attachments' if 'attachment_id' in columns else 'corpus'
            if not {'sha256', 'extension', 'first_filename'}.issubset(columns):
                raise ValueError('Expected feedback-attachments.sqlite or feedback-corpus.sqlite.')
            idcol = 'attachment_id' if self.kind == 'attachments' else 'id'
            cols = [idcol + ' AS attachment_id', 'sha256', 'extension', 'first_filename', 'decoded_bytes']
            cols += [c for c in ('content_kind', 'parse_status', 'eligible') if c in columns]
            self.rows = {str(r['attachment_id']): dict(r) for r in db.execute('SELECT '+','.join(cols)+' FROM attachments')}
            if self.kind == 'attachments':
                occurrences = [dict(r) for r in db.execute('SELECT occurrence_id,attachment_id,message_id,date_utc,direction,filename,subject FROM occurrences ORDER BY occurrence_id')]
            else:
                occurrences = [dict(r) for r in db.execute('SELECT id AS occurrence_id,attachment_id,message_id,filename FROM attachment_occurrences ORDER BY id')]
        messages, own = {}, set()
        cp = self.source if self.kind == 'corpus' else self.corpus
        if cp:
            with readonly(cp) as db:
                # Refuse to enrich from an unrelated corpus whose integer IDs happen to match.
                if self.kind == 'attachments':
                    hashes = {str(r['id']): r['sha256'] for r in db.execute('SELECT id,sha256 FROM attachments')}
                    if any(hashes.get(k) != r['sha256'] for k, r in self.rows.items()):
                        raise ValueError('Corpus attachment IDs/hashes do not match the attachment database.')
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='identities'").fetchone():
                    own = {r['address'].casefold() for r in db.execute('SELECT address FROM identities')}
                needed = {o['message_id'] for o in occurrences}
                for r in db.execute('SELECT id,date_utc,subject,from_header,to_header,cc_header,is_sent FROM messages'):
                    if r['id'] in needed:
                        messages[r['id']] = dict(r)
        for row in self.rows.values():
            row['occurrences'] = []
        for o in occurrences:
            m = messages.get(o['message_id'])
            o['sender'], o['recipients'] = '', ''
            if m:
                o.update(date_utc=m['date_utc'], subject=m['subject'], sender=m['from_header'] or '',
                         recipients=', '.join(x for x in (m['to_header'], m['cc_header']) if x))
                addresses = {a.casefold() for _, a in getaddresses([o['sender']]) if a}
                if m['is_sent'] == 1 or (addresses and addresses <= own):
                    o['direction'] = 'outgoing'
                elif addresses & own:
                    o['direction'] = 'unknown'
                elif self.kind == 'corpus':
                    o['direction'] = 'incoming' if addresses and own else 'unknown'
            if o.get('direction') not in ('incoming', 'outgoing'):
                o['direction'] = 'unknown'
            self.rows[str(o['attachment_id'])]['occurrences'].append(o)
        self.decisions.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.decisions) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS attachment_triage (
                attachment_id INTEGER NOT NULL, sha256 TEXT NOT NULL,
                triage_status TEXT NOT NULL DEFAULT 'unreviewed'
                  CHECK(triage_status IN ('unreviewed','possible_feedback','rejected')),
                template INTEGER NOT NULL DEFAULT 0 CHECK(template IN (0,1)),
                updated_utc TEXT NOT NULL,
                PRIMARY KEY(attachment_id,sha256))""")

    def data(self):
        with sqlite3.connect(self.decisions) as db:
            decisions = {(str(r[0]), r[1]): dict(triage_status=r[2], template=bool(r[3]), updated_utc=r[4])
                         for r in db.execute('SELECT * FROM attachment_triage')}
        rows = [dict(r, **decisions.get((k, r['sha256']), dict(triage_status='unreviewed', template=False, updated_utc=None)))
                for k, r in self.rows.items()]
        return dict(rows=rows, source=str(self.source), source_kind=self.kind,
                    sender_available=any(o['sender'] for r in rows for o in r['occurrences']))

    def update(self, payload):
        ids = payload.get('ids')
        if not isinstance(ids, list) or not ids or len(ids) > 100000 or any(str(i) not in self.rows for i in ids):
            raise ValueError('Unknown attachment ID or empty selection.')
        status, template = payload.get('triage_status'), payload.get('template')
        if status is not None and status not in STATUSES:
            raise ValueError('Invalid triage status.')
        if template is not None and type(template) is not bool:
            raise ValueError('Template must be true or false.')
        if status is None and template is None:
            raise ValueError('No decision supplied.')
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.decisions) as db:
            for aid in set(map(str, ids)):
                sha = self.rows[aid]['sha256']
                old = db.execute('SELECT triage_status,template FROM attachment_triage WHERE attachment_id=? AND sha256=?', (aid, sha)).fetchone()
                s = status if status is not None else (old[0] if old else 'unreviewed')
                t = int(template) if template is not None else (old[1] if old else 0)
                db.execute('INSERT OR REPLACE INTO attachment_triage VALUES(?,?,?,?,?)', (aid, sha, s, t, now))
        return dict(updated_utc=now)

    def detail(self, aid):
        row = self.rows[aid]
        with readonly(self.source) as db:
            if self.kind == 'attachments':
                r = db.execute('SELECT substr(screen_summary,1,12000),structure_json FROM attachments WHERE attachment_id=?', (aid,)).fetchone()
                snippets = [dict(r) for r in db.execute('SELECT occurrence_id,substr(email_context,1,6000) AS context FROM occurrences WHERE attachment_id=?', (aid,))]
                return dict(summary=r[0] or '', structure=r[1], contexts=snippets)
            snippets = [dict(r) for r in db.execute('SELECT ao.id AS occurrence_id,substr(b.visible_text,1,6000) AS context FROM attachment_occurrences ao LEFT JOIN message_bodies b ON b.message_id=ao.message_id WHERE ao.attachment_id=?', (aid,))]
            return dict(summary='', structure='', contexts=snippets)

def handler(inventory):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def send(self, value, status=200, mime='application/json; charset=utf-8'):
            content = value.encode('utf-8') if isinstance(value, str) else json.dumps(value, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(content)

        def allowed(self):
            host = self.headers.get('Host', '')
            return host in ('127.0.0.1:'+str(self.server.server_port), 'localhost:'+str(self.server.server_port))

        def do_GET(self):
            if not self.allowed():
                return self.send({'error':'Local requests only.'}, 403)
            route = urlparse(self.path)
            try:
                if route.path == '/':
                    return self.send(Path(__file__).with_name('index.html').read_text(encoding='utf-8'), mime='text/html; charset=utf-8')
                if route.path == '/api/data':
                    return self.send(inventory.data())
                if route.path == '/api/detail':
                    return self.send(inventory.detail(parse_qs(route.query)['id'][0]))
                if route.path == '/decisions.csv':
                    output = io.StringIO(newline='')
                    fields = ['attachment_id','sha256','triage_status','template','updated_utc']
                    writer = csv.DictWriter(output, fields, extrasaction='ignore')
                    writer.writeheader()
                    for row in inventory.data()['rows']:
                        writer.writerow({**row, 'template': int(row['template'])})
                    return self.send(output.getvalue(), mime='text/csv; charset=utf-8')
                return self.send({'error':'Not found.'},404)
            except (ValueError, KeyError) as e:
                return self.send({'error':str(e)},400)

        def do_POST(self):
            origin = self.headers.get('Origin')
            if not self.allowed() or (origin and origin != 'http://'+self.headers['Host']) or self.headers.get('Content-Type') != 'application/json':
                return self.send({'error':'Local JSON requests only.'},403)
            if self.path != '/api/decision':
                return self.send({'error':'Not found.'},404)
            try:
                length = int(self.headers.get('Content-Length','0'))
                if not 0 < length <= 2000000:
                    raise ValueError('Invalid request size.')
                result = inventory.update(json.loads(self.rfile.read(length)))
                self.send(result)
            except (ValueError, KeyError, TypeError, AttributeError) as e:
                self.send({'error':str(e)},400)
            except sqlite3.Error:
                self.send({'error':'Could not save. Check disk space and decision database permissions.'},500)
    return Handler

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path, help='Existing feedback-attachments.sqlite OR feedback-corpus.sqlite')
    p.add_argument('--corpus', type=Path, help='Optional matching feedback-corpus.sqlite, adds sender/recipient metadata')
    p.add_argument('--decisions', type=Path, help='Separate decision database; default: attachment-triage.sqlite beside source')
    p.add_argument('--port', type=int, default=8765)
    args = p.parse_args()
    try:
        inv = Inventory(args.source, args.decisions or args.source.resolve().with_name('attachment-triage.sqlite'), args.corpus)
        server = ThreadingHTTPServer(('127.0.0.1', args.port), handler(inv))
    except (ValueError, OSError, sqlite3.Error) as e:
        p.exit(1, str(e)+'\n')
    print(f'{len(inv.rows):,} attachments loaded. Open http://127.0.0.1:{server.server_port}/', flush=True)
    print(f'Decisions: {inv.decisions}\nPress Ctrl+C to stop.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == '__main__':
    main()
