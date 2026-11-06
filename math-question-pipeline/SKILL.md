---
name: math-question-pipeline
description: Collect and curate authorized high-school mathematics questions into a traceable bank with original images, source and inferred tags, knowledge-graph alignment, reusable solution guidance, independent review, and professional offline typesetting. Use for 学科网/组卷网题库整理、按知识点覆盖扩展、可恢复并行处理或已有 Word 样题的标准化。
metadata:
  short-description: 可移植、可恢复的数学题库整理与解题指导流程
---

# Math Question Pipeline

Build a reviewable question bank from authorized source material. Preserve original evidence; make added teaching content and edits traceable. This skill includes a deterministic local runner and an agent workflow for acquisition, annotation, and review. The runner does **not** log in to websites, invent missing annotations, call a model, or approve mathematical correctness.

## Start from the current state

1. Resolve `SKILL_ROOT` to this folder, `INPUT_ROOT` to the source workspace, and `OUTPUT_ROOT` to a separate output directory. Never depend on the author's home directory, an earlier chat, or files outside this package for code.
2. Reuse the user's latest scope and approvals. Record subject/stage, region selection mode, coverage graph/version, allowed sources, authorized batch count, existing download access, and what constitutes a reviewed question. Account capacity is not authorization: a current one-batch, 100-question test remains one batch even when the account can support 20 × 100. Respect an outstanding user review gate; a later explicit instruction can replace an earlier selection strategy or gate.
3. Use the smallest appropriate path:
   - **Curriculum coverage or expansion:** use macro-topic coverage targets from [coverage-planning.md](references/coverage-planning.md). Topic/type/difficulty proportions are soft planning targets, not a reason for repeated item-by-item UI selection.
   - **Sources not yet downloaded:** follow [source-xkw.md](references/source-xkw.md). One account coordinator uses scope-compatible official batch controls or page-based addition to fill combined downloads up to the observed cap (100 questions, 20 downloads/day for the verified membership). For a required region, a region preference is insufficient: prefer the actual question-region filter. Capture original files and identity receipts into the queue; continue the next authorized batch without waiting for annotation or review.
   - **Acquisition only / colleague download package:** stop at verified originals, complete ID mapping, raw metadata and a confirmed `captured` registry update. Deliver these capture artifacts and timing. Do not require teaching guidance, full formula transcription, mathematical review or Drive publication before completing this requested phase.
   - **Word files but no annotations:** inspect, match source IDs, and build the inputs in [data-contract.md](references/data-contract.md).
   - **Prepared workspace:** run directly; do not redo acquisition or generation merely to exercise every stage.
   - **Failed/interrupted run:** read status, correct the cause, then rerun the same output directory. Do not erase completed work.
   - **Colleagues sharing acquisition across computers:** use the Git claim protocol in [team-registry.md](references/team-registry.md). Normal push success grants the whole-batch claim; publish claim/download transitions promptly through the coordinator's CLI calls. Public Git stores only permitted metadata. Local concurrent-client tests and a live GitHub duplicate-claim rejection passed on 2026-11-06; each colleague still needs verified write access. Coordination assumes collaborators use the provided tool without force-pushing or manually changing claims; server-side branch protection is not enabled.
   - **Google Drive backup requested:** explicitly configure **`mode: batch_end` as this session's default** under [google-drive-backup.md](references/google-drive-backup.md): finish the complete batch locally, check it, then invoke `backup-batch` for a distinct operator/batch archive. `run` does not upload in this mode. `mode: per_question` is explicit compatibility only; configurations lacking a mode retain the old automatic behavior.

## Keep acquisition and completion independent

Use a dedicated acquisition coordinator for the shared account. Before every download, bulk-extract the complete current ID list and check within-batch duplicates plus overlaps with `captured_questions` and other unfinished `reserved_batches`. Replace conflicts through official controls, refill and recheck the entire batch; only that coordinator performs preflight and reservation serially. Download-afterward deduplication cannot replace this mandatory gate; see [source-xkw.md](references/source-xkw.md). Processing agents do not operate the browser or consume quota. Check scope controls, count and export settings as well. Defer difficulty/type evaluation, teaching-value selection, semantic deduplication and detailed source-paper research to downstream workers. Different paper titles or raw source regions do not justify browsing and reselecting every question. Record the actual region control: a Jiangsu preference is not proof that every question originated in Jiangsu.

The observed intelligent-assembly selector permits at most 500 child knowledge nodes. Select 1–2 macro categories per fresh batch when that route meets the user's scope, and rotate across authorized batches. The actual 2026-11-06 combined download reused 74 existing questions and added 26 through the Jiangsu question filter; its timing is not a fresh 100-question selection benchmark.

In enabled team mode, complete the pre-download gate against the latest Git registry and obtain a confirmed normal-push claim for the entire batch. A push conflict requires fetching and repeating business-level ID checks, not merging an old claim or force-pushing. Push `downloading` before the download and `captured` immediately after its receipt succeeds; do not defer those updates until Drive archiving. The same account has one coordinator and shared quota; different colleagues' accounts have separate quotas but one team ID registry.

A batch becomes `captured` when its original DOCX, complete source-ID/actual-Word-ordinal mapping, available UI metadata, integrity checks and hashes are saved in a reviewable receipt. This is a raw acquisition milestone. Parsing, tagging, guidance, blind solving, content review, publication and backup consume independent work packets as described in [agent-handoffs.md](references/agent-handoffs.md). None is a gate for the next authorized download. This queue is coordinator-maintained; the bundled local runner does not implement an acquisition scheduler.

Measure download throughput and reviewed-question throughput separately. A test must state whether it generated a fresh selection or reused an old basket, how many items were already selected, and which stages were timed. See [scaling-and-recovery.md](references/scaling-and-recovery.md).

## Environment and execution

Python 3.9+ and Node.js on `PATH` are needed. Dependencies are in `requirements.txt`; KaTeX and fonts are bundled. Use an existing suitable environment, or a project virtual environment if needed. Do not overwrite system packages.

```sh
python3 "$SKILL_ROOT/scripts/pipeline.py" doctor
python3 "$SKILL_ROOT/scripts/pipeline.py" inspect --docx "$SOURCE_DOCX" --output "$INSPECTION_DIR"
python3 "$SKILL_ROOT/scripts/pipeline.py" run --input "$INPUT_ROOT" --output "$OUTPUT_ROOT" --workers 4 --preview-limit 100
python3 "$SKILL_ROOT/scripts/pipeline.py" verify --output "$OUTPUT_ROOT"
python3 "$SKILL_ROOT/scripts/pipeline.py" status --output "$OUTPUT_ROOT"
```

`inspect` produces raw blocks and media, **not verified site IDs**. Source-ID/ordinal matching is a required agent step. The default preview is bounded so a large bank does not become one enormous HTML page; JSON output retains the full successful set. Read [scaling-and-recovery.md](references/scaling-and-recovery.md) for caches, failure isolation, concurrency, and measured boundaries.

## Per-question completion contract

Follow [data-contract.md](references/data-contract.md) and [editorial-and-guidance.md](references/editorial-and-guidance.md). These are downstream completion requirements, not pre-download selection checks.

- Capture question, options, parts, answer, full explanation, source metadata, and original formula/diagram assets. A missing formula is a failed extraction, not an empty string.
- Preserve source tags; normalized or inferred tags require their own evidence and review status. Keep correct rate, score rate, and school paper-use statistics null unless their real school data has been connected under the user's scope. Source difficulty is not a correct rate.
- Align source knowledge to stable graph IDs with primary/secondary/supporting roles. Unsupported details enter a gap queue. Partial/supporting/unreviewed matches do not prove main-topic coverage.
- Keep the single user-facing **解题思路与技巧** tag dimension with internal method/technique/competency categories. Separately author concise **解题思路与套路** in `solution_guide`: one sentence for the entry point and method choice, usually 2–3 key steps, and 1–2 relevant pitfalls. Cover every subquestion and preserve essential conditions. Keep the structured evidence fields brief; do not repeat the full answer explanation or display every field as a separate section. See the editorial reference for the concise writing and display contract.
- Keep raw source content and `presentation` edits separate. Math notation, punctuation, equation layout, diagram linkage, and printing behavior must pass actual display checks.
- Never report script validation, agreement between agents, and teacher signoff as the same thing. Keep the three statuses distinct.

## Delegate when useful

When the user authorizes agents/subagents, separate the acquisition role from parsing, tagging, guidance and review roles using [agent-handoffs.md](references/agent-handoffs.md). Only the acquisition coordinator operates the shared account; local consumers own independent work packets and files. Do not have agents append to a shared JSONL or wait for all content workers before continuing an authorized acquisition batch.

For mathematical review, obtain a sealed answer from question-only material before exposing the source answer and authored guidance. Then compare and review the reasoning, applicability conditions, editorial changes, and learning value. This provides context isolation; do not claim OS-enforced file isolation unless actually configured and verified. Keep the author and independent reviewer in different invocations. If subagents are unavailable, complete feasible work and mark independent review pending.

Resolve disagreements from evidence. Conflicting answers, questionable wording, missing diagrams, or unverified formula transcriptions remain in review; never change the expected answer or difficulty just to make a batch pass. Source errors become documented correction proposals.

## Acceptance and authorized expansion

For processing acceptance, use a representative trial spanning requested question types, image-dependent questions, multi-part proofs, difficult formulas, and likely parsing variants, preferably reusing captured originals. These completion checks do not serialize later authorized downloads behind content review. For an acquisition-speed test, use the fast bulk path and report its capture receipt and timing separately. Do not infer full coverage from a few repeated files.

1. Verify the downloaded DOCX and source identity, then run all deterministic checks.
2. Review guidance and mathematics against original text/images; preserve review records tied to input hashes.
3. Open the generated preview in a browser. Check images, formulas, Chinese punctuation, long expressions, disclosure panels, zoom, and a narrow viewport. Static HTML validity alone is insufficient.
4. Exercise resume, one-document change, corrupt-cache recovery, a failed document and repair, duplicate/conflicting IDs, and a relocated skill/workspace. Use isolated test directories; label synthetic faults and repeated-source workloads honestly.
5. Report newly captured unique IDs, processed and reviewed/admitted questions separately, with successful/failed jobs, knowledge gaps, timing scope, output paths, and remaining limits. Only claim improvements the run records show.

For large runs, keep acquisition constrained by the source's available interface and each account's allowance. Increase local workers or independent consumer batches based on observed resources and errors. Git registry coordination, when configured and tested, shares acquisition metadata; this package's processing runner remains local. A distributed processing service/database is a later extension.

In `batch_end`, a local run records pending completion without writing Drive. Once the whole batch's local tagging and checks finish, invoke the batch archive step; every colleague/batch uses an independent versioned destination. Preserve local retryable archives if Drive is unavailable. Follow the backup reference for implementation status and cloud verification; a local copy is only `staged_for_sync`. Git state updates happen throughout, while the final archive confirmation happens at the end.

## Deliverables

Deliver the bank JSONL and per-question JSON, schema, original media and source provenance, bounded offline preview, validation and task reports, knowledge gaps, and mathematical/editorial review records. The runner emits deterministic artifacts; the coordinating agent attaches acquisition and independent review records, which may come from separate stages. Provide a short user-facing result with links and the actual review state.

The included adapter has been exercised on 学科网高中数学 downloadable Word files with VML equations, DrawingML figures, and an end-of-paper answer section. Other export layouts, sources, and subjects require adapter calibration; unknown structure should fail explicitly rather than silently truncate a question.
