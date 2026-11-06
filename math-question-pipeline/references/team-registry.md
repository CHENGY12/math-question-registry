# Git team registry and batch-end Drive archives

Use this reference when colleagues on different computers share acquisition state. `scripts/team_registry.py` passed nine isolated concurrency tests. On 2026-11-06 the authorized public repository `https://github.com/CHENGY12/math-question-registry` was initialized on branch `question-registry`; 5 historical IDs were seeded and the 100-question trial was claimed and marked captured successfully. A second simulated client was rejected for all 100 existing claims without writing. This verifies the owner's real remote access and duplicate gate, not colleagues' permissions: each collaborator still needs authorized Git credentials and write access. Coordinators invoke the CLI explicitly; no automatic runner or Drive hook pushes registry states.

## Public metadata boundary

Public Git contains canonical question IDs, lifecycle state, opaque owner/account aliases, batch indexes, hashes and an optional opaque Drive `artifact_key`. Do not commit question text, answers, images, source documents, actual website account identifiers, machine paths, credentials or private Drive links. Keep the actual Drive file ID/URL and local file paths in private artifact receipts; the public key can resolve to them through an authorized private manifest. Only approved collaborators can push; a public reader or fork does not confer claim ownership.

Use one dedicated registry branch, normally `question-registry`, and fixed per-question paths:

```text
questions/<canonical-platform>/<canonical-subject>/<decimal-question-id>.json
questions/xkw/gzsx/36249828.json
```

Do not change subject, platform aliases or filenames to bypass an existing platform/question-ID record. The first implementation accepts only canonical `xkw/gzsx`; other subjects/aliases require a later explicit extension. The same source ID is shared across colleagues and their website accounts. Each colleague/batch gets a distinct batch ID and Drive archive; the shared registry never becomes a shared mutable question bank.

## Whole-batch claim protocol

The current trial remains **one batch of 100**, not all nominal 20 daily slots. Each account has one acquisition coordinator. Processing agents work locally and do not use the browser or account quota.

1. Bulk-extract the complete current generated-paper/basket ID list. Check within-batch duplicates and all current captured or reserved IDs. Fetch the shared registry immediately before the claim and include its existing records in that check. An existing captured record remains unavailable even if its author has not yet uploaded a final archive.
2. If any ID conflicts, replace/refill through official controls and re-extract/recheck the whole batch. Do not download first and deduplicate later.
3. Build one claim transaction for the entire batch, at most 100 IDs: all canonical question records carry the same batch ID and enter one commit from the latest registry tip. Any unavailable ID rejects the entire claim. Record opaque owner, batch and account aliases plus a unique claim token. Do not acquire the 100 records through 100 independent pushes.
4. Send a **normal, non-forced push to the one shared branch**. The batch is owned only after remote success is confirmed. A local commit, dry run, downloaded registry snapshot, PR, fork or saved JSON file is not a successful claim.
5. On rejection, fetch the new tip and repeat the business-level availability checks. Discard/rebuild the unaccepted claim proposal from that tip. Do not automatically merge, rebase or cherry-pick the old claim, and never use force-push, a `+` refspec or branch deletion to make it win.
6. On a connection error or ambiguous push result, fetch and inspect the remote claim token and operation record. The CLI returns `UNKNOWN_PUSH_OUTCOME` if it cannot confirm the outcome; do not download or assume the claim failed. Reconcile the recorded operation before retrying.

Git normally rejects a non-fast-forward branch update. This protocol uses that rule as the contention point, then performs the question-level checks again; Git itself does not understand claim ownership. The all-or-none batch is a single commit on a single branch, not 100 independent file writes or a multi-service transaction. See [Git push documentation](https://git-scm.com/docs/git-push).

Do not edit registry files manually or merge competing claim commits outside this protocol. Protect the registry branch against force pushes and deletion when the host supports it. Compliant clients and authorized writers are part of the trust boundary; this is not protection against a collaborator intentionally bypassing the protocol.

## State must be pushed promptly

The intended lifecycle is `reserved → downloading → captured → local_ready → archived`. Each transition is an owned operation followed by a confirmed normal push. Keep the token and owner with retries.

- After claiming, push `downloading` and the account-attempt reservation **before** the official download action. An interrupted download stays uncertain until reconciled with the website history, local files and capture receipt.
- After the DOCX, complete actual ordinal mapping, IDs and hashes pass, push `captured` immediately. Include the source document hash and originating batch. This must not wait for tagging, review or Drive upload.
- After the whole batch finishes local tagging, guidance and the agreed checks, push `local_ready`. Preserve actual mathematical/editorial/teacher review statuses; local readiness is not invented teacher approval.
- At batch end, create and verify the complete archive and stage/upload it to the colleague's own batch destination. Push archive progress separately. Only move to `archived` after the exact version is confirmed in Drive; public metadata uses its hash and `artifact_key`, with actual Drive IDs/URLs in the private receipt.

The first CLI has no automatic TTL release or renewal command: an unreleased claim stays owned. A future lease/heartbeat extension may allow owner renewal, but expiry must never make an attempted or uncertain download available again. The release command permits only `reserved` work, after confirming no download attempt occurred. `downloading`, `captured` or later states require reconciliation rather than TTL cleanup.

Account capacity is keyed by opaque account alias plus the site's day/reset basis. Each colleague's independent account has its own allowance; sessions sharing an account share one allowance. All accounts share the team's question-ID registry. Record confirmed, reserved and uncertain attempts without deriving remaining quota from Git question counts or the number of website history rows. The registry CLI's question claims do not by themselves implement website quota enforcement.

## Implemented CLI

These commands are implemented; verify the installed `--help` when transferring versions. `init-template` prints a template; it does not configure a remote. Mutation inputs are UTF-8 JSON via `--input` or stdin; `status` can inspect the registry without an input file.

```sh
python3 "$SKILL_ROOT/scripts/team_registry.py" init-template
python3 "$SKILL_ROOT/scripts/team_registry.py" init --remote "$REGISTRY_REMOTE" --branch question-registry
python3 "$SKILL_ROOT/scripts/team_registry.py" seed --remote "$REGISTRY_REMOTE" --branch question-registry --input "$SEED_JSON"
python3 "$SKILL_ROOT/scripts/team_registry.py" claim --remote "$REGISTRY_REMOTE" --branch question-registry --input "$CLAIM_JSON"
python3 "$SKILL_ROOT/scripts/team_registry.py" transition --remote "$REGISTRY_REMOTE" --branch question-registry --input "$TRANSITION_JSON"
python3 "$SKILL_ROOT/scripts/team_registry.py" release --remote "$REGISTRY_REMOTE" --branch question-registry --input "$RELEASE_JSON"
python3 "$SKILL_ROOT/scripts/team_registry.py" status --remote "$REGISTRY_REMOTE" --branch question-registry
```

A claim input has common `owner`, `batch_id`, `account_id`, and `questions`, each with `platform`, `subject` and positive decimal-string `question_id` without leading zeros. Use opaque non-secret aliases. `claim_token` is optional for a first claim but required for `transition`/`release`; preserve the returned token across retries. `details` may be shared or overridden per question. A 100-question batch supplies exactly its 100 current IDs. Never put a machine's source-file path into a public record merely because an older local ledger had a `source_file` field.

Only a `claim` result with `download_permitted: true` and `COMMITTED`, `CONFIRMED_AFTER_PUSH_ERROR` or `ALREADY_APPLIED` grants that batch's download permission. `status` is read-only and cannot grant a new download; other results must not trigger one. `--max-attempts` defaults to 4 and bounds a transaction's fetch/recheck/push retries. The successful claim's token is then used to record `downloading` before the official action.

Transitions use `to_state`; seed uses `state`, defaulting to `captured`. Required `details` are `source_sha256` and `local_status: source_received` for capture/seed, then `local_status: ready` for `local_ready`. Archive confirmation additionally requires `cloud_confirmed: true`, opaque `artifact_key` and `archive_manifest_sha256`; source hashes are retained. `validation_sha256` is an allowed optional check receipt. The CLI rejects `source_file`, Drive URL/ID and other unapproved public fields.

Bootstrap once by initializing the chosen remote branch and seeding already captured IDs before colleagues begin. Verify access separately for each collaborator and test a two-client same-batch race: one claim wins; the other is rejected without a download. Also test a disjoint-batch retry, an ambiguous push, and refusal to release `downloading`. Local bare-repository tests are implementation evidence, not proof of GitHub permissions or live cross-computer operation. Do not automatically create a public repository, invite collaborators or deploy a paid service as part of reading this skill.

## Drive and future scale

Git claim/download state is pushed immediately; Drive artifacts are updated only at `batch_end` after local work finishes, as described in [google-drive-backup.md](google-drive-backup.md). A Drive-synchronized JSON file is neither the registry's authority nor a multi-user lock. Use separate `<operator>/<batch>/<content-version>` archive destinations and never overwrite another colleague's file.

If contention or registry size later warrants a service, replace the claim transport with a transactional database while retaining stable IDs, whole-batch claims, owner tokens and uncertain-download reconciliation. PostgreSQL unique constraints and transaction-bound inserts are one option; [INSERT / ON CONFLICT](https://www.postgresql.org/docs/current/sql-insert.html) describes concurrency behavior. This is an undeployed future design, not a selected paid service or a current cloud capability.
