"""State/cache/failure invariants, using a deterministic adapter contract fixture.

Run: python -m unittest discover -s tests -v
Real DOCX trials use the public CLI separately; these tests do not claim math quality.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import pipeline


class FixtureAdapter:
    def __init__(self):
        self.calls = []

    def describe_job(self, root, manifest_relative):
        m = pipeline.read_json(root / manifest_relative)
        guidance = pipeline.read_json(root / "inputs/guidance.json")[m["id"]]
        key = pipeline.digest_bytes(pipeline.canonical([m, guidance]))
        return {"key": key, "manifest_relative": manifest_relative,
                "question_ids": ["xkw_gzsx_" + m["id"]], "dependency_hashes": {"fixture": key}}

    def process_job(self, root, description, stage):
        self.calls.append(description["manifest_relative"])
        m = pipeline.read_json(root / description["manifest_relative"])
        if m.get("fail"):
            raise ValueError("Unsupported fixture document")
        guidance = pipeline.read_json(root / "inputs/guidance.json")[m["id"]]
        data = m["value"].encode()
        digest = pipeline.digest_bytes(data)
        asset = "assets/" + digest + ".bin"
        original = "originals/" + digest + ".docx"
        pipeline.atomic_bytes(stage / asset, data)
        pipeline.atomic_bytes(stage / original, data)
        question = {"id": "xkw_gzsx_" + m["id"], "value": m["value"], "guidance": guidance,
            "source": {"question_id": m["id"], "original_file": original, "original_sha256": digest},
            "assets": [{"path": asset, "sha256": digest}], "alignment": {"matches": [], "unmapped": []}}
        pipeline.write_json(stage / "questions" / (question["id"] + ".json"), question)
        pipeline.atomic_bytes(stage / "questions.jsonl", pipeline.canonical(question) + b"\n")
        return {"question_ids": [question["id"]], "question_count": 1}

    def question_schema(self):
        return {"type": "object", "required": ["id", "value", "assets"]}

    def validate_question(self, q, root):
        if not q["id"].startswith("xkw_gzsx_") or not q["value"]:
            raise ValueError("Invalid fixture question")
        for asset in q["assets"]:
            if pipeline.digest_file(root / asset["path"]) != asset["sha256"]:
                raise ValueError("Fixture asset checksum mismatch")

    def render_bank(self, questions, root, preview_limit=100):
        pipeline.atomic_bytes(root / "preview.html", ("<html><body>" + str(len(questions)) + "</body></html>").encode())
        return {"question_count": len(questions), "preview_question_count": min(len(questions), preview_limit)}


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="math-pipeline-contract-")
        self.root = Path(self.temporary.name)
        self.input = self.root / "inputs with spaces"
        self.output = self.root / "output with spaces"
        pipeline.write_json(self.input / "inputs/batches.json", ["inputs/a.json", "inputs/b.json"])
        pipeline.write_json(self.input / "inputs/a.json", {"id": "1", "value": "first"})
        pipeline.write_json(self.input / "inputs/b.json", {"id": "2", "value": "second"})
        pipeline.write_json(self.input / "inputs/guidance.json", {"1": "first guidance", "2": "second guidance"})
        self.lib = FixtureAdapter()
        self.patch = patch.object(pipeline, "load_lib", return_value=self.lib)
        self.patch.start()
        self.args = SimpleNamespace(input=str(self.input), output=str(self.output), workers=4, preview_limit=100, max_attempts=2)

    def tearDown(self):
        self.patch.stop()
        self.temporary.cleanup()

    def configure_backup(self):
        path = self.input / "inputs/backup.json"
        pipeline.write_json(path, {"version": 1, "provider": "google_drive_desktop",
            "sync_root": str(self.root / "mock sync root"), "subfolder": "题库备份/高中数学", "max_attempts": 2})
        return path

    def staged_summary(self, count=2):
        return {"result": "STAGED_FOR_SYNC", "status": "staged_for_sync", "selected_questions": count,
                "staged_for_sync": count, "failed": 0, "pending": 0, "cloud_confirmed": 0,
                "records": [], "errors": []}

    def test_cold_resume_and_serial_parallel_equivalence(self):
        before = pipeline.inventory(self.input)
        first = pipeline.run(self.args)
        self.assertEqual(first["result"], "PASS_FOR_LOCAL_PIPELINE")
        self.assertEqual(first["processed_jobs"], 2)
        data = (self.output / "questions.jsonl").read_bytes()
        (self.output / "unrelated-user-note.txt").write_text("keep")
        second = pipeline.run(self.args)
        self.assertEqual(second["cache_hits"], 2)
        self.assertEqual(second["processed_jobs"], 0)
        self.assertEqual(data, (self.output / "questions.jsonl").read_bytes())
        self.assertEqual(len(self.lib.calls), 2)
        self.assertEqual(pipeline.verify(self.output)["question_count"], 2)
        self.assertEqual((self.output / "unrelated-user-note.txt").read_text(), "keep")
        self.assertEqual(before, pipeline.inventory(self.input))
        self.args.output = str(self.root / "serial")
        self.args.workers = 1
        pipeline.run(self.args)
        self.assertEqual(data, (Path(self.args.output) / "questions.jsonl").read_bytes())

    def test_one_annotation_only_invalidates_its_document(self):
        pipeline.run(self.args)
        pipeline.write_json(self.input / "inputs/guidance.json", {"1": "improved guidance", "2": "second guidance"})
        result = pipeline.run(self.args)
        self.assertEqual(result["cache_hits"], 1)
        self.assertEqual(result["processed_jobs"], 1)
        self.assertEqual(self.lib.calls.count("inputs/b.json"), 1)
        self.assertEqual(pipeline.verify(self.output)["question_count"], 2)

    def test_corrupted_cache_is_rebuilt(self):
        pipeline.run(self.args)
        cache = next((self.output / ".pipeline/cache").iterdir())
        (cache / "questions.jsonl").write_text("tampered")
        result = pipeline.run(self.args)
        self.assertEqual(result["repaired_corrupt_caches"], 1)
        self.assertEqual(result["processed_jobs"], 1)
        self.assertEqual(result["cache_hits"], 1)
        self.assertEqual(pipeline.verify(self.output)["artifact_integrity"], "pass")

    def test_failed_document_isolated_then_repaired(self):
        pipeline.write_json(self.input / "inputs/b.json", {"id": "2", "value": "second", "fail": True})
        first = pipeline.run(self.args)
        self.assertEqual(first["result"], "INCOMPLETE")
        self.assertEqual(first["question_count"], 1)
        self.assertEqual(len(first["failed_jobs"]), 1)
        self.assertEqual(first["failed_jobs"][0]["errors"][0]["attempt"], 1)
        self.assertEqual(pipeline.verify(self.output)["result"], "INCOMPLETE")
        pipeline.write_json(self.input / "inputs/b.json", {"id": "2", "value": "second"})
        second = pipeline.run(self.args)
        self.assertEqual(second["result"], "PASS_FOR_LOCAL_PIPELINE")
        self.assertEqual(second["cache_hits"], 1)
        self.assertEqual(second["question_count"], 2)

    def test_duplicate_and_conflicting_ids(self):
        pipeline.write_json(self.input / "inputs/b.json", {"id": "1", "value": "first", "batch_token": "another source"})
        first = pipeline.run(self.args)
        self.assertEqual(first["question_count"], 1)
        self.assertEqual(first["duplicate_records_removed"], 1)
        pipeline.write_json(self.input / "inputs/b.json", {"id": "1", "value": "contradiction"})
        second = pipeline.run(self.args)
        self.assertEqual(second["result"], "INCOMPLETE")
        self.assertEqual(second["question_count"], 0)
        self.assertEqual(second["conflicting_question_count"], 1)
        conflict = second["question_conflicts"][0]
        self.assertEqual(len(list((self.output / conflict["artifacts"]).glob("*.json"))), 2)

    def test_interrupt_after_cache_commit_recovers(self):
        with patch.object(self.lib, "render_bank", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                pipeline.run(self.args)
        self.assertEqual(pipeline.status(self.output)["status"], "interrupted")
        with self.assertRaises(pipeline.PipelineError):
            pipeline.verify(self.output)
        result = pipeline.run(self.args)
        self.assertTrue(result["recovered_interrupted_run"])
        self.assertEqual(result["processed_jobs"], 0)
        self.assertEqual(result["cache_hits"], 2)
        self.assertEqual(pipeline.verify(self.output)["artifact_integrity"], "pass")

    def test_artifact_and_report_tampering_are_detected(self):
        pipeline.run(self.args)
        (self.output / "preview.html").write_text("changed")
        with self.assertRaisesRegex(pipeline.PipelineError, "changed"):
            pipeline.verify(self.output)
        pipeline.run(self.args)
        with (self.output / "run-report.json").open("a") as stream:
            stream.write(" ")
        with self.assertRaisesRegex(pipeline.PipelineError, "Run report"):
            pipeline.verify(self.output)

    def test_nonempty_output_and_overlap_rejected(self):
        self.args.output = str(self.input / "output")
        with self.assertRaises(pipeline.PipelineError):
            pipeline.run(self.args)
        self.output.mkdir()
        (self.output / "user-document.txt").write_text("untouched")
        self.args.output = str(self.output)
        with self.assertRaises(pipeline.PipelineError):
            pipeline.run(self.args)
        self.assertEqual((self.output / "user-document.txt").read_text(), "untouched")

    def test_unconfigured_run_does_not_load_or_write_backups(self):
        with patch.object(pipeline, "load_backup_lib") as backup_lib:
            result = pipeline.run(self.args)
        backup_lib.assert_not_called()
        self.assertEqual(result["pipeline_result"], "PASS_FOR_LOCAL_PIPELINE")
        self.assertEqual(result["backup_result"]["result"], "NOT_CONFIGURED")
        self.assertFalse((self.output / ".pipeline/backups").exists())
        self.assertFalse((self.root / "mock sync root").exists())
        self.assertEqual(pipeline.status(self.output)["backup"]["status"], "not_configured")

    def test_automatic_backup_follows_verified_publication_under_same_lock(self):
        config_path = self.configure_backup()
        observed = {}
        with patch.object(pipeline, "verify_locked", wraps=pipeline.verify_locked) as verify:
            def stage(output, config, question_ids=None):
                verify.assert_called_once()
                self.assertTrue(pipeline.lock_active(output))
                self.assertEqual(pipeline.read_json(output / ".pipeline/state.json")["status"], "completed")
                self.assertEqual(config, pipeline.read_json(config_path))
                self.assertIsNone(question_ids)
                observed["report"] = pipeline.digest_file(output / "run-report.json")
                return self.staged_summary()
            with patch.object(pipeline, "load_backup_lib", return_value=SimpleNamespace(backup_questions=stage)):
                result = pipeline.run(self.args)
        self.assertEqual(result["pipeline_result"], "PASS_FOR_LOCAL_PIPELINE")
        self.assertEqual(result["backup_result"]["staged_for_sync"], 2)
        self.assertEqual(result["backup_result"]["cloud_confirmed"], 0)
        self.assertEqual(observed["report"], pipeline.digest_file(self.output / "run-report.json"))
        self.assertEqual(pipeline.verify(self.output)["artifact_integrity"], "pass")
        backup = pipeline.status(self.output)["backup"]
        self.assertTrue(backup["matches_current_run"])
        self.assertEqual(backup["last_operation"]["status"], "staged_for_sync")
        self.assertFalse((self.root / "mock sync root").exists())

    def test_backup_failure_has_nonzero_cli_and_independent_retry_preserves_bank(self):
        config = self.configure_backup()
        failed = {"result": "PARTIAL", "status": "partial", "selected_questions": 2,
                  "staged_for_sync": 1, "failed": 1, "pending": 1, "cloud_confirmed": 0,
                  "errors": [{"message": "Mock sync directory unavailable"}]}
        with patch.object(pipeline, "load_backup_lib") as load:
            load.return_value.backup_questions.return_value = failed
            with patch.object(sys, "argv", ["pipeline.py", "run", "--input", str(self.input), "--output", str(self.output)]):
                with redirect_stdout(io.StringIO()) as stream:
                    code = pipeline.main()
            self.assertEqual(code, 2)
            result = json.loads(stream.getvalue())
            self.assertEqual(result["pipeline_result"], "PASS_FOR_LOCAL_PIPELINE")
            self.assertEqual(result["backup_result"]["failed"], 1)
            self.assertEqual(pipeline.verify(self.output)["result"], "PASS_FOR_LOCAL_PIPELINE")
            self.assertEqual(pipeline.status(self.output)["status"], "completed")
            report_hash = pipeline.digest_file(self.output / "run-report.json")
            load.return_value.backup_questions.return_value = self.staged_summary(1)
            with patch.object(sys, "argv", ["pipeline.py", "backup", "--output", str(self.output),
                    "--config", str(config), "--question-id", "xkw_gzsx_2"]):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(pipeline.main(), 0)
            self.assertEqual(load.return_value.backup_questions.call_args.kwargs["question_ids"], ["xkw_gzsx_2"])
        self.assertEqual(len(self.lib.calls), 2)
        self.assertEqual(report_hash, pipeline.digest_file(self.output / "run-report.json"))
        self.assertEqual(pipeline.verify(self.output)["question_count"], 2)
        self.assertFalse((self.root / "mock sync root").exists())

    def test_incomplete_or_tampered_publication_cannot_be_backed_up(self):
        config = self.configure_backup()
        pipeline.write_json(self.input / "inputs/b.json", {"id": "2", "value": "second", "fail": True})
        with patch.object(pipeline, "load_backup_lib") as load:
            result = pipeline.run(self.args)
            self.assertEqual(result["pipeline_result"], "INCOMPLETE")
            self.assertEqual(result["backup_result"]["result"], "SKIPPED_PIPELINE_INCOMPLETE")
            load.assert_not_called()
            pipeline.write_json(self.input / "inputs/b.json", {"id": "2", "value": "second"})
            load.return_value.backup_questions.return_value = self.staged_summary()
            pipeline.run(self.args)
            load.reset_mock()
            (self.output / "preview.html").write_text("corrupted after publication")
            blocked = pipeline.backup(self.output, config)
            self.assertEqual(blocked["pipeline_result"], "NOT_VERIFIED")
            self.assertEqual(blocked["result"], "BACKUP_BLOCKED")
            load.assert_not_called()

    def test_invalid_backup_config_does_not_invalidate_published_bank(self):
        config = self.configure_backup()
        config.write_text("not valid JSON")
        with patch.object(pipeline, "load_backup_lib") as load:
            result = pipeline.run(self.args)
        load.assert_not_called()
        self.assertEqual(result["pipeline_result"], "PASS_FOR_LOCAL_PIPELINE")
        self.assertTrue(pipeline.backup_incomplete(result["backup_result"]))
        self.assertEqual(pipeline.verify(self.output)["artifact_integrity"], "pass")
        self.assertEqual(pipeline.status(self.output)["backup"]["last_operation"]["status"], "incomplete")

    def test_backup_interrupt_preserves_publication_and_can_resume_independently(self):
        config = self.configure_backup()
        with patch.object(pipeline, "load_backup_lib") as load:
            load.return_value.backup_questions.side_effect = KeyboardInterrupt
            with self.assertRaises(KeyboardInterrupt):
                pipeline.run(self.args)
            self.assertEqual(pipeline.verify(self.output)["result"], "PASS_FOR_LOCAL_PIPELINE")
            status = pipeline.status(self.output)
            self.assertEqual(status["status"], "completed")
            self.assertEqual(status["backup"]["last_operation"]["status"], "interrupted")
            load.return_value.backup_questions.side_effect = None
            load.return_value.backup_questions.return_value = self.staged_summary()
            self.assertEqual(pipeline.backup(self.output, config)["backup_result"]["result"], "STAGED_FOR_SYNC")
        self.assertEqual(len(self.lib.calls), 2)

    def test_backup_archive_verification_cli_is_local(self):
        archive = self.root / "already downloaded.zip"
        with patch.object(pipeline, "load_backup_lib") as load:
            load.return_value.verify_backup.return_value = {"result": "PASS", "cloud_confirmed": False}
            with patch.object(sys, "argv", ["pipeline.py", "backup-verify", "--archive", str(archive)]):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(pipeline.main(), 0)
            load.return_value.verify_backup.assert_called_once_with(archive)
            load.return_value.backup_questions.assert_not_called()

    def test_process_lock_is_exclusive_and_crash_releases_it(self):
        code = """import sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from pipeline import OutputLock
with OutputLock(Path(sys.argv[2])):
 print('LOCKED',flush=True)
 time.sleep(60)
"""
        process = subprocess.Popen([sys.executable, "-c", code, str(SCRIPTS), str(self.output)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "LOCKED")
            self.assertTrue(pipeline.lock_active(self.output))
            with self.assertRaises(pipeline.PipelineError):
                with pipeline.OutputLock(self.output):
                    pass
            process.kill()
            process.wait(timeout=10)
            with pipeline.OutputLock(self.output):
                pass
            self.assertFalse(pipeline.lock_active(self.output))
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            process.stdout.close()
            process.stderr.close()


if __name__ == "__main__":
    unittest.main()
