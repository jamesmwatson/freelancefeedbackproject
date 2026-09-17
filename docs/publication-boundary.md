# Publication boundary

This directory was assembled as a new, explicit selection. It contains public project descriptions, inspected generic code, fictional fixtures and an interactive preview using those fixtures.

## Included

- General project purpose, workflow and methodological decisions.
- Selected code with its provenance and limitations.
- Fictional correspondence, document summaries, decisions and source identifiers.
- A self-contained preview of the early review interface using those fictional fixtures.

## Excluded

Original correspondence and attachments; real quotations or anonymised paraphrases; personal names or contact details; client and project identities; real source filenames, message identifiers and hashes; private career findings and archive counts; review state; logs and caches; personal filesystem paths; the original Git history.

The original evidence snapshot and private project remain separate. This edition is a project record, not a backup or a substitute for the private archive.

## Generated output is a separate concern

The repository contains no private source material, but its tools are not anonymisers. The inventory tool reports its input filename, dates and aggregates, and can optionally include custom label names. The viewer displays whatever source records it is given and exports their decision identifiers. Outputs from real private inputs therefore remain private.

The demo writes its runtime files into ignored `.demo/`. The `.gitignore` is an extra guard against accidental additions, not a guarantee that arbitrary new files are safe to publish.

## Publishing this edition

Extract the supplied archive into a fresh folder. Review the file list and documentation, then create a new Git repository there. Do not bring across the original `.git` directory or copy private evidence into this folder. Review the configured Git author identity before the first commit if you want to avoid exposing a personal email address in commit metadata.

No remote, commit history or publishing credentials are included. No reuse licence has been selected in this edition.
