#!/usr/bin/env python3
"""Build fictional fixtures for the preserved early attachment-triage app."""
import argparse
import hashlib
import json
import mailbox
import sqlite3
import subprocess
import sys
from datetime import datetime
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).with_name('fictional-feedback.json')


def build_fixture(destination):
    """Create a new demo directory; refuse to overwrite existing data."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    fixture = json.loads(FIXTURE.read_text(encoding='utf-8'))
    attachment_path, corpus_path = destination/'attachments.sqlite', destination/'corpus.sqlite'
    data = {a['id']: a for a in fixture['attachments']}
    with sqlite3.connect(attachment_path) as attachments, sqlite3.connect(corpus_path) as corpus:
        attachments.executescript('''
            CREATE TABLE attachments(attachment_id INTEGER PRIMARY KEY,sha256 TEXT,
              extension TEXT,first_filename TEXT,decoded_bytes INTEGER,content_kind TEXT,
              parse_status TEXT,eligible INTEGER,screen_summary TEXT,structure_json TEXT);
            CREATE TABLE occurrences(occurrence_id INTEGER PRIMARY KEY,attachment_id INTEGER,
              message_id INTEGER,date_utc TEXT,direction TEXT,filename TEXT,subject TEXT,email_context TEXT);
        ''')
        corpus.executescript('''
            CREATE TABLE attachments(id INTEGER PRIMARY KEY,sha256 TEXT);
            CREATE TABLE identities(address TEXT);
            CREATE TABLE messages(id INTEGER PRIMARY KEY,date_utc TEXT,subject TEXT,
              from_header TEXT,to_header TEXT,cc_header TEXT,is_sent INTEGER);
        ''')
        corpus.execute('INSERT INTO identities VALUES(?)', ('practitioner@example.test',))
        for a in data.values():
            raw = a['text'].encode('utf-8')
            digest = hashlib.sha256(raw).hexdigest()
            attachments.execute('INSERT INTO attachments VALUES(?,?,?,?,?,?,?,?,?,?)',
                (a['id'],digest,'.txt',a['filename'],len(raw),'plain_text','fictional_fixture',1,a['text'],json.dumps({'fictional':True})))
            corpus.execute('INSERT INTO attachments VALUES(?,?)', (a['id'],digest))
        box = mailbox.mbox(destination/'fictional.mbox', create=True)
        try:
            for m in fixture['messages']:
                a = data[m['attachment_id']]
                attachments.execute('INSERT INTO occurrences VALUES(?,?,?,?,?,?,?,?)',
                    (m['id'],a['id'],m['id'],m['date'],m['direction'],a['filename'],m['subject'],m['body']))
                corpus.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)',
                    (m['id'],m['date'],m['subject'],m['sender'],m['recipient'],'',int(m['direction']=='outgoing')))
                email = EmailMessage()
                email['From'], email['To'] = m['sender'], m['recipient']
                email['Subject'] = m['subject']
                email['Date'] = format_datetime(datetime.fromisoformat(m['date']))
                email['Message-ID'] = f"<demo-message-{m['id']}@example.test>"
                email['X-Gmail-Labels'] = 'Sent' if m['direction']=='outgoing' else 'Inbox'
                if m.get('reply_to'):
                    email['In-Reply-To'] = f"<demo-message-{m['reply_to']}@example.test>"
                email.set_content(m['body'])
                email.add_attachment(a['text'].encode('utf-8'),maintype='text',subtype='plain',filename=a['filename'])
                box.add(email)
            box.flush()
        finally:
            box.close()
    (destination/'fixture.sha256').write_text(hashlib.sha256(FIXTURE.read_bytes()).hexdigest()+'\n')
    return attachment_path, corpus_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve', action='store_true')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    destination = ROOT/'.demo'
    marker = destination/'fixture.sha256'
    expected = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    if destination.exists():
        required = ('attachments.sqlite','corpus.sqlite','fictional.mbox')
        if not marker.is_file() or marker.read_text().strip()!=expected or not all((destination/n).is_file() for n in required):
            parser.error('Existing .demo does not match the fixture. Move it aside or remove it after review, then rerun.')
        print('Using the existing fictional fixture; saved decisions are preserved.',flush=True)
    else:
        build_fixture(destination)
        print('Created the fictional fixture in .demo/.',flush=True)
    if args.serve:
        command = [sys.executable,str(ROOT/'src/triage/triage.py'),str(destination/'attachments.sqlite'),
                   '--corpus',str(destination/'corpus.sqlite'),'--decisions',str(destination/'decisions.sqlite'),
                   '--port',str(args.port)]
        try:
            return subprocess.call(command)
        except KeyboardInterrupt:
            return 0
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
