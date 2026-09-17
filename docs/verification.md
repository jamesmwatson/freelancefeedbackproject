# Verification of this edition

Checks were run on the exact public subset, using only synthetic fixtures.

| Check | Result |
| --- | --- |
| Preserved Python review tests | All 5 passed: HTTP loading/context/export; independent decisions and restart; bulk validation; protection against attachment ID reuse; corpus alignment |
| Public-example Python tests | Both passed: fixture relationships, source hash unchanged by review, saved decisions after restart, overwrite refusal and quote categories |
| Preserved JavaScript filter checks | Syntax and 12 combined direction/template/search/date checks passed |
| Standalone preview checks | Inline JavaScript parsed; fixture loading, context, filtering and decision adapter passed; no fetch calls in its JavaScript |
| Inventory on fictional MBOX | Completed: 5 parsed messages, 5 attachment occurrences, 4 unique payloads |
| Repeat demo preparation | Existing matching fixture reused, with decision state preserved |
| Source provenance | Included inventory script matches its supplied source byte-for-byte |
| Publication content review | Selected text checked for private names, paths, email addresses, source hashes, internal identifiers and common credential patterns; all included addresses are fictional `example.test` addresses |
| Package inspection | Explicit file selection; no private input material, runtime databases, generated mailboxes, caches or original Git history |

Browser rendering and browser-driven interaction were not verified in the build environment: no browser executable was installed, and downloading one timed out. The self-contained preview is provided for direct inspection; no screenshot or visual-QA claim is included.

The automated checks exercise source and decision separation, relationship handling, filtering and fixture behaviour. They do not prove semantic correctness of arbitrary extracted feedback or that future additions to this repository contain no private data. Publication review applies to this edition's selected files.

## Re-run

From the repository root:

```sh
python -m unittest discover -s src/triage -p "test_*.py"
python -m unittest discover -s tests
node src/triage/test_filters.cjs
node tests/test_preview.cjs
```

The Python tests need only the standard library. Node.js is optional for the two JavaScript checks.
