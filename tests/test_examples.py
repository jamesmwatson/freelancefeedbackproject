"""Focused checks of fixture invariants and the preserved quote diagnostic."""
import hashlib
import json
import mailbox
import sys
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'),str(ROOT/'src/triage'),str(ROOT/'examples')]
from evidence_matching import evidence_match_category
from run_demo import build_fixture, FIXTURE
from triage import Inventory

class ExampleChecks(unittest.TestCase):
    def test_fictional_data_and_readonly_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp)/'demo'
            source, corpus = build_fixture(destination)
            original = hashlib.sha256(source.read_bytes()).hexdigest()
            inventory = Inventory(source,destination/'decisions.sqlite',corpus)
            rows = inventory.data()['rows']
            self.assertEqual(len(rows),4)
            self.assertEqual(sum(len(r['occurrences']) for r in rows),5)
            self.assertEqual(len(rows[0]['occurrences']),2)
            self.assertEqual(rows[2]['occurrences'][0]['direction'],'outgoing')
            self.assertTrue(inventory.data()['sender_available'])
            inventory.update({'ids':['1'],'triage_status':'possible_feedback'})
            inventory.update({'ids':['2'],'template':True})
            restarted = Inventory(source,destination/'decisions.sqlite',corpus)
            self.assertEqual(restarted.data()['rows'][0]['triage_status'],'possible_feedback')
            self.assertEqual(restarted.data()['rows'][1]['triage_status'],'unreviewed')
            self.assertTrue(restarted.data()['rows'][1]['template'])
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),original)
            box = mailbox.mbox(destination/'fictional.mbox',create=False)
            try:
                self.assertEqual(len(box),5)
            finally:
                box.close()
            with self.assertRaises(FileExistsError):
                build_fixture(destination)

    def test_quote_diagnostics(self):
        f = json.loads(FIXTURE.read_text())
        source, quote = f['attachments'][0]['text'], f['example_verification']['quote']
        self.assertEqual(evidence_match_category(source,quote,quote),'verified_exact')
        self.assertEqual(evidence_match_category('The instruction is clear.','','The  instruction is clear.'),'whitespace_only')
        self.assertEqual(evidence_match_category('The “revised” instruction.','','The "revised" instruction.'),'typography_or_whitespace')
        self.assertEqual(evidence_match_category(source,'','The change reduced errors by half.'),'not_locatable_by_safe_normalization')
        self.assertEqual(evidence_match_category(source,'','\u2003'),'missing_model_quote')

if __name__ == '__main__':
    unittest.main()
