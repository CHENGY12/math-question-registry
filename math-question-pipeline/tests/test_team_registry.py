"""Concurrent registry checks against temporary local bare remotes, never real accounts."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import team_registry as registry


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="registry-tests-")
        self.root = Path(self.temporary.name)
        self.remote = self.root / "remote.git"
        subprocess.run(["git", "init", "--bare", "--quiet", str(self.remote)], check=True, capture_output=True)
        self.assertEqual(registry.initialize(str(self.remote), registry.DEFAULT_BRANCH)["result"], "READY")

    def tearDown(self):
        self.temporary.cleanup()

    def request(self, ids, batch="batch-a", token=None):
        request = {"owner": "agent-a", "account_id": "shared-account", "batch_id": batch,
                   "questions": [{"platform": "xkw", "subject": "gzsx", "question_id": str(qid)} for qid in ids]}
        if token:
            request["claim_token"] = token
        return request

    def transact(self, action, request, **kwargs):
        return registry.transact(str(self.remote), registry.DEFAULT_BRANCH, action, request, **kwargs)

    def records(self):
        return registry.status(str(self.remote), registry.DEFAULT_BRANCH)["records"]

    def concurrent(self, first, second):
        barrier = threading.Barrier(2)
        def before_push(attempt):
            if attempt == 1:
                barrier.wait(timeout=10)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.transact, "claim", request, before_push=before_push) for request in [first, second]]
            return [future.result(timeout=30) for future in futures]

    def test_two_agents_racing_for_same_question_only_one_wins(self):
        results = self.concurrent(self.request([1], "batch-a"), self.request([1], "batch-b"))
        self.assertEqual(sorted(r["result"] for r in results), ["COMMITTED", "CONFLICT"])
        self.assertEqual(sum(r["download_permitted"] for r in results), 1)
        self.assertEqual(len(self.records()), 1)

    def test_nonoverlapping_race_rechecks_new_head_and_both_commit(self):
        results = self.concurrent(self.request([1], "batch-a"), self.request([2], "batch-b"))
        self.assertEqual([r["result"] for r in results], ["COMMITTED", "COMMITTED"])
        self.assertEqual(sorted(r["attempts"] for r in results), [1, 2])
        self.assertEqual(len(self.records()), 2)

    def test_hundred_question_claim_is_atomic_on_conflict(self):
        self.transact("claim", self.request([50], "prior-batch"))
        result = self.transact("claim", self.request(range(1, 101)))
        self.assertEqual(result["result"], "CONFLICT")
        self.assertEqual([r["question_id"] for r in result["conflicts"]], ["50"])
        self.assertEqual([r["question_id"] for r in self.records()], ["50"])
        success = self.transact("claim", self.request(range(101, 201), "full-batch"))
        self.assertTrue(success["download_permitted"])
        self.assertEqual(len(self.records()), 101)

    def test_downloading_cannot_be_released_or_overwritten_by_other_batch(self):
        claimed = self.transact("claim", self.request([1, 2]))
        own = self.request([1], token=claimed["claim_token"])
        self.assertEqual(self.transact("transition", {**own, "to_state": "downloading"})["result"], "COMMITTED")
        release = self.transact("release", self.request([1, 2], token=claimed["claim_token"]))
        self.assertEqual(release["result"], "CONFLICT")
        self.assertEqual({r["question_id"]: r["state"] for r in self.records()}, {"1": "downloading", "2": "reserved"})
        self.assertEqual(self.transact("claim", self.request([1], "different-batch"))["result"], "CONFLICT")
        self.assertEqual(self.transact("release", self.request([2], token=claimed["claim_token"]))["result"], "COMMITTED")
        self.assertEqual(self.transact("claim", self.request([2], "next-batch"))["result"], "COMMITTED")

    def test_seed_five_and_archive_requires_explicit_batch_confirmation(self):
        request = self.request(range(1, 6), "existing-five")
        seeded = self.transact("seed", {**request, "details": {"source_sha256": "a" * 64, "local_status": "source_received"}})
        self.assertEqual(seeded["result"], "COMMITTED")
        own = {**request, "claim_token": seeded["claim_token"]}
        with self.assertRaises(registry.RegistryError):
            self.transact("transition", {**own, "to_state": "local_ready", "details": {"source_sha256": "b" * 64, "local_status": "ready"}})
        self.transact("transition", {**own, "to_state": "local_ready", "details": {"local_status": "ready", "validation_sha256": "b" * 64}})
        with self.assertRaises(registry.RegistryError):
            self.transact("transition", {**own, "to_state": "archived"})
        archived = self.transact("transition", {**own, "to_state": "archived", "details": {
            "artifact_key": "existing-five-archive-v1", "archive_manifest_sha256": "c" * 64, "cloud_confirmed": True}})
        self.assertEqual(archived["result"], "COMMITTED")
        self.assertEqual({r["state"] for r in self.records()}, {"archived"})
        self.assertFalse(archived["download_permitted"])

    def test_accepted_push_with_lost_response_is_confirmed_by_remote(self):
        original = registry.GitStore.commit_push
        def accepted_but_lost(store, message):
            result = original(store, message)
            self.assertEqual(result.returncode, 0)
            raise subprocess.TimeoutExpired("redacted", 1)
        with patch.object(registry.GitStore, "commit_push", accepted_but_lost):
            result = self.transact("claim", self.request([1]))
        self.assertEqual(result["result"], "CONFIRMED_AFTER_PUSH_ERROR")
        self.assertTrue(result["download_permitted"])
        self.assertEqual(self.records()[0]["claim_token"], result["claim_token"])

    def test_unknown_push_and_unavailable_fetch_never_authorizes_download(self):
        original_fetch = registry.GitStore.fetch
        calls = []
        def fail_later(store, *args, **kwargs):
            calls.append(1)
            if len(calls) > 1:
                raise registry.GitError("fetch", 128)
            return original_fetch(store, *args, **kwargs)
        with patch.object(registry.GitStore, "commit_push", side_effect=subprocess.TimeoutExpired("redacted", 1)), \
                patch.object(registry.GitStore, "fetch", fail_later):
            result = self.transact("claim", self.request([1]))
        self.assertEqual(result["result"], "UNKNOWN_PUSH_OUTCOME")
        self.assertFalse(result["download_permitted"])
        self.assertEqual(self.records(), [])

    def test_claim_idempotency_and_public_field_allowlist(self):
        request = self.request([1], token="retry-token")
        self.transact("claim", request)
        self.assertEqual(self.transact("claim", request)["result"], "ALREADY_APPLIED")
        for bad in [
            {**request, "owner": "person@example.com"},
            {**request, "details": {"source_file": "/private/machine/path.docx"}},
            {**request, "details": {"drive_url": "https://drive.google.com/private"}},
            {**request, "questions": [{"platform": "xkw", "subject": "another-alias", "question_id": "1"}]},
            {**request, "questions": [{"platform": "xkw", "subject": "gzsx", "question_id": "01"}]},
        ]:
            with self.assertRaises(registry.RegistryError):
                self.transact("claim", bad)
        self.assertEqual(len(self.records()), 1)

    def test_inherited_git_environment_cannot_modify_a_user_repository(self):
        user = self.root / "unrelated-user-project"
        subprocess.run(["git", "init", "--quiet", str(user)], check=True, capture_output=True)
        config = user / ".git/config"
        original = config.read_bytes()
        with patch.dict(os.environ, {"GIT_DIR": str(user / ".git"), "GIT_WORK_TREE": str(user)}):
            result = self.transact("claim", self.request([1]))
        self.assertEqual(result["result"], "COMMITTED")
        self.assertEqual(config.read_bytes(), original)
        self.assertFalse((user / "questions").exists())


if __name__ == "__main__":
    unittest.main()
