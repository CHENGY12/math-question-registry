#!/usr/bin/env python3
"""Portable, resumable local ingestion. Source acquisition and model work are separate."""
import argparse
import concurrent.futures
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from uuid import uuid4


STATE_VERSION = "math-question-pipeline/1"
MANAGED_DIR = ".pipeline"
MAX_WORKERS = 32


class PipelineError(Exception):
    pass


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def digest_bytes(value):
    return hashlib.sha256(value).hexdigest()


def digest_file(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def atomic_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + "." + uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


def write_json(path, value):
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"))


def read_json(path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def contained(root, relative):
    """Only lexical relative paths and resolved in-root locations may enter artifacts."""
    rel = Path(relative)
    if rel.is_absolute() or not rel.parts or ".." in rel.parts:
        raise PipelineError("Unsafe relative path: " + str(relative))
    target = (root / rel).resolve()
    if target == root or root not in target.parents:
        raise PipelineError("Path escapes its root: " + str(relative))
    return target


def inventory(root, exclude=()):
    excluded = set(exclude)
    result = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if relative in excluded:
            continue
        if path.is_symlink():
            raise PipelineError("Generated artifacts cannot be symbolic links: " + relative)
        if path.is_file():
            result[relative] = digest_file(path)
    return result


def load_lib():
    return importlib.import_module("lib.pipeline_lib")


def load_backup_lib():
    return importlib.import_module("lib.question_backup")


def lock_fd(stream):
    if os.name == "nt":
        import msvcrt
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def unlock_fd(stream):
    if os.name == "nt":
        import msvcrt
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class OutputLock:
    """Kernel advisory locks are released after crashes; PID files are informational."""
    def __init__(self, output, action="run"):
        self.output, self.action, self.stream = output, action, None

    def __enter__(self):
        path = self.output / MANAGED_DIR / "run.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = path.open("a+", encoding="utf-8")
        # Windows byte-range locking needs an existing byte.
        if path.stat().st_size == 0:
            self.stream.write("\n")
            self.stream.flush()
        try:
            lock_fd(self.stream)
        except (OSError, BlockingIOError):
            self.stream.close()
            self.stream = None
            raise PipelineError("This output directory already has an active run or verification.")
        self.stream.seek(0)
        self.stream.truncate()
        self.stream.write(json.dumps({"pid": os.getpid(), "host": socket.gethostname(),
                                     "action": self.action, "acquired_at": now()}))
        self.stream.flush()
        return self

    def __exit__(self, *unused):
        if self.stream is not None:
            unlock_fd(self.stream)
            self.stream.close()


def lock_active(output):
    path = output / MANAGED_DIR / "run.lock"
    if not path.is_file():
        return False
    with path.open("r+", encoding="utf-8") as stream:
        try:
            lock_fd(stream)
        except (OSError, BlockingIOError):
            return True
        unlock_fd(stream)
    return False


def checked_roots(input_path, output_path):
    input_root, output_root = Path(input_path).expanduser().resolve(), Path(output_path).expanduser().resolve()
    if not input_root.is_dir():
        raise PipelineError("Input directory does not exist: " + str(input_root))
    if input_root == output_root or input_root in output_root.parents or output_root in input_root.parents:
        raise PipelineError("Input and output must be separate, non-overlapping directories.")
    if output_root == Path(output_root.anchor):
        raise PipelineError("The filesystem root cannot be an output directory.")
    for name in [MANAGED_DIR, MANAGED_DIR + "/cache", MANAGED_DIR + "/staging", MANAGED_DIR + "/quarantine"]:
        if (output_root / name).is_symlink():
            raise PipelineError("Pipeline state directories cannot be symbolic links.")
    marker = output_root / MANAGED_DIR / "owner.json"
    if output_root.exists() and any(output_root.iterdir()) and not marker.is_file():
        raise PipelineError("Refusing to overwrite a non-empty directory that is not a pipeline output.")
    if marker.exists() and read_json(marker).get("format") != STATE_VERSION:
        raise PipelineError("Output belongs to a different pipeline format.")
    return input_root, output_root


def load_questions(root):
    path = root / "questions.jsonl"
    result = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                result.append(json.loads(line))
            except ValueError as error:
                raise PipelineError("Invalid JSONL at line %d: %s" % (line_number, error))
    return result


def validate_job(root, description, lib):
    questions = load_questions(root)
    ids = [q["id"] for q in questions]
    if len(ids) != len(set(ids)):
        raise PipelineError("A document emitted duplicate question IDs.")
    # Adapter descriptors may identify source IDs or canonical IDs; accept either explicit form.
    expected = set(str(qid) for qid in description["question_ids"])
    actual_source = {str(q.get("source", {}).get("question_id", q["id"])) for q in questions}
    if set(ids) != expected and actual_source != expected:
        raise PipelineError("Extracted question IDs differ from the source manifest.")
    if not questions:
        raise PipelineError("A completed document must contain at least one question.")
    for question in questions:
        lib.validate_question(question, root)
        individual = contained(root, "questions/" + question["id"] + ".json")
        if read_json(individual) != question:
            raise PipelineError("Individual JSON differs from JSONL: " + question["id"])
    return questions


def validate_cache(root, description, lib):
    if root.is_symlink():
        raise PipelineError("Cache directories cannot be symbolic links.")
    receipt_path = root / "cache-receipt.json"
    if not receipt_path.is_file():
        raise PipelineError("Cache has no completion receipt.")
    receipt = read_json(receipt_path)
    if receipt.get("key") != description["key"]:
        raise PipelineError("Cache key does not match its dependencies.")
    actual = inventory(root, {"cache-receipt.json"})
    if actual != receipt.get("files"):
        raise PipelineError("Cache artifact hash or file inventory changed.")
    return validate_job(root, description, lib)


def quarantine_dir(path, system, label):
    if not path.exists():
        return None
    destination = system / "quarantine" / (label + "-" + uuid4().hex)
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(str(path), str(destination))
    return destination.relative_to(system.parent).as_posix()


def transient(error):
    return isinstance(error, (TimeoutError, subprocess.TimeoutExpired, OSError)) and not isinstance(error, (FileNotFoundError, PermissionError))


def process_one(input_root, description, system, lib, max_attempts):
    started = time.perf_counter()
    key = description["key"]
    cache = system / "cache" / key
    failures = []
    for attempt in range(1, max_attempts + 1):
        stage = system / "staging" / (key + "-" + uuid4().hex)
        stage.mkdir(parents=True)
        try:
            metadata = lib.process_job(input_root, description, stage)
            questions = validate_job(stage, description, lib)
            if metadata.get("question_count") != len(questions):
                raise PipelineError("Adapter question count differs from its written data.")
            write_json(stage / "cache-receipt.json", {"format": STATE_VERSION, "key": key,
                "question_ids": [q["id"] for q in questions], "files": inventory(stage),
                "dependency_hashes": description.get("dependency_hashes", {})})
            cache.parent.mkdir(parents=True, exist_ok=True)
            os.replace(str(stage), str(cache))
            return {"status": "completed", "key": key, "cache": cache,
                    "question_count": len(questions), "attempts": attempt,
                    "elapsed_seconds": time.perf_counter() - started, "previous_attempt_errors": failures}
        except Exception as error:
            location = quarantine_dir(stage, system, "failed-" + key[:16])
            failures.append({"attempt": attempt, "error_type": type(error).__name__,
                             "message": str(error)[:2000], "artifacts": location})
            if attempt == max_attempts or not transient(error):
                return {"status": "failed", "key": key, "attempts": attempt,
                        "elapsed_seconds": time.perf_counter() - started, "errors": failures}
    raise AssertionError("Unreachable retry loop")


def copy_materials(cache, publish, key):
    # Adapter paths are content/job-addressed, including graph snapshots referenced by JSON.
    for folder in ["assets", "originals", "raw"]:
        source = cache / folder
        if not source.exists():
            continue
        for path in sorted(source.rglob("*")):
            if path.is_symlink():
                raise PipelineError("Cached material cannot be a symbolic link.")
            if not path.is_file():
                continue
            relative = path.relative_to(source)
            target = publish / folder / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if digest_file(target) != digest_file(path):
                    raise PipelineError("Conflicting material path: " + target.relative_to(publish).as_posix())
            else:
                shutil.copyfile(str(path), str(target))


def coverage(questions):
    candidates = {}
    for question in questions:
        for match in question.get("alignment", {}).get("matches", []):
            node_id = match["node_id"]
            item = candidates.setdefault(node_id, {"node_id": node_id, "name": match.get("node_name"),
                "primary_question_ids": [], "supporting_question_ids": [], "distribution": {}})
            field = "primary_question_ids" if match.get("role") == "primary" else "supporting_question_ids"
            if question["id"] not in item[field]:
                item[field].append(question["id"])
            if field == "primary_question_ids":
                tags = question.get("tags", {})
                key = "/".join(str(tags.get(name, {}).get("values", ["unknown"])[0])
                               if tags.get(name, {}).get("values") else "unknown"
                               for name in ["difficulty", "question_type"])
                item["distribution"][key] = item["distribution"].get(key, 0) + 1
    return {"unique_questions": len(questions), "candidate_nodes": list(candidates.values()),
            "teacher_approved_covered_node_ids": [],
            "note": "Candidate, supporting, and partially aligned questions do not establish approved curriculum coverage.",
            "unmapped": [{"question_id": q["id"], **gap} for q in questions for gap in q.get("alignment", {}).get("unmapped", [])]}


def publish_files(publish, output, state):
    """Individual replacements are atomic; the receipt is committed last.

    An interrupted multi-file publish is rejected by verify and rebuilt from verified caches.
    Only previously recorded generated files are removed; unrelated output files are untouched.
    """
    system = output / MANAGED_DIR
    previous_path = system / "published-files.json"
    previous = read_json(previous_path).get("files", []) if previous_path.exists() else []
    current = sorted(p.relative_to(publish).as_posix() for p in publish.rglob("*") if p.is_file())
    for relative in current:
        source, target = publish / relative, contained(output, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name("." + target.name + "." + uuid4().hex + ".tmp")
        try:
            shutil.copyfile(str(source), str(temporary))
            os.replace(str(temporary), str(target))
        finally:
            if temporary.exists():
                temporary.unlink()
    for relative in set(previous) - set(current):
        target = contained(output, relative)
        if target.is_file() and not target.is_symlink():
            target.unlink()
    write_json(previous_path, {"run_id": state["run_id"], "files": current})
    write_json(system / "publication-receipt.json", {"run_id": state["run_id"],
        "artifact_index_sha256": digest_file(output / "artifacts.json"),
        "run_report_sha256": digest_file(output / "run-report.json")})


def run(args):
    started = time.perf_counter()
    lib = load_lib()
    input_root, output = checked_roots(args.input, args.output)
    batch_path = contained(input_root, "inputs/batches.json")
    batches = read_json(batch_path)
    if not isinstance(batches, list) or not batches or not all(isinstance(v, str) and v for v in batches):
        raise PipelineError("inputs/batches.json must be a non-empty list of relative manifest paths.")
    if not (1 <= args.workers <= MAX_WORKERS and 1 <= args.max_attempts <= 5 and args.preview_limit >= 1):
        raise PipelineError("Require workers 1–32, max-attempts 1–5, and preview-limit >= 1.")
    output.mkdir(parents=True, exist_ok=True)
    system = output / MANAGED_DIR
    system.mkdir(exist_ok=True)
    write_json(system / "owner.json", {"format": STATE_VERSION})
    with OutputLock(output):
        state_path = system / "state.json"
        old_state = read_json(state_path) if state_path.exists() else {}
        previous_jobs = old_state.get("jobs", {})
        state = {"format": STATE_VERSION, "run_id": uuid4().hex, "status": "running", "started_at": now(),
                 "input": str(input_root), "output": str(output), "workers": args.workers,
                 "recovered_interrupted_run": old_state.get("status") in ["running", "interrupted"],
                 "jobs": {}, "max_attempts_per_invocation": args.max_attempts,
                 "backup_requested": (input_root / "inputs/backup.json").exists()}
        write_json(state_path, state)
        try:
            report = run_locked(args, lib, input_root, output, system, batches, state, previous_jobs, started)
        except BaseException as error:
            state.update(status="interrupted" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "failed",
                         finished_at=now(), error={"type": type(error).__name__, "message": str(error)[:2000]})
            write_json(state_path, state)
            raise
        # Publication is complete. Backup failures must never mark that publication failed
        # or mutate its signed reports. This still runs under the same output lock.
        if state["backup_requested"]:
            backup = backup_locked(output, input_root / "inputs/backup.json", input_root=input_root, lib=lib)
            return {**report, **backup}
        return {**report, "pipeline_result": report["result"],
                "backup_result": {"result": "NOT_CONFIGURED", "status": "not_configured", "cloud_confirmed": 0}}


def run_locked(args, lib, input_root, output, system, batches, state, previous_jobs, started):
    state_path = system / "state.json"
    phases = {}
    phase_start = time.perf_counter()
    descriptions, failures, cache_errors = {}, [], []
    unique_manifests = list(dict.fromkeys(batches))
    for manifest in unique_manifests:
        try:
            contained(input_root, manifest)
            description = lib.describe_job(input_root, manifest)
            key = description["key"]
            if not isinstance(key, str) or len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
                raise PipelineError("Adapter returned an invalid job key.")
            if key in descriptions:
                descriptions[key]["aliases"].append(manifest)
                continue
            descriptions[key] = {**description, "aliases": [manifest]}
            previous = previous_jobs.get(key, {})
            state["jobs"][key] = {"manifest": manifest, "status": "pending", "attempts_total": previous.get("attempts_total", 0),
                                  "question_ids": description["question_ids"], "cache_hit": False}
        except Exception as error:
            failure = {"manifest": manifest, "phase": "describe", "error_type": type(error).__name__, "message": str(error)[:2000]}
            failures.append(failure)
            key = "invalid-" + digest_bytes(manifest.encode())
            state["jobs"][key] = {"manifest": manifest, "status": "failed", "error": failure, "attempts_total": 0}
    phases["describe_seconds"] = time.perf_counter() - phase_start
    phase_start = time.perf_counter()
    completed, pending = {}, []
    for key, description in descriptions.items():
        path = system / "cache" / key
        if path.exists():
            try:
                questions = validate_cache(path, description, lib)
                completed[key] = {"status": "completed", "key": key, "cache": path, "attempts": 0,
                                  "elapsed_seconds": 0, "question_count": len(questions), "cache_hit": True}
                state["jobs"][key].update(status="completed", cache_hit=True, question_count=len(questions))
                continue
            except Exception as error:
                location = quarantine_dir(path, system, "corrupt-cache-" + key[:16])
                cache_errors.append({"key": key, "reason": str(error)[:2000], "artifacts": location})
        pending.append(description)
        state["jobs"][key]["status"] = "running"
    phases["cache_validation_seconds"] = time.perf_counter() - phase_start
    write_json(state_path, state)
    phase_start = time.perf_counter()
    job_seconds_sum = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(process_one, input_root, description, system, lib, args.max_attempts): description for description in pending}
        for future in concurrent.futures.as_completed(futures):
            description = futures[future]
            result = future.result()
            job_seconds_sum += result["elapsed_seconds"]
            key = description["key"]
            entry = state["jobs"][key]
            entry.update(status=result["status"], attempts_this_run=result["attempts"],
                         attempts_total=entry["attempts_total"] + result["attempts"],
                         processing_seconds=round(result["elapsed_seconds"], 6))
            if result["status"] == "completed":
                completed[key] = result
                entry["question_count"] = result["question_count"]
            else:
                failure = {"manifest": description["manifest_relative"], "phase": "process", "key": key, "errors": result["errors"]}
                failures.append(failure)
                entry["error"] = failure
            write_json(state_path, state)
    phases["processing_wall_seconds"] = time.perf_counter() - phase_start
    phases["job_processing_seconds_sum"] = job_seconds_sum
    phase_start = time.perf_counter()
    publish = system / "staging" / ("publish-" + state["run_id"])
    publish.mkdir(parents=True)
    records, conflicts = {}, {}
    seen_counts = 0
    for key, result in sorted(completed.items()):
        cache = result["cache"]
        copy_materials(cache, publish, key)
        for question in load_questions(cache):
            seen_counts += 1
            qid = question["id"]
            encoded = canonical(question)
            if qid in records and records[qid]["encoded"] != encoded:
                conflict = conflicts.setdefault(qid, {"question_id": qid, "reason": "Same source ID has different complete records; no version is silently selected.",
                                                     "jobs": [records[qid]["key"]]})
                if key not in conflict["jobs"]:
                    conflict["jobs"].append(key)
            else:
                records.setdefault(qid, {"question": question, "encoded": encoded, "key": key})
    for qid, conflict in conflicts.items():
        directory = system / "quarantine" / ("question-conflict-" + state["run_id"]) / qid
        for key in conflict["jobs"]:
            for question in load_questions(completed[key]["cache"]):
                if question["id"] == qid:
                    write_json(directory / (key + ".json"), question)
        conflict["artifacts"] = directory.relative_to(output).as_posix()
    questions = [records[qid]["question"] for qid in sorted(records) if qid not in conflicts]
    for question in questions:
        lib.validate_question(question, publish)
        write_json(contained(publish, "questions/" + question["id"] + ".json"), question)
    payload = b"".join(canonical(q) + b"\n" for q in questions)
    atomic_bytes(publish / "questions.jsonl", payload)
    write_json(publish / "question.schema.json", lib.question_schema())
    write_json(publish / "coverage.json", coverage(questions))
    write_json(publish / "quarantine.json", {"failed_jobs": failures, "question_conflicts": list(conflicts.values()), "repaired_corrupt_caches": cache_errors})
    phases["merge_and_validation_seconds"] = time.perf_counter() - phase_start
    phase_start = time.perf_counter()
    rendering = lib.render_bank(questions, publish, preview_limit=args.preview_limit)
    phases["render_seconds"] = time.perf_counter() - phase_start
    success = not failures and not conflicts and bool(questions)
    result = "PASS_FOR_LOCAL_PIPELINE" if success else "INCOMPLETE"
    validation = {"result": result, "format": STATE_VERSION, "question_count": len(questions),
        "question_ids_unique": True, "schema_checks": "pass", "individual_json_matches_jsonl": True,
        "media_integrity": "pass", "questions_jsonl_sha256": digest_bytes(payload),
        "failed_job_count": len(failures), "conflicting_question_ids": sorted(conflicts),
        "learning_content": "Provided annotations validated structurally; no fresh model generation or mathematical signoff is implied.",
        "teacher_signoff": "not_inferred_from_pipeline_success", "production_import_performed": False,
        "rendering": rendering}
    write_json(publish / "validation.json", validation)
    artifact_hashes = inventory(publish)
    write_json(publish / "artifacts.json", {"format": STATE_VERSION, "files": artifact_hashes})
    report = {"result": result, "run_id": state["run_id"], "started_at": state["started_at"], "finished_at": now(),
        "input_manifest_count": len(batches), "unique_manifest_count": len(unique_manifests), "unique_job_count": len(descriptions),
        "workers": args.workers, "completed_jobs": len(completed), "processed_jobs": len(pending),
        "cache_hits": sum(bool(result.get("cache_hit")) for result in completed.values()),
        "repaired_corrupt_caches": len(cache_errors), "question_count": len(questions),
        "duplicate_records_removed": seen_counts - len(records), "conflicting_question_count": len(conflicts),
        "failed_jobs": failures, "question_conflicts": list(conflicts.values()),
        "recovered_interrupted_run": state["recovered_interrupted_run"],
        "timings": {key: round(value, 6) for key, value in phases.items()},
        "elapsed_before_publish_seconds": round(time.perf_counter() - started, 6),
        "artifact_index_sha256": digest_file(publish / "artifacts.json"),
        "scope": "Local captured Word files plus existing annotations; no website, OCR, or fresh LLM calls. Timing is not a production capacity forecast.",
        "preview_question_limit": args.preview_limit, "rendering": rendering}
    write_json(publish / "run-report.json", report)
    phase_start = time.perf_counter()
    publish_files(publish, output, state)
    state.update(status="completed" if success else "incomplete", finished_at=now(), result=result,
                 question_count=len(questions), cache_hits=report["cache_hits"],
                 publish_seconds=round(time.perf_counter() - phase_start, 6),
                 total_seconds=round(time.perf_counter() - started, 6))
    write_json(state_path, state)
    shutil.rmtree(str(publish))  # Only this invocation's generated staging directory.
    return report


def verify(output_path):
    output = Path(output_path).expanduser().resolve()
    require_output(output)
    with OutputLock(output, "verify"):
        return verify_locked(output)


def require_output(output):
    if (output / MANAGED_DIR).is_symlink():
        raise PipelineError("Pipeline state directories cannot be symbolic links.")
    marker = output / MANAGED_DIR / "owner.json"
    if not marker.is_file() or read_json(marker).get("format") != STATE_VERSION:
        raise PipelineError("Not a recognized pipeline output.")


def verify_locked(output, lib=None):
    """Full artifact verification; the caller must already hold OutputLock."""
    lib = lib or load_lib()
    state = read_json(output / MANAGED_DIR / "state.json")
    if state.get("status") not in ["completed", "incomplete"]:
        raise PipelineError("The last run did not finish publication; rerun to recover from verified caches.")
    receipt = read_json(output / MANAGED_DIR / "publication-receipt.json")
    if receipt["run_id"] != state["run_id"]:
        raise PipelineError("Published output belongs to an older or interrupted run.")
    if receipt["artifact_index_sha256"] != digest_file(output / "artifacts.json"):
        raise PipelineError("Artifact index checksum changed.")
    if receipt["run_report_sha256"] != digest_file(output / "run-report.json"):
        raise PipelineError("Run report checksum changed.")
    index = read_json(output / "artifacts.json")
    for relative, expected in index["files"].items():
        path = contained(output, relative)
        if not path.is_file() or path.is_symlink() or digest_file(path) != expected:
            raise PipelineError("Published artifact is missing or changed: " + relative)
    report, validation = read_json(output / "run-report.json"), read_json(output / "validation.json")
    if report["artifact_index_sha256"] != receipt["artifact_index_sha256"]:
        raise PipelineError("Report refers to a different artifact index.")
    questions = load_questions(output)
    if len(questions) != len({q["id"] for q in questions}):
        raise PipelineError("Duplicate question IDs in published JSONL.")
    for question in questions:
        lib.validate_question(question, output)
        if read_json(contained(output, "questions/" + question["id"] + ".json")) != question:
            raise PipelineError("Individual JSON differs from JSONL.")
    actual_individuals = {path.name for path in (output / "questions").glob("*.json")}
    if actual_individuals != {q["id"] + ".json" for q in questions}:
        raise PipelineError("Individual question files contain missing or unlisted records.")
    if len(questions) != validation["question_count"] or len(questions) != report["question_count"]:
        raise PipelineError("Question count differs from reports.")
    if digest_file(output / "questions.jsonl") != validation["questions_jsonl_sha256"]:
        raise PipelineError("Question data checksum differs from validation.")
    return {"result": validation["result"], "artifact_integrity": "pass", "question_count": len(questions),
            "run_id": state["run_id"], "teacher_signoff": "not_inferred_from_artifact_verification"}


def backup_incomplete(result):
    return (bool(result.get("failed") or result.get("pending") or result.get("errors")) or
            result.get("result") not in ["STAGED_FOR_SYNC", "NOTHING_TO_BACK_UP", "NOT_CONFIGURED", "PENDING_LOCAL_COMPLETION"])


def backup_locked(output, config_path, question_ids=None, input_root=None, lib=None, batch_requested=False):
    """Verify under the publication lock; batch-end automation never transfers files."""
    backup_root = output / MANAGED_DIR / "backups"
    operation_path = backup_root / "last-operation.json"
    state = read_json(output / MANAGED_DIR / "state.json")
    operation = {"version": 1, "run_id": state["run_id"], "status": "running", "started_at": now(),
                 "pipeline_result": "NOT_VERIFIED", "selected_question_ids": question_ids}
    operation_writable = False
    try:
        if backup_root.is_symlink() or operation_path.is_symlink():
            raise PipelineError("Backup state paths cannot be symbolic links.")
        contained(output, MANAGED_DIR + "/backups/last-operation.json")
        operation_writable = True
        verification = verify_locked(output, lib=lib)
        operation["pipeline_result"] = verification["result"]
        write_json(operation_path, operation)
        if verification["result"] != "PASS_FOR_LOCAL_PIPELINE":
            summary = {"result": "SKIPPED_PIPELINE_INCOMPLETE", "status": "blocked", "cloud_confirmed": 0,
                       "errors": [{"message": "Backup requires a fully published, successful bank; repair and rerun first."}]}
        else:
            # Auto-run configs are constrained to the input; explicit CLI configs may live elsewhere.
            if input_root is not None:
                config_path = contained(input_root, "inputs/backup.json")
            config = read_json(Path(config_path).expanduser().resolve())
            mode = config.get("mode", "per_question")
            if mode not in ["per_question", "batch_end"]:
                raise PipelineError("Backup mode must be per_question or batch_end.")
            if batch_requested and mode != "batch_end":
                raise PipelineError("backup-batch requires mode: batch_end in its configuration.")
            if mode == "batch_end":
                if question_ids is not None:
                    raise PipelineError("Batch backup cannot select individual questions; finish and verify the whole configured batch.")
                adapter = load_backup_lib()
                summary = (adapter.pending_batch(config) if input_root is not None
                           else adapter.backup_batch(output, config))
            else:
                summary = load_backup_lib().backup_questions(output, config, question_ids=question_ids)
            if not isinstance(summary, dict) or not isinstance(summary.get("result"), str):
                raise PipelineError("Backup adapter returned an invalid summary.")
    except Exception as error:
        summary = {"result": "FAILED", "status": "failed", "failed": 1, "cloud_confirmed": 0,
                   "errors": [{"error_type": type(error).__name__, "message": str(error)[:2000]}]}
    operation_status = ("pending_local_completion" if summary.get("result") == "PENDING_LOCAL_COMPLETION"
                        else "incomplete" if backup_incomplete(summary) else "staged_for_sync")
    operation.update(status=operation_status,
                     finished_at=now(), backup_result=summary)
    if operation_writable:
        try:
            write_json(operation_path, operation)
        except OSError as error:
            summary = {**summary, "result": "FAILED", "status": "failed",
                       "errors": list(summary.get("errors", [])) + [{"error_type": type(error).__name__,
                           "message": "Could not persist backup operation outcome: " + str(error)[:1500]}]}
    pipeline_result = operation["pipeline_result"]
    if pipeline_result != "PASS_FOR_LOCAL_PIPELINE":
        result = "BACKUP_BLOCKED"
    elif summary.get("result") == "PENDING_LOCAL_COMPLETION":
        result = "PIPELINE_COMPLETE_BACKUP_PENDING_LOCAL_COMPLETION"
    else:
        result = "PIPELINE_COMPLETE_BACKUP_INCOMPLETE" if backup_incomplete(summary) else "PIPELINE_COMPLETE_BACKUP_STAGED_FOR_SYNC"
    return {"result": result, "pipeline_result": pipeline_result, "backup_result": summary, "run_id": state["run_id"]}


def backup(output_path, config_path, question_ids=None):
    output = Path(output_path).expanduser().resolve()
    require_output(output)
    with OutputLock(output, "backup"):
        return backup_locked(output, config_path, question_ids=question_ids)


def backup_batch(output_path, config_path):
    output = Path(output_path).expanduser().resolve()
    require_output(output)
    with OutputLock(output, "backup-batch"):
        return backup_locked(output, config_path, batch_requested=True)


def backup_status(output, state, active):
    root = output / MANAGED_DIR / "backups"
    result = {"requested_for_current_run": state.get("backup_requested", False),
              "cloud_confirmation": "not_verified_by_local_pipeline"}
    operation_path = root / "last-operation.json"
    if operation_path.is_file():
        operation = read_json(operation_path)
        result["last_operation"] = operation
        result["matches_current_run"] = operation.get("run_id") == state["run_id"]
        if operation.get("status") == "running" and not active:
            result["last_operation"] = {**operation, "status": "interrupted", "recovery": "Repeat backup with the same configuration."}
    else:
        result["status"] = "pending" if result["requested_for_current_run"] else "not_configured"
    module_path = root / "state.json"
    if module_path.is_file():
        module = read_json(module_path)
        counts = {}
        for key in module.get("latest", {}).values():
            entry = module.get("records", {}).get(key, {})
            name = entry.get("status", "unknown")
            counts[name] = counts.get(name, 0) + 1
        result.update(tracked_questions=len(module.get("latest", {})),
                      archived_versions=len(module.get("records", {})), latest_versions_by_status=counts)
    batch_path = root / "batches.json"
    if batch_path.is_file():
        batches = read_json(batch_path)
        result["batches"] = {"tracked_batches": len(batches.get("latest", {})),
                             "archived_versions": len(batches.get("records", {})),
                             "last_summary": batches.get("last_summary")}
    return result


def status(output_path):
    output = Path(output_path).expanduser().resolve()
    state_path = output / MANAGED_DIR / "state.json"
    if not state_path.is_file():
        raise PipelineError("No run state found.")
    state = read_json(state_path)
    active = lock_active(output)
    result = {"status": state["status"], "run_id": state["run_id"], "active_lock": active,
              "jobs": state["jobs"], "question_count": state.get("question_count"),
              "total_seconds": state.get("total_seconds"), "publish_seconds": state.get("publish_seconds"),
              "backup": backup_status(output, state, active)}
    if state["status"] == "running" and not active:
        result.update(status="interrupted", recovery="Rerun the same command; completed caches will be verified and reused.")
    return result


def inspect_docx(docx_path, output_path):
    """Materialize source blocks for an agent to identify and annotate; not a bank import."""
    source = Path(docx_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".docx":
        raise PipelineError("inspect requires an existing .docx file.")
    if output == source or output in source.parents:
        raise PipelineError("Inspection output cannot contain or overwrite the source document.")
    if output.exists() and any(output.iterdir()):
        raise PipelineError("Inspection output must be a new or empty directory.")
    output.mkdir(parents=True, exist_ok=True)
    result = load_lib().inspect_docx(source, output)
    return {"result": "INSPECTED_NOT_IDENTIFIED", "output": str(output), "inspection": result,
            "note": "Raw blocks and images only. Source IDs, document ordinals, tags, answers and guidance still require evidence and review."}


def doctor():
    checks = {"python": {"version": sys.version.split()[0], "ok": sys.version_info >= (3, 9)}}
    for module, distribution in [("lxml", "lxml"), ("PIL", "Pillow"), ("jsonschema", "jsonschema")]:
        try:
            importlib.import_module(module)
            checks[module] = {"ok": True, "version": importlib.metadata.version(distribution)}
        except (ImportError, importlib.metadata.PackageNotFoundError) as error:
            checks[module] = {"ok": False, "error": str(error)}
    node = shutil.which("node")
    try:
        node_version = subprocess.run([node, "--version"], text=True, capture_output=True, check=True, timeout=10).stdout.strip() if node else None
        checks["node"] = {"ok": bool(node_version and int(node_version.lstrip("v").split(".")[0]) >= 16), "version": node_version}
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        checks["node"] = {"ok": False, "error": str(error)}
    root = Path(__file__).resolve().parents[1]
    required = ["scripts/lib/pipeline_lib.py", "scripts/lib/question_backup.py", "scripts/render_math.cjs", "vendor/katex/katex.min.js", "vendor/katex/katex.min.css", "vendor/katex/LICENSE"]
    checks["bundled_files"] = {"ok": all((root / name).is_file() for name in required),
                               "missing": [name for name in required if not (root / name).is_file()]}
    return {"result": "READY" if all(item["ok"] for item in checks.values()) else "MISSING_DEPENDENCIES", "checks": checks,
            "network_required_for_run": False, "note": "Use the requirements file in your chosen Python environment; this command does not install or change anything."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Inspect local dependencies without installing anything.")
    inspect_parser = commands.add_parser("inspect", help="Extract raw Word blocks and images before preparing reviewed manifests.")
    inspect_parser.add_argument("--docx", required=True)
    inspect_parser.add_argument("--output", required=True)
    run_parser = commands.add_parser("run", help="Process captured inputs; safely resume by repeating this command.")
    run_parser.add_argument("--input", required=True)
    run_parser.add_argument("--output", required=True)
    run_parser.add_argument("--workers", type=int, default=4)
    run_parser.add_argument("--preview-limit", type=int, default=100)
    run_parser.add_argument("--max-attempts", type=int, default=2)
    backup_parser = commands.add_parser("backup", help="Verify a published bank and stage individual backups for Google Drive desktop sync.")
    backup_parser.add_argument("--output", required=True)
    backup_parser.add_argument("--config", required=True)
    backup_parser.add_argument("--question-id", action="append", dest="question_ids", help="Repeat to select specific question IDs; defaults to all published questions.")
    batch_parser = commands.add_parser("backup-batch", help="After completing all local work, verify and stage one portable archive for this operator's batch.")
    batch_parser.add_argument("--output", required=True)
    batch_parser.add_argument("--config", required=True)
    archive_parser = commands.add_parser("backup-verify", help="Verify a local backup ZIP and its restore contents; does not confirm cloud synchronization.")
    archive_parser.add_argument("--archive", required=True)
    for command in ["verify", "status"]:
        sub = commands.add_parser(command)
        sub.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        if args.command == "doctor":
            result = doctor()
            code = 0 if result["result"] == "READY" else 2
        elif args.command == "run":
            result = run(args)
            code = 0 if result["pipeline_result"] == "PASS_FOR_LOCAL_PIPELINE" and not backup_incomplete(result["backup_result"]) else 2
        elif args.command == "backup":
            result = backup(args.output, args.config, args.question_ids)
            code = 0 if result["pipeline_result"] == "PASS_FOR_LOCAL_PIPELINE" and not backup_incomplete(result["backup_result"]) else 2
        elif args.command == "backup-batch":
            result = backup_batch(args.output, args.config)
            code = 0 if result["pipeline_result"] == "PASS_FOR_LOCAL_PIPELINE" and not backup_incomplete(result["backup_result"]) else 2
        elif args.command == "backup-verify":
            result = load_backup_lib().verify_backup(Path(args.archive).expanduser().resolve())
            code = 0 if result.get("result") == "PASS" else 2
        elif args.command == "verify":
            result = verify(args.output)
            code = 0 if result["result"] == "PASS_FOR_LOCAL_PIPELINE" else 2
        elif args.command == "inspect":
            result, code = inspect_docx(args.docx, args.output), 0
        else:
            result, code = status(args.output), 0
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return code
    except KeyboardInterrupt:
        print(json.dumps({"result": "INTERRUPTED", "message": "Rerun the command to recover from completed, verified caches."}), file=sys.stderr)
        return 130
    except Exception as error:
        print(json.dumps({"result": "ERROR", "error_type": type(error).__name__, "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
