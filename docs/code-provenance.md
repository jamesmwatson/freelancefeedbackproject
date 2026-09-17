# Code provenance

This edition selects inspectable components from an AI-assisted project. It does not reproduce the entire private working repository. Public documentation is newly written from the final project README and inspection of the selected source files.

| Public path | Origin | Changes in this edition |
| --- | --- | --- |
| `src/gmail_mbox_inventory.py` | Original inventory tool, version 1.0.0 | Retained unchanged |
| `src/triage/triage.py` | Preserved early attachment-triage package | Clarified its module description: source read-only, separate decision writes |
| `src/triage/index.html` | Same early package | Added a demonstration title and fictional-data notice |
| `src/triage/test_triage.py` | Same early package | Retained synthetic workflow tests unchanged |
| `src/triage/test_filters.cjs` | Same early package | Retained synthetic filter tests unchanged |
| `src/evidence_matching.py` | Four functions from `gmail_feedback_diagnostic_sample.py` | Isolated standard-library imports; a whitespace-normalised empty quote is treated as missing |
| `examples/run_demo.py` and JSON fixture | Newly written for the public edition | Creates fictional input data compatible with the early viewer and a corresponding MBOX |
| `examples/preview.html` | Derived from the preserved early interface | Embedded fictional data and an in-memory API adapter; no server or persistent decisions |
| `tests/test_preview.cjs` | Newly written for this edition | Exercises the standalone preview data adapter and checks its JavaScript syntax |
| `tests/test_examples.py` | Newly written for this edition | Checks the fixture invariants and the extracted quote logic |

The early attachment viewer predates the final conversation-review workflow. It has no final thread classifications, evidence cards or showcase controls. The new demo adapter is not the original importer: it constructs small fixture databases directly from invented JSON.

The inventory script is a historical inspection tool. It assumes conventional MBOX envelope boundaries and uses approximate RFC-header conversation grouping. It does not provide comprehensive support for every damaged mailbox or MBOX variant. The quote checker is a string-normalisation diagnostic, not semantic validation.

The public subset intentionally omits superseded repair pipelines, live databases, prompt/run logs, corpus-specific sender rules and final private synthesis documents. The methodology records their role where needed to explain the project.
