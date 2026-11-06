# Input and output contract

The supplied adapter is for high-school mathematics exports from 学科网·组卷网. It consumes reviewed annotations; it does not guess site IDs or generate guidance. Paths inside manifests are POSIX relative paths beneath `INPUT_ROOT`, without `..`, absolute paths, or symlink escape. The skill, input and output can each live at a different location.

## Workspace layout

```text
INPUT_ROOT/
  originals/*.docx
  inputs/batches.json
  inputs/*_manifest.json
  inputs/knowledge-snapshot.json
  inputs/learning-guidance.json
  inputs/presentation.json
  tag-taxonomy.json
```

`inputs/batches.json` is a nonempty array of manifest paths, e.g. `["inputs/batch-001_manifest.json"]`. Each manifest corresponds to one downloaded document. The DOCX must contain exactly the ordinals declared in that manifest; do not silently skip extra questions. Use `inspect` first to locate blocks and media relationship IDs.

### Source manifest

Required top-level fields:

| Field | Meaning |
|---|---|
| `capture_date` | Observed acquisition date, `YYYY-MM-DD`. |
| `list_url` | Observed stable source listing URL. |
| `download.file` | Relative original DOCX path. |
| `download.identity_matching` | Concrete evidence linking document ordinals to site IDs. |
| `graph_file` | Relative knowledge snapshot path. |
| `graph_origin` | Human-readable provenance for that graph/version; not a dependency on an external machine path. |
| `paper` | Shared original source paper for a single-paper document; use `{}` for a mixed-paper collection. Unknown metadata stays null. |
| `source_mode` | Optional `single_paper` (legacy default) or `mixed_papers`. Mixed-paper downloads require `source_paper` on every question. |
| `questions` | Nonempty array of the question records below. |

Useful download evidence fields include method, displayed action, download settings and original hash; they do not substitute for identity matching.

Each question entry requires:

- `id`: observed decimal site ID as a string; `ordinal`: positive integer in this DOCX.
- `type`: `single_choice`, `multiple_choice`, `fill_blank`, or `constructed_response`; `type_raw` and `subtype_raw` retain source wording, with null subtype when absent.
- `difficulty`: `{label, coefficient, normalized, label_3}`. Preserve the original coefficient in `[0,1]`. Explicitly map observed labels to `low/mid/high` and the display label. Do not invent numeric thresholds.
- `source_tags`: list of `{name, kind, url}` for observed `knowledge`, `solution_method`, or `competency` tags. Knowledge and difficulty must match the downloaded Word metadata.
- `stem_latex`; `options_latex`: `[{key:"A",content:"..."},...]`; `parts_latex`: `[{id:"1",content:"..."},...]`. Empty option/part arrays are valid when the type does not use them. These are source transcriptions, not normalized edits.
- `answer`: `{kind, value, summary_latex}`. Choice values are keys; blank values are strings; part values are `[{part:"1",latex:"..."},...]`. Keep original answers even if a reviewer later raises a correction proposal.
- `thinking_candidates`: `[{name, category, confidence, evidence},...]`; use `thinking_method`, `technique`, or `competency`. Empty means not assessed, not proven absence.
- `alignments`: `[{source_tag,node_id,relation,role,confidence,evidence},...]`; `role` is primary, secondary or supporting. Use only IDs in the provided semantic graph.
- `gaps`: `[{source_tag,proposal,reason},...]`; `topic_candidates`: an array of explicitly inferred topic names.

Optional: `source_paper` is a complete per-question source object and replaces the shared `paper`, without inheriting any missing school, city or year. For `source_mode: mixed_papers`, this field is mandatory for every question; use `{}` when the original source is unknown. Export title and website filter region are not a substitute for original paper evidence. `region`, `source.paper` and year inference use this resolved per-question source.

Optional: `source_url` when actually verified, `source_updated_at`, `year` plus `year_evidence`, `chapter:{values,evidence}`, `answer_verification`, `transcription_review`, and `figures`. A missing verified detail URL is marked as derived by the adapter rather than falsely marked visited.

For every source DrawingML diagram in the stem, supply a `figures` entry with `relationship_id`, `role:"stem_diagram"`, `types`, `alt` and reading provenance. The adapter adds original asset path/hash/dimensions. Record only defensible graph readings; leave unlabelled exact coordinates null. Equation images remain equation assets. A diagram missing its metadata fails processing.

### Knowledge snapshot and taxonomy

The graph has `version` and `nodes`. Each referenced node needs a stable `id`, `name`, and `semantic_available:true`; retain descriptions, aliases, scope and kind for agent alignment. A name match alone is insufficient. The output copies the snapshot under a content-addressed path and preserves the origin/version/hash.

The minimum taxonomy structure used by the adapter is:

```json
{
  "dimensions": {
    "solution_strategies": {
      "source_dictionary": {
        "逻辑推理能力": "逻辑推理",
        "数学运算能力": "数学运算",
        "直观想象能力": "直观想象",
        "数学建模能力": "数学建模"
      }
    }
  }
}
```

Maintain a versioned fuller taxonomy when expanding. The seven active dimensions are chapter, syllabus knowledge, question type, difficulty, question category, solution strategies and year. Correct rate, score rate and school paper-use are reserved. “数据分析” is a competency within the combined strategies tag dimension; its label does not replace substantive guidance.

### Learning guidance

`inputs/learning-guidance.json` has `version:"pilot-learning-v1"` and `questions`, a dictionary keyed by source ID. Each value contains:

```text
title, one_sentence
routes: [{part_id, label, trigger, goal, why,
          steps:[{action,reason},...], checkpoint},...]
transfer: {template, conditions:[...]}
pitfalls:[...], self_check:[...]
origin:"agent_authored", review_status:"pending_teacher_review"
```

There must be one ordered route per subpart; for a question without subparts, use one route with `part_id:null`. Each route needs at least two actionable steps. The adapter adds the version to each output guide. Follow [editorial-and-guidance.md](editorial-and-guidance.md) for content quality; field presence is not proof of good teaching.

Keep this structure concise. The default preview uses `one_sentence`, `steps.action` and `pitfalls`; for multiple subparts it also uses each route's `label` and `why`. Place any essential condition in these visible fields. Other fields remain in JSON for review and reuse and need not become repeated paragraphs in the preview.

### Normalized presentation

`inputs/presentation.json` has `version:"math-editorial-v1"` and a `questions` dictionary. Each value contains `version`, `origin:"editorial_normalization"`, `stem_latex`, `options`, `parts`, `answer_summary_latex`, `changes:[{field,before,after,reason},...]`, `source_preserved:true`, and `review_status:"pending_teacher_review"`. Preserve option and part IDs/order. Log actual edits; use `changes:[]` if no correction is needed. Never fabricate an edit solely to fill a field.

Use UTF-8 JSON tooling. Backslashes in JSON math must be escaped correctly; a programming-language `\frac` string accidentally converted to form feed can silently change the formula. Use raw strings or structured serialization. The runner rejects abnormal control characters and unmatched delimiters; KaTeX validates all formula syntax.

## Outputs and interpretation

The runner produces JSONL, per-question JSON, `question.schema.json`, original assets and documents, raw extraction/manifest/graph snapshots, bounded `preview.html`, `validation.json`, `coverage.json`, `run-report.json`, an artifact hash index and managed task/cache state. The current question contract is `question-bank-pilot/2.1`; keep source and normalized/inferred/generated fields distinct.

`PASS_FOR_LOCAL_PIPELINE` means deterministic processing succeeded, not that every answer was independently solved or that a teacher approved publication. Independent and teacher review records are separate artifacts. An output with failed jobs or conflicting IDs is partial and has a nonzero command result, even if the successful questions are available for inspection.

Formal admission to the user's bank requires the agreed content review; current local outputs retain `production_import_ready:false`. Do not write this intermediate format directly into a production platform without a separately verified adapter.
