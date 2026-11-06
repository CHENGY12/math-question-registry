# Agent handoffs

Read when separating acquisition from processing, dividing a batch or arranging independent mathematical review. Agents work on separate files; the coordinator performs merges and output commits. The user may assign these stages to different agents/subagents; they do not need to finish in one serial turn.

## Producer and consumers

One dedicated acquisition coordinator per account owns its logged-in session, basket/generated paper and shared daily-download ledger. It selects by broad category through official intelligent/bulk controls, falling back to whole-page bulk addition. Other agents do not operate that account in parallel or receive their own 20-download allowance. Colleagues with independent accounts have separate quotas but share canonical question IDs through [team-registry.md](team-registry.md).

The producer selects 1–2 macro categories within the observed 500-child-knowledge-node limit and rotates categories across authorized batches. This test is only one 100-question batch using 集合与常用逻辑用语 + 函数与导数. Before downloading, the producer bulk-extracts every current ID, checks within-batch duplicates plus `captured_questions` and other unfinished `reserved_batches`, replaces conflicts with official 换题/bulk regeneration, refills and rechecks the full list. It performs successful preflight and reservation serially; changing IDs invalidates the check. Consumers do not access the browser or quota. Downstream deduplication never substitutes for this gate.

The producer commits an immutable `captured` packet after original-file, source-ID/actual-ordinal, UI-metadata, count and hash checks. Consumers own parsing/enrichment, annotation, blind solving, review and publication packets independently. As soon as capture succeeds, the producer can begin the next **already authorized** batch; it does not await those consumers or Google Drive backup. A one-batch 100-question test remains bounded to one download batch. Daily capacity alone does not authorize more batches.

This producer/consumer queue is maintained by the coordinating agent; the local runner is not a persistent broker. Use a saved task index with packet hash, assigned owner, owned output path and actual state so a restart can resume. Commit each receipt/result once through its owner; do not have workers race to claim the same IDs or write a shared annotation file.

For team work, the acquisition coordinator owns the whole-batch Git claim: fixed question paths, one commit, normal push success before download. A conflicting push requires a fresh fetch and business-level ID check, not merging/rebasing an old claim or force-pushing. Push `downloading` before the website action and `captured` immediately after the receipt; neither waits for Drive. Public Git receives only permitted metadata, never question content, credentials or machine paths. A batch-completion worker creates a distinct operator/batch Drive archive only after the complete local batch is ready (`batch_end`); per-question auto upload is explicit compatibility, not the default.

## Work units

Acquisition units are full source documents or bounded site selections, normally 100 questions per download. Parse/cache units are complete documents because shared Word media and answer boundaries should be read once. Author/review units are question IDs with their subparts; several short questions may share one bounded invocation. Do not create extra website downloads to match smaller author/review packets. Start with a small number of concurrent consumer jobs and increase only when output quality and resource use remain acceptable.

Each assignment includes IDs, role, permitted inputs, owned output path, input hashes, expected schema, and stopping conditions. Tell workers that others are editing concurrently and that they must not revert or write other workers' files.

## Acquisition / identity packet

Inputs: the authorized batch count and question limit, subject/stage, actual region-control mode, broad-category plan, shared account quota ledger, IDs already captured/actively reserved, saved selection/basket evidence and download destination. Topic/type/difficulty proportions are soft targets. The producer does not evaluate each question's difficulty, teaching value or fine graph fit, and does not inspect each source paper merely because titles differ.

Output: original DOCX, all observed site IDs, actual Word ordinals with identity evidence, available UI/source metadata, selection filters/preferences, export settings, count/integrity checks, hashes and the download attempt/charge receipt. Unknown fields remain unknown. A Jiangsu preference is not evidence that each raw source region is Jiangsu; preserve differing regions and route them to source enrichment. A complete annotation manifest is not required to publish this raw capture packet. Never include login material.

An identity worker may match saved generated-paper evidence to Word ordinals without browsing or consuming quota, returning the proposed mapping and ambiguities to the acquisition coordinator. It must not infer an ID from an ordinal or claim identity because basket insertion order looks plausible. This identity/integrity check is the capture boundary, not a mathematical review. Ambiguous IDs remain capture exceptions; review/tagging exceptions are downstream work.

Suggested acquisition assignment:

> Own only the account-selection/download work and capture receipt for the authorized batch. Prefer official intelligent/bulk assembly, otherwise add whole pages within the subject and region-selection scope. Collect available metadata in bulk; check exact captured/reserved IDs, count, settings, original-file integrity and actual ordinal mapping. Do not perform per-item difficulty/type/value assessment or exact-ratio optimization. Save and hash the capture packet, enqueue it, then continue the next already authorized batch without waiting for downstream workers. Record whether the selection is fresh or reuses an old basket and its starting count. Stop at the user's batch bound or usable account limit.

## Intake / source enrichment packet

Inputs: one immutable captured packet and its receipt. Verify its hashes, parse the complete original once, and extract blocks/media without changing the original. Build the complete source manifest required by [data-contract.md](data-contract.md). A mixed-paper document uses per-question `source_paper`; use `{}` for unknown provenance and do not treat the combined export title as an original paper.

Preserve the acquisition filter/preference separately from raw region evidence. Resolve source metadata, normalize type/difficulty only with evidence, identify graph candidates/gaps, and check semantic duplicates downstream. A source region mismatch is recorded rather than silently repaired to the selected region. Escalate genuinely missing evidence; do not send every question back to the browser. Output identified raw question packets and owned input files for annotation/review. The completed consumer packet must retain every ordinal expected by the full document.

## Author packet

Inputs: one identified question's stem, options, subparts, original diagrams, source explanation, source labels, graph candidates, and the applicable editorial rules. Output: `solution_guide`, `presentation`, tag inferences and knowledge-alignment candidates with evidence. The author must not claim teacher approval or source authorship for added text.

Suggested assignment:

> For these IDs, write concise guidance: one sentence explaining the entry point and method choice, usually 2–3 key actions and 1–2 specific pitfalls. Cover all subparts and keep essential conditions visible. Keep the structured justification/reuse/check fields brief; do not repeat the full explanation. Use only the supplied question/source evidence. Preserve source content and log presentation edits. Own only the assigned annotation file; do not merge the bank. Identify uncertain math or missing source evidence explicitly.

## Blind solver packet

Include only the question ID, question text, choices/parts and required original figures. Exclude answer, explanation, guidance, source-answer filenames, correct-choice cues, reviewer conclusions, and answer-bearing image pages. Inspect image pixels as well as text fields for answer leakage.

Ask the independent solver to produce an answer, derivation, domain/degeneracy checks and ambiguity findings. Save and hash its output before exposing the source answer. “Separate prompt” does not imply OS filesystem isolation; state the actual isolation used.

## Review packet after sealing the blind answer

Inputs: the sealed solution, source answer/full explanation, authored guidance/presentation, original images and relevant alignment evidence. Output a new review record; do not overwrite the blind solution. Verify:

- answer agreement and a valid derivation, not only matching final text;
- nonzero denominators, signs, domains, distinct intersections, endpoint conventions and attainability;
- correct diagram reading, units, comparable proportions and sample/population distinctions;
- learning value and boundaries of any “套路”;
- source and inferred tag provenance, valid graph IDs and honest gaps;
- symbol, punctuation and editing fidelity.

Bind the review to canonical per-question annotation digests using sorted-key UTF-8 JSON, not just a filename. This allows another question's edits to leave the current review valid. Store `teacher_review: pending` unless an actual teacher has signed off. Agent mathematical review and automated structural checks are separate statuses.

Disagreement yields a documented issue and a review task. Do not repeatedly regenerate until reviewers happen to agree, or silently promote source errors as verified answers.
