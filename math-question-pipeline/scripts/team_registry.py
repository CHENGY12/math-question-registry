#!/usr/bin/env python3
"""Atomic question claims in a dedicated Git branch; no downloads or quota allocation.

All Git work happens in disposable repositories. Public records contain identifiers,
aliases and hashes only. Source material and private Drive receipts stay elsewhere.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from uuid import uuid4


FORMAT = "math-question-team-registry/1"
DEFAULT_BRANCH = "question-registry"
STATES = {"reserved", "downloading", "captured", "local_ready", "archived", "released"}
NEXT = {"reserved": {"downloading", "released"}, "downloading": {"captured"},
        "captured": {"local_ready"}, "local_ready": {"archived"}, "archived": set(), "released": set()}
ALIAS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
NAMESPACE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
HASH = re.compile(r"^[a-f0-9]{64}$")
DETAILS = {"source_sha256", "local_status", "validation_sha256", "artifact_key", "archive_manifest_sha256", "cloud_confirmed"}
META = {"format": FORMAT, "question_path": "questions/<platform>/<subject>/<question_id>.json",
        "quota_concurrency_supported": False, "automatic_ttl_release": False,
        "public_data_policy": "IDs, status, batch indices, aliases and hashes only; no source text, media, account identities, machine paths or Drive IDs/URLs."}


class RegistryError(ValueError):
    pass


class GitError(RegistryError):
    def __init__(self, phase, code):
        # Git errors may echo credential-bearing remote URLs; do not expose stderr.
        super().__init__("Git operation failed (%s, exit %s); remote details omitted." % (phase, code))
        self.phase, self.code = phase, code


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def alias(value, field):
    if not isinstance(value, str) or not ALIAS.fullmatch(value):
        raise RegistryError(field + " must be a public-safe alias, not an email, URL or machine path.")
    return value


def question_key(question):
    if not isinstance(question, dict) or set(question) - {"platform", "subject", "question_id", "details"}:
        raise RegistryError("Question entries allow only platform, subject, question_id and public-safe details.")
    for field in ["platform", "subject"]:
        if not isinstance(question.get(field), str) or not NAMESPACE.fullmatch(question[field]):
            raise RegistryError("Invalid " + field + " namespace.")
    if question["platform"] != "xkw" or question["subject"] != "gzsx":
        raise RegistryError("This workflow uses only canonical platform=xkw and subject=gzsx; aliases cannot bypass existing claims.")
    if not isinstance(question.get("question_id"), str) or not re.fullmatch(r"[1-9][0-9]{0,39}", question["question_id"]):
        raise RegistryError("question_id must be a canonical positive decimal string without leading zeros.")
    return "/".join(question[field] for field in ["platform", "subject", "question_id"])


def checked_details(value):
    if not isinstance(value, dict) or set(value) - DETAILS:
        raise RegistryError("Details contain disallowed public fields. Keep content, filenames, paths and Drive references private.")
    for field in ["source_sha256", "validation_sha256", "archive_manifest_sha256"]:
        if field in value and (not isinstance(value[field], str) or not HASH.fullmatch(value[field])):
            raise RegistryError(field + " must be a SHA256 digest.")
    if "local_status" in value and value["local_status"] not in {"source_received", "ready"}:
        raise RegistryError("local_status must be source_received or ready.")
    if "artifact_key" in value:
        alias(value["artifact_key"], "artifact_key")
    if "cloud_confirmed" in value and type(value["cloud_confirmed"]) is not bool:
        raise RegistryError("cloud_confirmed must be an explicit boolean.")
    return value


def validate_request(action, request):
    allowed = {"owner", "batch_id", "account_id", "claim_token", "questions", "details", "to_state", "state"}
    if not isinstance(request, dict) or set(request) - allowed:
        raise RegistryError("Unknown request fields are prohibited in the public registry.")
    questions = request.get("questions")
    if not isinstance(questions, list) or not 1 <= len(questions) <= 100:
        raise RegistryError("One atomic request must contain 1–100 questions.")
    keys = [question_key(question) for question in questions]
    if len(set(keys)) != len(keys):
        raise RegistryError("Duplicate IDs in one atomic request.")
    for field in ["owner", "batch_id", "account_id"]:
        alias(request.get(field), field)
    if action in {"transition", "release"} and not request.get("claim_token"):
        raise RegistryError("Transitions require the successful claim token.")
    if request.get("claim_token"):
        alias(request["claim_token"], "claim_token")
    checked_details(request.get("details", {}))
    for question in questions:
        checked_details(question.get("details", {}))
    if action == "transition" and request.get("to_state") not in STATES - {"reserved", "released"}:
        raise RegistryError("Use an allowed to_state; release uses its own reserved-only command.")
    if action == "seed" and request.get("state", "captured") not in {"captured", "local_ready", "archived"}:
        raise RegistryError("Seed records must represent already captured local material.")
    if action in {"claim", "release"} and (request.get("details") or any(q.get("details") for q in questions)):
        raise RegistryError("claim/release do not accept artifact changes.")
    return keys


class GitStore:
    def __init__(self, remote, branch=DEFAULT_BRANCH):
        if not isinstance(remote, str) or not remote or remote.startswith("-") or "\n" in remote or "::" in remote:
            raise RegistryError("Invalid registry remote.")
        self.remote = str(Path(remote).expanduser().resolve()) if ":" not in remote else remote
        self.branch = branch
        self.temporary = None

    def __enter__(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="question-team-registry-")
        self.root = Path(self.temporary.name).resolve()
        self.git("init", "--quiet")
        self.git("check-ref-format", "--branch", self.branch)
        self.git("config", "user.name", "Question Registry Client")
        self.git("config", "user.email", "registry@local.invalid")
        self.git("remote", "add", "origin", self.remote)
        return self

    def __exit__(self, *unused):
        self.temporary.cleanup()

    def git(self, *arguments, check=True):
        environment = dict(os.environ, GIT_TERMINAL_PROMPT="0")
        # A caller may itself be inside a worktree operation. Inherited repository
        # selectors must never redirect these commands into the user's project.
        for name in list(environment):
            if name in {"GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                        "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_CONFIG", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS"} or name.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")):
                environment.pop(name, None)
        result = subprocess.run(["git", "-c", "protocol.ext.allow=never", "-c", "core.hooksPath=" + str(self.root / ".disabled-hooks"), *arguments],
                                cwd=str(self.root), env=environment, text=True, capture_output=True, timeout=60)
        if check and result.returncode:
            raise GitError(arguments[0], result.returncode)
        return result

    def fetch(self, allow_missing=False):
        result = self.git("fetch", "--quiet", "--no-tags", "origin", "refs/heads/" + self.branch, check=False)
        if result.returncode:
            if allow_missing:
                probe = self.git("ls-remote", "--exit-code", "--heads", "origin", "refs/heads/" + self.branch, check=False)
                if probe.returncode == 2:
                    return None
            raise GitError("fetch", result.returncode)
        head = self.git("rev-parse", "FETCH_HEAD").stdout.strip()
        self.git("checkout", "--quiet", "--detach", "--force", head)
        self.git("clean", "-fd", "--quiet")
        marker = self.root / "registry.json"
        if not marker.is_file() or marker.is_symlink() or read_json(marker).get("format") != FORMAT:
            raise RegistryError("The dedicated branch is not a compatible question registry.")
        return head

    def record_path(self, key):
        path = self.root / "questions" / (key + ".json")
        if self.root not in path.resolve().parents or any(parent.is_symlink() for parent in [path, *path.parents] if parent != self.root):
            raise RegistryError("Registry record cannot escape the temporary checkout.")
        return path

    def read_record(self, key):
        path = self.record_path(key)
        if not path.is_file():
            return None
        record = read_json(path)
        if record.get("format") != FORMAT or record.get("key") != key or record.get("state") not in STATES:
            raise RegistryError("Invalid existing registry record: " + key)
        allowed = {"format", "key", "platform", "subject", "question_id", "state", "owner", "batch_id", "account_id", "claim_token", "claimed_at", "updated_at", "history"} | DETAILS
        if set(record) - allowed:
            raise RegistryError("Existing record violates the public-data allowlist.")
        for field in ["owner", "batch_id", "account_id", "claim_token"]:
            alias(record.get(field), field)
        checked_details({field: record[field] for field in DETAILS if field in record})
        if not isinstance(record.get("history"), list):
            raise RegistryError("Invalid registry event history.")
        for event in record["history"]:
            if not isinstance(event, dict) or set(event) != {"operation_id", "action", "from", "to", "at", "batch_id", "owner", "claim_token"}:
                raise RegistryError("Existing event violates the public-data allowlist.")
            for field in ["operation_id", "batch_id", "owner", "claim_token"]:
                alias(event[field], field)
            if event["action"] not in {"claim", "seed", "transition", "release"} or event["from"] not in STATES | {None} or event["to"] not in STATES:
                raise RegistryError("Invalid registry event transition.")
            try:
                datetime.fromisoformat(event["at"])
            except (ValueError, TypeError):
                raise RegistryError("Invalid registry event timestamp.")
        return record

    def commit_push(self, message):
        self.git("add", "--", "registry.json", "questions") if (self.root / "questions").exists() else self.git("add", "--", "registry.json")
        self.git("commit", "--quiet", "-m", message)
        return self.git("push", "--porcelain", "origin", "HEAD:refs/heads/" + self.branch, check=False)


def same_claim(record, request, token):
    return all(record.get(field) == request[field] for field in ["owner", "batch_id", "account_id"]) and record.get("claim_token") == token


def validate_completion(state, record):
    if state in {"captured", "local_ready", "archived"}:
        if not HASH.fullmatch(record.get("source_sha256", "")):
            raise RegistryError("captured must immediately record the original source SHA256.")
        expected = "source_received" if state == "captured" else "ready"
        if record.get("local_status") != expected:
            raise RegistryError(state + " requires local_status=" + expected)
    if state == "archived" and not (record.get("cloud_confirmed") is True and record.get("artifact_key") and record.get("archive_manifest_sha256")):
        raise RegistryError("archived requires confirmed batch upload, an opaque artifact_key and archive_manifest_sha256; keep its Drive receipt private.")


def apply_request(store, action, request, token, operation_id):
    conflicts, updates, existing = [], {}, {}
    for question in request["questions"]:
        key = question_key(question)
        old = store.read_record(key)
        existing[key] = old
        details = {**request.get("details", {}), **question.get("details", {})}
        if action in {"claim", "seed"}:
            target = "reserved" if action == "claim" else request.get("state", "captured")
            if old and old["state"] != "released":
                if same_claim(old, request, token) and old["state"] == target and all(old.get(k) == v for k, v in details.items()):
                    continue
                conflicts.append({"key": key, "question_id": question["question_id"], "state": old["state"], "batch_id": old["batch_id"], "reason": "already_registered"})
                continue
            record = {"format": FORMAT, "key": key, **{field: question[field] for field in ["platform", "subject", "question_id"]},
                      **{field: request[field] for field in ["owner", "batch_id", "account_id"]},
                      "claim_token": token, "claimed_at": timestamp(), "history": list(old.get("history", [])) if old else []}
        else:
            target = "released" if action == "release" else request["to_state"]
            if not old or not same_claim(old, request, token):
                conflicts.append({"key": key, "question_id": question["question_id"], "reason": "claim_identity_mismatch"})
                continue
            if old["state"] == target and all(old.get(k) == v for k, v in details.items()):
                continue
            if target not in NEXT[old["state"]]:
                conflicts.append({"key": key, "question_id": question["question_id"], "state": old["state"], "reason": "illegal_transition"})
                continue
            if "source_sha256" in details and old.get("source_sha256") not in {None, details["source_sha256"]}:
                raise RegistryError("A captured source digest cannot be overwritten.")
            record = {**old, "history": list(old["history"])}
        record.update(details)
        record.update(state=target, updated_at=timestamp())
        validate_completion(target, record)
        record["history"].append({"operation_id": operation_id, "action": action, "from": old["state"] if old else None,
                                  "to": target, "at": record["updated_at"], "batch_id": request["batch_id"], "owner": request["owner"], "claim_token": token})
        updates[key] = record
    return conflicts, updates, existing


def outcome(action, result, request, token, records=None, **extra):
    successful = result in {"COMMITTED", "CONFIRMED_AFTER_PUSH_ERROR", "ALREADY_APPLIED"}
    return {"result": result, "action": action, "batch_id": request["batch_id"], "claim_token": token,
            "question_count": len(request["questions"]), "download_permitted": successful and action == "claim",
            "quota_reservation_performed": False, **extra}


def transact(remote, branch, action, request, max_attempts=4, before_push=None):
    keys = validate_request(action, request)
    if not 1 <= max_attempts <= 10:
        raise RegistryError("max-attempts must be between 1 and 10.")
    token = request.get("claim_token") or uuid4().hex
    operation_id = uuid4().hex
    with GitStore(remote, branch) as store:
        for attempt in range(1, max_attempts + 1):
            head = store.fetch()
            conflicts, updates, _ = apply_request(store, action, request, token, operation_id)
            if conflicts:
                return outcome(action, "CONFLICT", request, token, conflicts=conflicts, attempts=attempt, atomic_batch_unchanged=True)
            if not updates:
                return outcome(action, "ALREADY_APPLIED", request, token, attempts=attempt, remote_head=head)
            for key, record in updates.items():
                write_json(store.record_path(key), record)
            if before_push:
                before_push(attempt)
            try:
                pushed = store.commit_push("registry: " + action + " " + request["batch_id"])
                if pushed.returncode == 0:
                    return outcome(action, "COMMITTED", request, token, attempts=attempt,
                                   commit=store.git("rev-parse", "HEAD").stdout.strip())
            except (OSError, subprocess.SubprocessError, GitError):
                pass
            # Never merge an obsolete claim. Fetch and inspect the authoritative
            # records, including after a transport error whose outcome is unknown.
            try:
                confirmed_head = store.fetch()
                confirmed = [store.read_record(key) for key in keys]
            except (RegistryError, OSError, subprocess.SubprocessError):
                return outcome(action, "UNKNOWN_PUSH_OUTCOME", request, token, attempts=attempt,
                               operation_id=operation_id, recovery="Do not download. Recheck this batch and claim_token against the remote before retrying.")
            if all(record and same_claim(record, request, token) and
                   any(event.get("operation_id") == operation_id for event in record.get("history", [])) for record in confirmed):
                return outcome(action, "CONFIRMED_AFTER_PUSH_ERROR", request, token, attempts=attempt, remote_head=confirmed_head)
            # The next iteration starts from a freshly fetched head and repeats
            # every semantic check; even non-overlapping claims get a new commit.
        return outcome(action, "RETRY_LIMIT", request, token, attempts=max_attempts,
                       recovery="No download authorization was issued; retry with the same claim_token after checking status.")


def initialize(remote, branch):
    with GitStore(remote, branch) as store:
        head = store.fetch(allow_missing=True)
        if head:
            return {"result": "READY", "remote_head": head, "created": False}
        write_json(store.root / "registry.json", META)
        try:
            push = store.commit_push("registry: initialize dedicated branch")
            if push.returncode == 0:
                return {"result": "READY", "created": True, "commit": store.git("rev-parse", "HEAD").stdout.strip()}
        except (OSError, subprocess.SubprocessError, GitError):
            pass
        try:
            head = store.fetch()
            return {"result": "READY", "created": False, "confirmed_after_push_error": True, "remote_head": head}
        except (RegistryError, OSError, subprocess.SubprocessError):
            return {"result": "UNKNOWN_PUSH_OUTCOME", "created": None, "download_permitted": False}


def status(remote, branch, request=None):
    request = request or {}
    if set(request) - {"questions", "batch_id"}:
        raise RegistryError("status accepts only questions or batch_id filters.")
    with GitStore(remote, branch) as store:
        head = store.fetch()
        if "questions" in request:
            keys = [question_key(question) for question in request["questions"]]
        else:
            keys = [p.relative_to(store.root / "questions").as_posix()[:-5] for p in sorted((store.root / "questions").glob("*/*/*.json"))]
        records = [store.read_record(key) for key in keys]
        if request.get("batch_id"):
            records = [r for r in records if r and r.get("batch_id") == request["batch_id"]]
        return {"result": "READ_ONLY", "remote_head": head, "records": records,
                "download_permitted": False, "quota_concurrency_supported": False,
                "note": "Reading status alone never grants a new download; use successful atomic claim and record downloading before acquisition."}


def template():
    return {"registry_file": META, "default_branch": DEFAULT_BRANCH,
            "claim_request": {"owner": "agent-alias", "account_id": "account-alias", "batch_id": "batch-001",
                              "questions": [{"platform": "xkw", "subject": "gzsx", "question_id": "12345678"}]},
            "seed_instructions": "Use seed with state=captured, details.source_sha256 and details.local_status=source_received for each already-downloaded question; 1–100 items commit atomically.",
            "transition_order": ["reserved", "downloading", "captured", "local_ready", "archived"],
            "release": "reserved only; downloading is never released by a timer",
            "archive_instructions": "After batch upload is verified, transition local_ready to archived with cloud_confirmed=true, artifact_key and archive_manifest_sha256. Keep Drive URLs/IDs in a private receipt.",
            "scope": "Question-ID ownership only. Account quotas still require one acquisition coordinator; no automatic downloads or Drive uploads."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["init-template", "init", "seed", "claim", "status", "transition", "release"])
    parser.add_argument("--remote", help="Dedicated registry remote; never included in output.")
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--input", help="JSON file, or - for stdin. Mutation commands default to stdin.")
    parser.add_argument("--max-attempts", type=int, default=4)
    args = parser.parse_args()
    try:
        if args.action == "init-template":
            result = template()
        else:
            if not args.remote:
                raise RegistryError("--remote is required.")
            if args.action == "init":
                result = initialize(args.remote, args.branch)
            else:
                request = {} if args.action == "status" and args.input is None else json.loads(
                    Path(args.input).read_text(encoding="utf-8") if args.input not in {None, "-"} else sys.stdin.read())
                result = status(args.remote, args.branch, request) if args.action == "status" else transact(
                    args.remote, args.branch, args.action, request, args.max_attempts)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("result") in {None, "READY", "READ_ONLY", "COMMITTED", "CONFIRMED_AFTER_PUSH_ERROR", "ALREADY_APPLIED"} else 2
    except (RegistryError, OSError, ValueError, subprocess.SubprocessError) as error:
        message = str(error) if isinstance(error, RegistryError) else "Local input or Git transport failed; potentially sensitive details omitted."
        print(json.dumps({"result": "ERROR", "error_type": type(error).__name__, "message": message, "download_permitted": False}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
