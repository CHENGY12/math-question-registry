# Scaling and recovery

## Implemented local execution

- A document is the deterministic processing/cache unit. Its key includes original DOCX, source manifest, graph snapshot, taxonomy, the guidance/presentation entries for only its question IDs, and adapter/contract code.
- Identical inputs reuse a content-addressed cache after verifying file digests and question integrity. Editing one guide invalidates its owning document, not the whole bank. Rendering and publication still verify the merged output.
- Workers write isolated staging directories. The coordinator validates and commits cache receipts, merges records, and writes the final JSONL. Do not have multiple agents or runner processes append to the same bank.
- `--workers` is bounded from 1 to 32, default 4. This is local thread concurrency, not browser/model concurrency. Shared media and original documents use content hashes.
- `--max-attempts` is bounded from 1 to 5, default 2 per invocation; deterministic input errors are not retried as transient failures. Repair the input and rerun.
- Same-ID, identical records collapse; conflicting records are excluded and reported. Near-duplicate/variant detection is a separate content review; this package does not claim a semantic deduplication service.
- A kernel process lock protects a single output directory and releases after a process exits or crashes. Windows behavior has code support but needs validation on the destination Windows environment.

## Recovery contract

For acquisition recovery, first reconcile the account ledger, captured receipts, original files, saved generated papers and basket state. Resume from those artifacts instead of generating or downloading again. Preserve uncertain download charges until reconciled. If an old basket is reused, record its starting count and origin; do not label topping it up as a fresh full-batch selection. If a test generates a fresh paper, save the old basket evidence separately and begin a new measurement. A local annotation, rendering, review or backup failure does not justify another website download.

A resumed or regenerated selection must still pass the full-batch pre-download ID gate against `captured_questions`, other unfinished `reserved_batches` and its own repeated IDs. The sole acquisition coordinator bulk-extracts the current list, replaces conflicts through official controls, refills, rechecks all IDs and records the reservation serially. Do not rely on a stale preflight or downstream deduplication; processing agents do not operate the browser or quota. Limit each intelligent-selection batch to 1–2 macro categories and at most the observed 500 child nodes, rotating only across authorized batches. The current 集合与常用逻辑用语 + 函数与导数 test remains one 100-question batch.

Use `status` to inspect the last run and active lock. Rerun the same command to resume. Completed caches are verified, incomplete staging is never accepted as success, and corrupt caches are isolated then rebuilt from read-only input. Errors and conflicting IDs remain visible; a partial output does not count as a successful whole batch.

Publication replaces files atomically one by one and commits a receipt last. It is **not an atomic transaction for the entire directory**. `verify` rejects an interrupted/mismatched publication, a changed report/index, missing media, or a changed per-question file. Rebuilding from intact inputs/cache repairs it. Do not serve an actively publishing output as a production database; a production adapter should promote an immutable completed version through an atomic pointer or database transaction.

Inputs and outputs must not overlap. The runner owns its managed state/staging area and previously recorded generated files; unrelated user files must not be removed. Keep authored inputs and review evidence outside temporary worker directories. Copy the full verified output when transporting it, including managed state if you need `verify` or resume; a viewer-only copy can use the self-contained HTML but has no execution state.

Explicitly configure `mode: batch_end` for this session: finish local tagging and checks for the entire batch, then invoke `backup-batch` for its distinct operator/batch archive; see [google-drive-backup.md](google-drive-backup.md). This implementation passed local tests; `run` leaves it pending without uploading individual questions. A sync failure leaves the verified bank intact, and changing a destination does not require re-downloading or re-parsing originals. The optional `mode: per_question` compatibility mode retains its archives/retry ledger under `.pipeline/backups`; configurations with no mode still use the old automatic behavior. A per-question ZIP is not the entire runner's cache/lock state.

## Stages that remain agent-driven

Browser acquisition, ID matching, formula transcription, source/inference tagging, graph alignment, guidance authoring and mathematical review require agent or teacher work. The runner consumes their completed inputs. It does not call a model or turn its own `PASS` into content approval.

Use two independent work streams. One acquisition coordinator owns the account and uses official intelligent/bulk assembly, falling back to whole-page additions, within broad subject/region/category scope. Before download it checks deterministic ID duplicates, count, settings and identity evidence, not per-item difficulty, exact quotas, pedagogical value or paper-title consistency. It verifies each original DOCX, actual ordinal mapping, available UI metadata and hashes, then publishes the `captured` packet. Detailed parsing, tagging, writing, blind solving and review belong to local consumers of that packet.

After a capture receipt is committed, immediately continue the next authorized acquisition batch when usable quota permits. Do not wait for consumers, completed guidance, review exceptions, publication or backup. Review exceptions block the affected questions' admission, not unrelated raw acquisition. See [agent-handoffs.md](agent-handoffs.md) for ownership and packets. The saved queue is an agent-maintained orchestration contract, not an implemented background service in this runner.

Target 100 questions per website download, with at most the account's remaining shared daily slots (verified membership nominally 20/day) **and** the user's remaining authorized batches. Local processing concurrency does not multiply account quota. A one-batch 100-question test does not become 20 batches just because capacity exists. Group small questions into bounded author/reviewer jobs, assign each ID once, and cache version-bound review results. Scale those consumers from measured resources independently of the single account producer.

For distributed processing, a durable task broker and transactional publication remain extensions. The selected team registry shares acquisition metadata only; it does not turn the local runner into a multi-host processing service.

## Team Git registry and Drive — deployment boundary

The user selected Git metadata + Drive, with requested public repository `CHENGY12/math-question-registry`. `scripts/team_registry.py` passed nine isolated local tests; repository creation, write permissions and real concurrent client operation must be verified separately. Until then, report the local tested scope. Registry transitions require coordinator CLI calls; there is no automatic runner/Drive hook. Follow [team-registry.md](team-registry.md) for commands, state transitions and the public-data boundary.

Use canonical fixed question files and a single shared registry branch. A 100-question claim is one commit/normal push, acquired only after confirmed remote success. On conflict, fetch and redo whole-batch business deduplication; do not merge/rebase old claims or force-push. Local `captured_questions`/`reserved_batches` and current-batch checks still form a mandatory pre-download gate, augmented by the latest shared registry. Push ownership and download-state changes promptly, rather than waiting for the final Drive archive. Public Git contains IDs/states/batch indexes/hashes and an opaque archive key; actual Drive IDs/URLs, source files and machine paths remain private.

Claims and uncertain downloads are different states. Owner heartbeats may support renewal, but `downloading` or uncertain outcomes must not expire into automatic availability; reconcile remote token/operation records, website history and saved files first. The first CLI releases only never-started `reserved` work. Account quotas are separate counters by account alias plus site day/reset basis, while question IDs are team-global. Processing agents neither use the website account nor consume its quota.

Every colleague/batch finishes local work and checks before its `batch_end` Drive archive, using an independent operator/batch/content-version destination with no same-name overwrite. Google Drive holds artifacts; Drive-synchronized JSON does not provide a multi-user lock. Distinguish local staging, actual cloud confirmation and the Git `archived` transition. Per-question auto backup is only an explicit legacy option.

If Git contention or scale later warrants a service, a PostgreSQL unique constraint and transaction-bound claim can preserve the same contract; [INSERT / ON CONFLICT](https://www.postgresql.org/docs/current/sql-insert.html) documents the concurrency primitives. This is an undeployed upgrade option, not a cloud service already connected or a requirement to choose a paid provider.

The current merger and full-bank formula validation load a batch into memory. The preview limit is not a memory limit for the JSON bank. For expansion, keep bounded per-topic/source batches in separate output directories and an external batch index; choose batch sizes from measured memory and content complexity. Whole-bank cross-batch conflict detection and promotion need an aggregate ID/content index. Do not market this local implementation as unbounded streaming or million-question capacity.

## Measurement and acceptance

Keep acquisition throughput and reviewed-product throughput in separate records:

- **Acquisition:** record selection mode (`fresh_generated`, `fresh_bulk_selected` or `reused_basket`), initial basket count and origin, newly selected distinct IDs, selection start, download request/completion and capture-commit times. Count verified original documents and newly captured unique source IDs; report attempted/charged/uncertain slots. Time UI selection, download and identity/hash checks separately, plus their total wall time. Missing receipts and corrupt/ambiguous batches do not count as successful captures.
- **Processing and review:** record queued/parsed/annotated questions, sealed blind solutions, independently reviewed/admitted questions, exceptions, publication and backup states, with the applicable wall times. Capture is not mathematical acceptance. Queue backlog and downstream latency may grow while download throughput remains high; report both instead of presenting captured questions as finished products.
- **Comparison scope:** mark reused baskets, already downloaded files, warm caches and unchanged reviews explicitly. A test that only fills an old basket's remaining slots cannot establish fresh 100-question selection speed. A fresh intelligent-generation test starts its own timer and does not include old selected items as newly selected work. If reporting end-to-end latency, include both streams and waiting time under that explicit label.

The nominal 20 × 100 is an acquisition capacity bound when all slots and that volume are authorized, not a measured rate or a reviewed-question target. A speed claim needs a successful capture receipt and measured timings; an untested intelligent-assembly page alone does not establish throughput. No timing test silently expands the current one-batch authorization.

Save `run-report.json` before the next run overwrites it. Compare processed jobs, cache hits, repaired caches, distinct questions, failure count and stage timings. `job_processing_seconds_sum` is summed worker time, not wall time. The report separately shows processing wall time, validation/merge and rendering. `status` includes final total and publication time.

Cold/warm runs are affected by imports, filesystem state and background activity. Describe a cache hit as “skipped parsing N unchanged documents”; do not extrapolate a small replay to new-question throughput, model cost or website capacity.

Useful regression commands:

```sh
python3 -m unittest discover -s "$SKILL_ROOT/tests" -v
python3 "$SKILL_ROOT/scripts/pipeline.py" run --input "$INPUT_ROOT" --output "$OUTPUT_ROOT" --workers 1
python3 "$SKILL_ROOT/scripts/pipeline.py" run --input "$INPUT_ROOT" --output "$OTHER_OUTPUT_ROOT" --workers 4
```

The bundled unit suite uses a controlled fake adapter for concurrency/recovery faults. It validates the runner contract, not actual Word rendering or mathematics. Also run representative real documents, relocate the package/workspace, and perform browser checks. Repeated copies of a few source files are a load replay, not newly acquired unique questions or curriculum coverage.
