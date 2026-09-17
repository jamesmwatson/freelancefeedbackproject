# Feedback: from correspondence to career evidence

A completed project exploring how to recover useful professional feedback from a mixed email and document archive, review it systematically, and turn it into traceable career evidence.

The key decision was to make **human review authoritative**. Automated extraction helped discover candidates and diagnose problems; it could not establish what counted as feedback or what a source actually justified.

This repository is a compact project record with selected working code and an entirely fictional demonstration. The original correspondence, review decisions, evidence register and personal retrospective remain private. No real archive counts or career findings are reproduced here.

**Quick visual tour:** download or clone the repository and open [examples/preview.html](examples/preview.html) in a browser. It is self-contained and uses fictional data; decisions in this preview last only until reload.

## The problem

Feedback was scattered across email bodies, repeated correspondence, document comments and formal review attachments. A useful result needed more than keyword matches: it needed the correct source, speaker, context and review decision. Repeated templates, outgoing messages and administrative acknowledgements could all look relevant without supporting a professional claim.

## What was built

- Read-only mailbox inventory and a resumable corpus/discovery pipeline.
- Local model-assisted candidate discovery and extraction diagnostics.
- Attachment and conversation review interfaces, including filters, bulk decisions and independent showcase markers.
- A frozen evidence snapshot preserving source relationships and human decisions.
- Two distinct synthesis outputs: an application-facing evidence register and a career retrospective.

The completed project covered all eligible incoming conversations in its review population. This establishes completion of that review population, not perfect recovery of every possible piece of feedback in the original archive.

## Explore the record

| File | Purpose |
| --- | --- |
| [Methodology](docs/methodology.md) | Workflow, authority rules and boundaries of the evidence |
| [Lessons learned](docs/lessons-learned.md) | Decisions that changed the project and what to do differently |
| [Output design](docs/output-design.md) | Evidence cards and retrospective structure, with a fictional worked example |
| [Code provenance](docs/code-provenance.md) | What is preserved, excerpted or newly written for this edition |
| [Publication boundary](docs/publication-boundary.md) | What this repository contains and excludes |
| [Fictional fixture](examples/fictional-feedback.json) | Inspectable source data for the demonstration |

## Run the fictional demonstration

Requires Python 3.9 or newer; no third-party Python packages or model service. Run from this repository's root. On Windows, use `py` in place of `python` if that is your Python launcher.

```sh
python examples/run_demo.py --serve
```

Open <http://127.0.0.1:8765>. Click a filename to see email context and expand **Existing document evidence**. Try filtering by sender, marking a candidate, toggling **Template**, and undoing a change. Stop the server with Ctrl+C; run the same command again to resume saved decisions.

The demo creates its own ignored `.demo/` directory. Sources are read-only in the viewer; decisions are stored separately. To start again, stop the app, remove `.demo/`, and rerun the command.

To create the fixtures without starting the viewer, run `python examples/run_demo.py`. Then run the preserved inventory tool:

```sh
python src/gmail_mbox_inventory.py .demo/fictional.mbox --output-dir .demo/reports
```

The fixture has five messages, five attachment occurrences and four distinct attachment payloads. The viewer hides one outgoing-only attachment by default. These numbers describe fictional data only.

## What the demonstration establishes

The preserved early viewer supports attachment triage, template flags, bulk decisions and separate decision persistence. Its `possible_feedback` state means **candidate for verification**, not confirmed feedback. The final project later added more extensive attachment verification and conversation review; those later interfaces are described here but are not reconstructed in this edition.

The invented evidence card in [Output design](docs/output-design.md) illustrates later synthesis. It is authored example material, not an automatically generated conclusion from the viewer.

## Verification

```sh
python -m unittest discover -s src/triage -p "test_*.py"
python -m unittest discover -s tests
```

With Node.js available, also run `node src/triage/test_filters.cjs` and `node tests/test_preview.cjs`. See [Verification](docs/verification.md) for the checks performed on this edition.

## Scope and authorship

This was an AI-assisted project. AI tools helped develop code and synthesis material; human decisions defined the review categories, adjudicated evidence, set the authority rules and determined when extraction work should stop. This repository records that workflow without implying that every line of code was written unaided.

The included tools are selected historical components, not a full reproduction of the private pipeline or a general-purpose supported product. The demo reads no external mailbox and makes no model/API requests. Real outputs produced by running these tools on private data would themselves need to remain private.
