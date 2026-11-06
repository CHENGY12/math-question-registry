# 学科网／组卷网采集

Use this reference only when acquiring or checking the source. It describes observed UI behavior, not a private API contract. Recheck the current page before acting; labels and account allowances can change.

## Fast acquisition through the authorized interface

- Prefer an available service connector when sufficient; otherwise use the current environment's browser tool and the user's logged-in session. Do not export cookies, tokens, browser profiles, or hidden application state into the bank.
- Use one dedicated acquisition coordinator for an account. Other agents consume saved files; they do not open concurrent selection/download sessions or receive separate quotas.
- Confirm subject/stage and the actual region control. The top-level region, question filter and intelligent-assembly **优先地区** can be different controls. Record both the selected value and its mode: filter, preference or unknown. A Jiangsu preference is not a strict Jiangsu-origin filter. After generation, capture and reconcile visible region evidence in bulk; preserve absent or conflicting source regions for later processing instead of changing them to Jiangsu.
- Select broad knowledge categories. For a required region, use the actual question-region filter and page-based batch selection. The 2026-11-06 intelligent route's **优先地区=江苏** produced only 51/100 questions with observed Jiangsu paper evidence, so it was rejected before download. Official **智能组卷 / 批量组卷** remains useful when its scope matches the request; an observed entry is `/gzsx/zhineng/t1/`. Use whole-page controls when present, otherwise add the page's new IDs deterministically without inspecting each question's teaching value.
- Intelligent assembly has an observed maximum of **500 selected child knowledge nodes**, separate from the 100-question export limit. Choose 1–2 macro categories per fresh batch and rotate across authorized batches. The actual downloaded trial reused 74 earlier basket questions and added 26 through the Jiangsu question filter; it was not a fresh 100-question generation or whole-course coverage proof.
- Observe completion after each addition. The site can show an optimistic added state while a request is pending. At 90 and above it may repeatedly show a near-full modal; dismiss that observed modal before the next action. A click alone is not proof of successful insertion.
- For final verification, open **试题篮** itself; the generic sidebar **展开** control is not the basket. A previously opened basket panel may retain its old list. If it contradicts the badge, refresh once, reopen the basket, and wait for **试题加载中…** to disappear. Compare the actual item IDs with metadata, not just the badge.
- Before download, restrict question-level checks to deterministic ID deduplication and identity/count integrity. Do not open each question to evaluate difficulty, type balance, teaching value, fine-grained knowledge fit or similarity to other wording. Coverage proportions are soft targets. Do not browse individual papers merely because their titles differ, or repeatedly regenerate/filter to force exact proportions.
- Capture available list/generated-paper metadata in bulk: selected filters, observed IDs and URLs, source labels, displayed type/difficulty, source paper or region/year/grade/term when present. Recording visible values is not a requirement to assess them before downloading. Unknown metadata remains unknown; downstream workers can read question-front provenance and other evidence from the export.
- Do not infer the question's textbook from a recommended textbook sidebar. Do not replace the exam year with the web update date. Account-wide quotation/download counts are not school-specific “已组卷”.
- Use official downloads within the user's available access and scope. If a new payment, login intervention, verification challenge, or exhausted allowance prevents a download, record that item as blocked and continue independent local work. Do not bypass the source restriction or reinterpret an HTML challenge page as question data.

## Mandatory full-batch ID preflight before download

The single acquisition coordinator for each account performs this gate and reservation serially; processing agents do not touch the browser or account quota. In team mode, fetch the shared Git registry first and combine its claims/captured IDs with local evidence under [team-registry.md](team-registry.md). A local list or Drive-synchronized JSON is not a cross-computer lock.

1. Bulk-extract **all IDs in the current generated paper/basket**, not a sample or an old saved selection. Confirm the current expected count (100 in this test) and that no ID is missing.
2. Compare the full list for duplicates within the batch, against `captured_questions`, and against every other unfinished entry in `reserved_batches`. Exclude only the current batch's own reservation when rechecking it. All three conflict sets must be empty.
3. For any conflict, use official **换题** or bulk regeneration to replace/refill within scope. Then extract and verify the **entire resulting batch again**, including the replacement IDs; checking just the changed items is insufficient.
4. Save the checked ID list and preflight evidence, and register/update this batch's ID reservation and shared download attempt before the final download action. In team mode, submit all 100 question records with their common batch ID in one normal Git push; only a confirmed claim result with `download_permitted: true` grants permission. On conflict, fetch and repeat the business-level checks, never auto-merge an old claim or force-push. Push the owned `downloading` transition before consuming the account attempt. Only the account coordinator writes this sequence. If the selected IDs change afterward, invalidate the previous preflight, rerun the full check and update the reservation before downloading.

Do not download with unresolved duplicates or an incomplete ID list. Deduplicating question content or IDs after download cannot satisfy this gate or recover a spent download slot. Post-download Word-ordinal verification remains a separate required check.

## Download settings and visible verification

For the currently supported Word adapter, use DOCX, end-of-paper answers（卷尾）, full explanation, knowledge points, difficulty coefficient, question-front source, and high-resolution equation images. Disable optional QR codes when they add unrelated media. Saving into the website's personal bank is not required for local acquisition.

Observe the selected controls before downloading. In one tested dialog, a checkbox's `checked` JavaScript property was stale while the visible tick and DOM `checked` attribute/class correctly reflected the selection. A screenshot plus downloaded-content verification resolved this; do not repeatedly toggle based on one contradictory property.

Arm the browser download event, click the visible official action, and use the returned file path. Verify a real DOCX ZIP with `word/document.xml`, then compute a hash. A successful HTTP status or a `.docx` filename alone is not proof.

If the event times out, inspect the live dialog and actual download destination before any retry. The 100-question trial required slider verification; after the user completed it, the file arrived without another final click. Record verification waiting separately and keep an uncertain quota attempt reserved until reconciled.

Preserve complete knowledge-tag strings. A tag can contain `、`, such as `指数幂的化简、求值`; blindly splitting every `、` corrupts it. Match the Word line against the captured full tag vocabulary with a unique segmentation, or preserve the raw line pending review. Save browser-only tags separately. Exam year/term, source display time and capture time are distinct fields.

## Source identity is a separate step

Downloaded Word often numbers questions 1, 2, 3 without preserving site IDs. Save the generated-paper/list ID order and visible identity evidence in bulk, then establish `actual Word ordinal → question_id` after downloading. Match against the saved question content, option order or diagrams as needed for identity; this is not a mathematical or teaching-value review. Export may reorder by type, so basket insertion order alone is insufficient. Perform automated matching where evidence permits, escalating only ambiguous items for focused source inspection instead of browsing every question or paper. A local identity worker may prepare the mapping; the acquisition coordinator commits the receipt.

In the 100-question trial, unique normalized stem/options selected the candidate identity independently of basket order. Word VML shape `alt` values contained `eqId` identifiers matching the captured website SVG formula IDs, providing an additional sequence check for 99 questions. A remaining image-count difference was an equivalent native Word math expression, not a missing source question. Match against actual XML and captured DOM evidence; do not assume every future export retains these IDs. Strip only verified question-number/source-title prefixes, preserve substantive conditions, and retain per-question evidence and ambiguous cases.

Reuse an existing download to calibrate this mapping. A single-question calibration download consumes a scarce download slot and should be exceptional. Preserve the complete original document and complete mapping; splitting author/review work does not require more downloads.

Record source-side evidence independently from the generated data:

```json
{
  "question_id": "observed site ID",
  "source_url": "observed detail URL",
  "capture_date": "YYYY-MM-DD",
  "download_file": "originals/source.docx",
  "sha256": "computed original-file digest",
  "download_settings": ["DOCX", "卷尾", "解析", "知识点", "试题难度系数", "题文前来源", "高清图片"],
  "identity_verified": true,
  "identity_evidence": "Which visible content and ordering were compared",
  "cookie_or_token_stored": false
}
```

The example is a record template, not evidence of an actual download. Fill it from observations. Also record selection filters/preferences separately from original source metadata; the acquisition region must not overwrite `questions[].source_paper`. Retain the original and the source's usage attribution; external redistribution or production publishing is a separate scope decision.

## Captured queue and immediate continuation

Commit a batch as `captured` only after saving:

- the original, readable DOCX ZIP, its SHA-256 and basic export completeness evidence, including the expected questions and answer/explanation section;
- all observed site IDs, the actual DOCX ordinals, verified counts and concrete identity-matching evidence;
- available UI metadata, macro category, selection region/mode, source cursor and export settings, with unknown values explicit;
- a receipt binding those artifacts and metadata by hash, plus the account attempt/charge outcome.

This capture receipt is not a completed annotation manifest or mathematical acceptance. Missing teaching tags, uncertain raw source regions, unfinished guidance, blind review and pending backup do not block this milestone. Missing or ambiguous identities and corrupt/truncated files remain a capture exception. Preserve partial evidence for recovery; do not mark it captured or silently consume another download slot to repair it.

Publish the immutable packet into the coordinator-maintained `captured` queue and promptly push its captured IDs/source hashes to the enabled Git registry. Immediately begin the next batch **if it is already authorized and the account has usable capacity**. Parsing, source enrichment, tagging, guidance, blind solving and review run independently under [agent-handoffs.md](agent-handoffs.md); do not wait for them to finish before continuing acquisition. Drive's default `batch_end` archive waits until the batch's local work/checks finish, while Git state does not. The local runner does not implement this acquisition queue. If the active instruction is one 100-question test, stop acquiring after that batch even when the daily allowance is larger.

On resume, first reuse receipts, downloads, saved generated papers and basket state. Record whether the test used `fresh_generated`, `fresh_bulk_selected` or `reused_basket`, its starting count and prior origin. Reusing a partially filled basket can save work, but filling its remaining slots is not a fresh-selection timing for 100 questions. A fresh-generation comparison must record a new start and keep old-basket evidence separate.

## Full batches and the shared daily allowance

The official [daily download limit](https://zujuan.xkw.com/helper/articles/daily-download-limit.html), rechecked on 2026-11-06, states 20 downloads per member account per day and up to 100 questions per download. Treat these as account-specific observed limits, not permanent constants for all accounts. Recheck when membership or the site's rules change. With all 20 slots available, 20 full, successful batches can acquire up to 2,000 question entries; unique usable questions and reviewed questions are separate counts.

**Acquisition loop: 1–2 macro categories → official intelligent/bulk selection → full-batch ID preflight → replace/refill to 100 and recheck → confirmed claim/reservation → one combined DOCX → integrity and ordinal receipt → captured queue and prompt state push → next authorized batch.** Local processing and final batch-end Drive archiving consume this queue independently. Do not download 100 individual questions and merge the files afterward: that does not save download slots.

- Use macro-topic coverage priorities, not fine selection quotas. Exclude exact IDs already captured or actively reserved across batches/sessions; fill from compatible broad categories when needed. Source papers may differ. Preserve each question's observed original school, paper, region and year in post-processing; a different raw region under a region preference is an evidence issue to record, not permission to relabel it. Do not add another subject/stage or known duplicate merely to fill space.
- Normal target size is 100, capped by the currently observed basket limit. Hold a short tail for the next compatible batch. A finite approved scope, a user deadline or an actual site limitation can justify a smaller final batch; record the reason. Do not split by author/reviewer workload at the website stage.
- Before the final download, check actual selected count, unique IDs, scope controls, export settings and the saved visible order. Validate the actual Word order afterward. Export answers, explanation and source metadata together. Reuse captured originals for parsing, layout tests, corrections and backup retries.
- Downstream preparation of a merged download uses `source_mode: mixed_papers` with `questions[].source_paper` for every question; see [data-contract.md](data-contract.md). Use `{}` when original paper metadata is unknown. The combined paper title and region preference are not original source evidence. Keep the complete manifest for the complete Word file; smaller author/review assignments do not change that document contract.

All sessions, agents and manual use of the same account share one daily allowance. Choose **one download coordinator per account** and a shared account ledger outside individual run folders. Different colleagues' independent accounts have separate account/site-day counters; their question IDs are globally shared through the Git registry. The local runner does not log into the site or enforce this quota ledger. Do not give workers sharing one account independent 20-download budgets. Public registry records use opaque aliases and permitted metadata only; keep the local file paths and account observations in private receipts.

Before clicking a final download, the coordinator reserves one attempt in the ledger with:

```text
account_alias, site_day_key, limit_verified_at, limit_evidence_url
daily_download_limit, max_questions_per_download
used_confirmed, reserved_attempts, uncertain_attempts, remaining_verified
batch_id, source_question_ids, ordered_id_mapping, question_count
owner_session, state, attempted_at, quota_charge_status
original_file, sha256, verified_question_count, failure_reason
authorized_batch_limit, selection_mode, region_selection_mode
basket_start_count, reused_basket_origin, capture_receipt, capture_completed_at
```

Use a non-secret alias, not login material. Record the site's day/reset basis when known; never reset the budget merely because a new session or local process started. Reconcile website history and other sessions/manual use before acquiring. A history row count is not necessarily the charge count; an unverified remainder stays unknown. On success, verify DOCX integrity and all expected IDs, commit the receipt and mark IDs captured. On timeout, first inspect downloads/history/local files; keep an uncertain charge reserved until reconciled, rather than automatically clicking again. Stop website acquisition at the available limit and continue local work or queue the next site's download day. Record explicitly when site evidence shows an attempt did not count.

If remaining usable slots are R, the per-download cap is C, and the user has authorized A additional batches, the immediate acquisition ceiling is min(R, A) × C. The nominal 2,000 assumes R=20, C=100 and authorization for that volume; it is not a promise for a partly used day or of 2,000 fully reviewed questions. In a one-batch 100-question test, A=1. Report attempted/charged downloads, verified originals, unique captured IDs, pending processing, unused capacity and reviewed/admitted outputs separately. Time UI selection/download/capture separately from annotation/review/publication; see [scaling-and-recovery.md](scaling-and-recovery.md).

For a second answer/no-answer edition, the official [same-paper rule](https://zujuan.xkw.com/helper/articles/same-paper-download-count.html) says separate downloads from the original generation/detail page count twice, while accessing the already downloaded paper through “我的下载” to get its other edition does not add a count. Prefer one complete export; recheck this route before relying on it, and do not generalize it to arbitrary failed-download retries.
