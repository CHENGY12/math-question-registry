# 解题指导与编辑约定

These are project conventions for professional teaching material, not a claim to reproduce an official exam board's complete standard.

## Teach a reusable decision, not just an answer

Each guide identifies concrete signals in the stem, the target transformation, why the method is suitable, executable steps with reasons, applicability conditions, pitfalls, and a useful check. Multi-part problems require separate routes and consistent notation. The source explanation can support authoring, but the guide must add the method-selection logic that an answer key often omits.

## Keep the reading version concise

The user's preference is short, clear guidance. Default to **一句入手思路 + 2～3 个关键步骤 + 1～2 条易错提醒**. Ordinary questions should usually fit roughly 80–160 Chinese characters of teaching prose, excluding formula syntax; multi-part or difficult questions may need more. This is an editing target, not a hard validator limit. Preserve essential mathematical conditions even when they take extra space.

Combine the recognition signal and method-selection reason in `one_sentence`. Keep `steps.action` focused on decisive transformations, with any condition needed to make them valid. Routine algebra and full proof remain in the answer explanation. Put only question-specific errors in `pitfalls`; remove generic reminders, repeated conclusions and unneeded alternative methods.

Structured fields such as `trigger`, `goal`, `why`, step `reason`, `checkpoint`, `transfer` and `self_check` remain useful for review and reuse, but each should be brief. The default preview shows the lead, key actions and pitfalls; multi-part questions also show each part's method reason. Do not rely on hidden fields to supply a condition whose omission would make the visible method invalid. Do not turn the same point into separate “识别、目标、理由、迁移、自检” paragraphs for the reader.

For example, a line-perpendicularity guide can say: “已给一般式，直接用系数判垂直，可保留竖直线情形。列出系数关系并因式分解，再把参数代回原式。不要直接除以参数，以免漏掉零值。” Add the question's essential formula and result, rather than a second full derivation.

Good patterns include:

- For a modulus maximum: identify the geometric locus, prove a bound, then construct a permitted equality case. State whether whole circles and independent motion are required.
- For a parameterized line: check the equation remains a line; a coefficient-based criterion may avoid dropping a vertical-line case. Never divide by a parameter without handling zero.
- For a fixed value: express the target in moving coordinates and eliminate them with the curve constraint. One example does not prove a constant.
- For a fixed point: derive the line-parameter relation, then show a point is independent of every allowed parameter. Do not imply every parameter remains admissible.
- For several statistical plots: identify the quantity, chart, unit and denominator before comparing, summing or taking a complement. Sample inference is not an individual-level or causal claim.

An agent should not add all of these to every question. Select the obligations caused by the actual problem. Keep the primary route concise and understandable at the student's level; alternate methods are useful only with clear selection criteria.

## Mathematical editing

| Area | Check |
|---|---|
| Conditions | Domains, nonzero divisors, degenerate lines, signs, distinct intersections, excluded points and equality cases are explicit where used. |
| Symbols | Define variables; use one notation throughout. This profile uses `\mathrm{i}` for the imaginary unit and `\ell` for a line to avoid confusion with 1. |
| Formulas | Use structural LaTeX for fractions, roots, powers, indices, sets and modulus. Multiplication uses `\cdot` or conventional omission, not a Latin x. |
| Length and modulus | Distinguish unsigned length from coordinate difference. Explain removal of absolute values. |
| Chinese punctuation | Use consistent full-width sentence punctuation outside math semantics. Keep punctuation with the preceding formula visually where possible. |
| Math punctuation | Preserve semantic commas/brackets inside coordinates, functions and sets; do not globally replace them with Chinese punctuation. |
| Numbering | Keep A–D option order and（1）–（n）part order. Separate source IDs from print sequence numbers. Use one row per long text option. |
| Units and ranges | Keep units consistent; write Chinese age ranges with ～; clarify endpoint inclusion without changing the original question. |
| Images | Preserve original bytes, aspect ratio and question linkage. Distinguish equation images from diagrams using document structure; do not upscale every equation as a diagram. |
| Answers | Match answer kind and every part. In some Word exports the full proof precedes difficulty/knowledge metadata; concatenate answer and explanation blocks rather than assuming the final “详解” is complete. |
| Evidence | Keep raw content and all normalization changes. A source typo may be corrected for display with a record; disputed mathematical wording needs review. |
| Rendering | Typeset all questions, even those omitted from the bounded preview. Embed fonts/images for offline use. Check long expressions and narrow layouts visually; formula syntax success does not validate mathematics. |

Source images can retain source typography in the explicitly labelled raw section. Do not silently redraw a chart or alter an image's data. Default student print styles hide guidance, answers, source-tag panels and review controls; test an actual PDF before claiming a print-ready exported paper has been delivered.

## Review record

Record IDs, reviewed input digests, reviewer role, blind-solution digest if applicable, findings with evidence, accepted fixes, unresolved issues, and teacher status. Added guidance is agent-authored even when it is consistent with the source answer. Re-review a changed question's content; an unchanged unrelated question need not be re-solved merely because it shares a JSON file.
