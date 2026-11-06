# 按知识点覆盖组织批次

Use this reference when planning curriculum coverage or coordinating more than one batch. This is an agent-maintained planning contract; the bundled local runner does not implement a global scheduler or cross-batch database.

## Macro coverage guides bulk acquisition

Plan broad categories such as functions/derivatives, trigonometry, vectors, sequences, geometry and probability/statistics. Use the official intelligent/bulk assembly controls, or whole-page bulk addition, to acquire full batches efficiently. Topic, question-type, difficulty, figure and multi-part proportions are soft coverage targets. If the official form requires type counts, enter a coarse mix once; do not browse and replace individual questions or repeatedly regenerate to force exact ratios.

The observed intelligent-assembly limit is 500 selected child knowledge nodes. Use 1–2 macro categories per batch within that cap and rotate across authorized batches, rather than selecting the whole graph at once. This single 100-question test uses 集合与常用逻辑用语 + 函数与导数; remaining categories are future coverage targets, not authorization to download more now.

Before download, check subject/stage, the actual region selection mode, deterministic captured/reserved ID duplicates, counts, export settings and identity evidence. Do not require per-question difficulty assessment, teaching-value evaluation, exact graph alignment, source-paper research or semantic-variant review. Preserve available labels for downstream work. Different source-paper titles are normal in combined batches. A Jiangsu selection filter or preference describes acquisition scope; it never authorizes overwriting a different original region. Record whether the UI provides a filter or only a preference and reconcile visible region evidence in bulk.

Detailed reviewed deficits guide later broad-category allocations. They do not block an already authorized next download while current questions wait for parsing or review. Keep the authorized batch limit separate from the account's nominal 20 × 100 capacity; a one-batch 100-question test is still one batch.

## Define what counts as covered

Use the supplied graph's stable IDs, descriptions and version. Inspect semantic scope before mapping a source label. A supporting technique, partial match, broad parent node, or candidate waiting for review does not establish primary-topic coverage. Missing curriculum topics enter the graph-gap queue; do not assign a nearby ID solely to make the coverage chart green.

For “all high-school mathematics,” also establish a versioned curriculum scope list from the user's accepted curriculum/textbook scope. That list is the coverage denominator; an incomplete existing graph cannot define completeness by itself. Reconcile scope topics against graph nodes and keep missing nodes visible before reporting an overall coverage percentage. If the scope list is not yet agreed, report coverage only against the named graph snapshot and mark full-curriculum coverage undetermined.

Make the target distribution explicit: topic, question type, difficulty, number of distinct reviewed questions, region-selection mode and any year/grade constraint. Unless the user requires exact quotas, use a reasonable provisional distribution within the authorized total and record deviations after capture; do not create a new pre-download approval or selection gate. Do not equate “one question exists” with full mastery or complete curriculum coverage. Do not invent hard numeric difficulty thresholds when the source provides only its own labels/coefficient.

Keep these counts separate for each node:

1. Target count, optionally broken down by type/difficulty.
2. Acquired unique questions.
3. Successfully parsed questions.
4. Questions with accepted primary-topic alignment and independent content review.
5. Questions admitted under the user's agreed review process, including actual teacher signoff when required.

The remaining deficit is measured against the agreed admission criterion. Keep unavailable topics and unresolved graph gaps visible even when they cannot yet receive a valid node ID.

## A bounded task ledger

Maintain a coordinator-owned JSON ledger or equivalent database. A practical task record has:

```text
task_id, graph_version, target_node_ids, primary_topic_description
source, filters, region_selection_mode, soft_coverage_targets
authorized_batch_limit, batch_question_limit, selection_mode
account_alias, account_quota_ledger, download_batch_id, reserved_download_attempt
capture_state, processing_state, assigned_role, owned_output_path, source_question_ids
source_cursor_or_evidence_urls, input_digests, capture_receipt, completed_artifact_receipt
attempts, last_error, blocked_reason, next_action
```

Capture states include `planned`, `acquiring`, `captured` and `needs_attention`; processing states include `queued`, `parsing`, `annotating`, `reviewing`, `verified`, `admitted` and `needs_attention`. Maintain these independently, so a review issue does not undo a valid capture receipt or block the producer. These are coordinator workflow states, distinct from the local runner's job/cache status. Only record `admitted` after the agreed content criteria pass; a local runner `PASS` alone means `verified` structurally.

The coordinator reserves each source ID before authoring. Independent workers receive different question IDs or separate annotation files. Group a few short questions together when context allows; isolate long proofs or diagram-heavy questions. In one batch, finish the source-ID-to-Word-ordinal mapping before dispatching authors. Seal a blind review before providing answers, as described in [agent-handoffs.md](agent-handoffs.md).

## Independent acquisition and processing loops

The dedicated account coordinator repeats the acquisition loop only within the user's current authorization:

1. Choose 1–2 broad categories from the soft coverage plan within the 500-child-node limit. Reuse any existing capture/basket evidence before selecting more questions.
2. Generate or bulk-add a full batch through the official UI. Bulk-extract every current ID and check batch-internal duplicates plus overlaps with `captured_questions` and other unfinished `reserved_batches`. Replace conflicts through official 换题 or bulk regeneration, refill to 100 and recheck the entire batch. This mandatory pre-download gate cannot be deferred to content deduplication. Do not use downstream author/reviewer job sizes to split website downloads.
3. The account's acquisition coordinator serially records successful preflight and this batch's ID/attempt reservation. In team mode, obtain the whole-batch claim through confirmed normal Git push before downloading; a conflict requires fetching and redoing availability checks, not merging an old claim. Push the downloading transition, export once, then verify the original DOCX, count, actual ordinal-to-ID mapping, UI metadata and hashes. Changed IDs require full revalidation. Commit the immutable `captured` packet described in [source-xkw.md](source-xkw.md). Processing agents do not use the browser or quota.
4. Enqueue that packet, promptly push captured state/source hashes, and start the next authorized acquisition batch when quota permits. Do not wait for content parsing, metadata enrichment, tags, guidance, blind solving, review, publication or backup. Default Drive archiving is `batch_end` after local work/checks, not a reason to delay Git state updates.

Independent local consumers take captured packets, parse complete documents, enrich source metadata, author and independently review question packets, resolve exceptions, and run the deterministic pipeline in separate output directories. They update reviewed primary alignments, admission counts and remaining gaps when evidence becomes available. Their queue and results are separate from acquisition progress. The coordinator may use that feedback for later broad-category batches without holding up an already authorized capture.

Respect the latest user instruction: do not expand a one-batch test merely to use all 20 nominal slots, or invent a requirement to finish processing before another batch that the user has already authorized. An outstanding user review gate still applies unless later instructions replace it. Parsing consumes the complete Word and complete manifest once; do not pass a subset manifest for a full Word file. Size local work from measured document/image complexity and memory use, retaining the original; `--workers` does not promise unlimited scale.

Across batches, use a coordinator-maintained ID/content index. At acquisition, deterministic captured/reserved ID checks prevent repeat downloads. After capture, identical content can reuse one question; conflicting versions stay separate for adjudication and do not count twice as reviewed coverage. Different IDs with similar wording require downstream semantic/variant review; identical final answers are not enough to merge them. Do not turn semantic deduplication into item-by-item pre-download browsing. The runner only performs exact deduplication/conflict checks within its current invocation.

Report selection/download/capture throughput separately from parsed, reviewed and admitted-question throughput. Mark tests that reuse old baskets or original files, and retain the initial basket count; see [scaling-and-recovery.md](scaling-and-recovery.md).

For multiple colleagues, use the selected Git metadata protocol in [team-registry.md](team-registry.md), with separate website-account quotas and a shared question-ID namespace. The CLI passed isolated local tests; live remote access and concurrent operation require separate verification. Git transitions are coordinator CLI calls, not automatic runner/Drive hooks. Each colleague/batch uses its own Drive archive under [google-drive-backup.md](google-drive-backup.md). A durable distributed processing broker/database remains a future extension; Drive-synchronized JSON is not a claim lock.
