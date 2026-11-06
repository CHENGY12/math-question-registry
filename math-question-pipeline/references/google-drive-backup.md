# 批末归档到 Google Drive

Use this reference when the user requests Drive backup. The current session's default is **`batch_end`**: each colleague finishes a complete batch's local download, tagging, guidance and checks, then packages and updates shared Drive once. Git claim/download status is pushed promptly throughout the batch; it must not wait for the final archive. See [team-registry.md](team-registry.md).

The desktop-folder transport uses an existing Google Drive for desktop sync root. Prefer a connected service when it supports the authorized operation; do not export credentials or invent a private API. Machine-specific destination configuration stays outside the portable package. The batch-mode extension and CLI below are implemented and passed local tests; those tests do not confirm a particular Drive upload or team deployment. The older per-question mode remains explicitly optional; it is not the selected default.

## Mode and completion boundary

- **`batch_end` (session default):** `run` records `pending_local_completion` and does not write Drive. After the complete expected batch is locally ready and verified, invoke `backup-batch`. Calling `backup` with this mode also means the whole batch and rejects `--question-id`; do not silently upload only a subset.
- **`per_question` (explicit automatic-backup compatibility choice):** only when the user chooses it, a successful publication can trigger separate archives for individual questions. It does not imply a cloud-confirmed upload or teacher approval.

Do not upload a batch whose expected IDs are missing, conflicting or incompletely published. Keep mathematical/editorial review and teacher signoff as their actual separate statuses; an archive never upgrades them. Capture receipts and Git `captured` state are published as soon as the source files pass identity/integrity checks, even while this batch-end archive is pending.

Configurations without `mode` retain legacy per-question automatic behavior, including in the new implementation. Set `mode: batch_end` explicitly for this workflow. An older installed package may not recognize the mode at all; verify it has `backup-batch` before using the configuration. If it does not, keep batch-end configuration outside the old auto-discovery path and run locally, preserving any existing configuration separately. Do not accidentally revert to per-question upload.

## Batch contents and distinct destinations

A batch archive contains all expected question JSON/JSONL, original referenced images and DOCX files, source manifests/ordinal evidence, knowledge snapshots, concise guidance/presentation, schema, offline preview, validation, actual review statuses and a content-hash manifest. With `review_index` configured, matching records bound to the question's current canonical digest can contribute directly referenced evidence under `review/questions/<qid>/review/`: these are redacted per-question extracts retaining original review-file hashes. Stale/mismatched records generate warnings and do not contribute attachments. Without an index, record the actual JSON review status and the missing-index warning. Do not invent reports or teacher signoff. Credentials, machine configuration, input backup settings and caches are excluded.

The implemented destination is `<subfolder>/<operator_alias>/<batch_id>/<content_version>.zip`; the retained local archive is under `OUTPUT_ROOT/.pipeline/backups/batch-archives/<operator_alias>/<batch_id>/<content_version>.zip`. Operator and batch aliases must start with an alphanumeric character and contain 1–80 alphanumeric, underscore or hyphen characters. Use distinct operator/batch identities, content-based versions and retained older versions. Never overwrite a same-name different-content archive or another colleague's file. An unchanged verified batch reuses its archive. Original-source hash and final-archive hash are distinct receipt fields. Changing attached review evidence can create a new version.

After archive member/hash and restoration checks, stage it to the configured Drive folder or upload through the authorized service. Record the exact cloud file ID/URL in a **private** receipt after observing it. The public Git registry receives only allowed metadata such as `artifact_key`, batch/version hash and confirmed state; do not publish private Drive links or local paths. Do not delete a cloud archive merely because a local source is removed.

## Configure the existing Drive folder

Confirm the intended account and a writable destination. A new folder under the user's own My Drive is a reasonable default when no location was specified; reuse an explicitly selected destination. Do not alter sharing permissions. Check that the desktop sync root exists; never create a replacement directory at a missing mount path and call it Drive.

Create `INPUT_ROOT/inputs/backup.json` with the following structure. Replace the example path and aliases with the actual local destination and this colleague's unique batch identity; no account credentials belong here.

```json
{
  "version": 1,
  "mode": "batch_end",
  "provider": "google_drive_desktop",
  "sync_root": "/actual/existing/Google Drive/My Drive",
  "subfolder": "教育题库备份/高中数学",
  "operator_alias": "operator-a",
  "batch_id": "batch-20261106-001",
  "review_index": "/actual/workspace/review/review-index.json",
  "review_root": "/actual/workspace",
  "max_attempts": 2
}
```

`review_index` is optional when no independent evidence exists. `review_root` bounds which referenced evidence files may be included; the default is the index's own directory. If legitimate evidence lives in a sibling revision folder, explicitly set a common workspace root. Reject paths or symbolic links escaping that scope; never recursively upload the whole workspace. Never create fake evidence to fill a missing review. Keep the configuration out of user-independent distribution ZIPs, and reconfigure the destination when moving to another machine. With no backup configuration, the runner remains local and makes no remote writes.

## Batch-end execution and recovery

`run` records `PENDING_LOCAL_COMPLETION` / `pending_local_completion` and performs no Drive copy in `batch_end`. Invoke the final backup only when the whole batch's local work and checks are complete.

```sh
python3 "$SKILL_ROOT/scripts/pipeline.py" verify --output "$OUTPUT_ROOT"
python3 "$SKILL_ROOT/scripts/pipeline.py" backup-batch --output "$OUTPUT_ROOT" --config "$INPUT_ROOT/inputs/backup.json"
python3 "$SKILL_ROOT/scripts/pipeline.py" status --output "$OUTPUT_ROOT"
python3 "$SKILL_ROOT/scripts/pipeline.py" backup-verify --archive "$BATCH_ARCHIVE"
```

Keep the archive, its manifest and retry receipt locally before copying. Inspect the last operation before retrying, retain completed versions and use bounded retries. A failed Drive copy does not invalidate the local verified bank or release already captured IDs for another download. Resume the same batch archive rather than re-downloading or repeating annotations. `backup-verify` supports both archive formats and performs local member/hash/restoration checks; it does not confirm Drive upload. The current verifier caps uncompressed archive content at 512 MiB; measure larger batches rather than claiming unbounded recovery.

Use one writer for each colleague/batch destination. Verify a temporary file before committing its final name; desktop synchronization is not a multi-host transactional uploader. Distinct destinations prevent colleagues from overwriting one another, but do not replace Git claim coordination. Tests must omit the real backup configuration or use an isolated temporary destination.

The copier verifies bytes written to the sync folder and reports `staged_for_sync`. The desktop app is responsible for uploading them. A copied archive is not evidence of a successful cloud upload. Record a distinct cloud confirmation only after an authorized Drive tool or the web UI shows that exact version; when feasible, download the cloud archive and verify its hash and members. Record the observed file/folder URL, version and verification scope outside the deterministic question artifacts.

If syncing is paused, the app is unavailable, or the network is down, keep the local archive and pending state. Do not repeatedly request login or silently drop the backup. Once the connection returns, let the existing client sync or retry the configured backup step. No background agent schedule is required for the desktop client's normal synchronization.

Google describes desktop sync status and pause/resume controls in [Drive for desktop help](https://support.google.com/drive/answer/10838124?hl=en). Actual account and cloud-file observations remain the evidence for a particular backup. Do not hold Git claim/download updates until this cloud confirmation; only the archive-completion transition depends on it.

## Optional per-question compatibility

Enable `mode: per_question` only by explicit choice. A question archive includes its JSON, referenced original media/document and graph snapshot, self-contained preview, schema, validation, hash manifest and applicable review evidence. It is a single-question recovery package, not the whole runner cache. Existing per-question commands are:

```sh
python3 "$SKILL_ROOT/scripts/pipeline.py" backup --output "$OUTPUT_ROOT" --config "$PER_QUESTION_CONFIG"
python3 "$SKILL_ROOT/scripts/pipeline.py" backup --output "$OUTPUT_ROOT" --config "$PER_QUESTION_CONFIG" --question-id "$QUESTION_ID"
python3 "$SKILL_ROOT/scripts/pipeline.py" backup-verify --archive "$QUESTION_ARCHIVE"
```

Use canonical question IDs. This mode retains local archives and its retry ledger under `OUTPUT_ROOT/.pipeline/backups`. Older configurations lacking `mode` may follow the legacy automatic behavior; migrate them explicitly instead of assuming they now mean batch-end. An unchanged question reuses its archive, while changed content or attached review evidence creates another version.

## Portability and scale

Do not assume one user's sync path on another machine. Each colleague uses their own authorized Drive access and independent operator/batch namespace. Git metadata coordinates acquisition; Drive stores immutable archive versions. A Drive-synchronized JSON file cannot serve as a multi-user claim lock. A centralized uploader or authenticated API may later replace the folder transport, but neither a cloud service nor live team synchronization is established merely by this document or local tests.
