# Lessons learned

## Ground truth became the limiting factor

The project initially concentrated on extracting feedback automatically. Later diagnostic work made it clear that interpreting output required a reliable record of what actually counted as feedback. Human review changed the role of automation from authority to discovery and diagnosis.

For a similar future project, establish a small, deliberately varied human-reviewed reference set early, including negatives and ambiguous examples. Evaluate specific failure modes against it before expanding long-running extraction work.

## Review ergonomics mattered

Filters, bulk decisions, conversation context and independent flags made review practical. The most useful interface work reduced the cost of making a well-grounded decision repeatedly. It also made progress resumable.

For a future implementation, define the review unit and the decisions it must support before designing the database or queue. Keep “candidate”, “confirmed”, “uncertain” and “showcase” semantically distinct.

## More context also creates more attribution work

Conversation context can explain feedback, but quoted replies and outgoing text can cause an extractor to attribute a statement to the wrong source. Document templates can multiply apparent findings without adding independent evidence.

Keep message direction and source locators available throughout the workflow. Verify attribution as well as whether a quote is present.

## Diagnostic categories were more useful than a single success flag

A quotation altered only by typography presents a different problem from one that cannot be found. The included quote checker demonstrates this distinction. Matching alone does not establish the meaning or relevance of the quotation.

Measure and report the failure being tested. Avoid describing an extraction pipeline as “accurate” without naming the population, reference decisions and metric.

## A final export is not necessarily a preservation snapshot

The initial completed-review export did not contain every field needed to reconstruct the system. The fuller freeze preserved context and relationships as well as decisions. Databases, portable tables and manifests served different purposes.

Design a future snapshot around the question “Could I explain this decision after losing the running app?”

## Synthesis needed two destinations

An application register needs concise, retrievable claims with limits and provenance. A retrospective needs space for chronology, mixed evidence and interpretation. Separate outputs allowed each to serve its purpose.

The finish condition was a completed reviewed evidence base and usable synthesis outputs. That made it possible to park the project and use its results without continuously reopening extraction.
