from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.attackpilot import api, settings, store
from app.attackpilot.knowledge import ScopedKnowledge, knowledge_owner
from app.attackpilot.lifecycle import delete_user_tasks
from app.attackpilot.manager import TaskManager
from app.attackpilot.model_history import tool_history
from app.attackpilot.schemas import normalize_modules
from app.schemas_auth import AuthUser

HASH = "0x" + "a" * 64
PAYLOAD = {"name": "Test case", "platform": "Ethereum", "transaction_hash": [HASH], "enabled_modules": ["attack_detection"]}

class TemporaryStore:
    def init_store(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.patches = [patch.object(settings, "DATABASE_PATH", root / "test.sqlite3"), patch.object(settings, "RUNTIME_ROOT", root / "runtime")]
        for item in self.patches: item.start()
        self.addCleanup(self.temp.cleanup)
        for item in self.patches: self.addCleanup(item.stop)

    def demo(self):
        task_id = str(uuid.uuid4())
        seed = {"tasks": [{"task_id": task_id, "dapp_name": "Public sample", "status": "completed", "created_at": store.now(), "final_report": "Public historical report"}], "logs": {task_id: [{"log_id": "demo-log", "agent": "TraceAgent", "message": "public evidence"}]}}
        store.import_seed(seed)
        return task_id, seed

class StoreTest(TemporaryStore, unittest.TestCase):
    def setUp(self): self.init_store()

    def test_user_visibility_and_log_ownership(self):
        own = store.create_task("alice", PAYLOAD)
        other = store.create_task("bob", PAYLOAD)
        demo, _ = self.demo()
        store.append_log(own["task_id"], {"log_id": "shared-name", "message": "alice private"})
        self.assertEqual({t["task_id"] for t in store.list_tasks("alice")}, {own["task_id"], demo})
        self.assertEqual([t["task_id"] for t in store.list_tasks(None)], [demo])
        self.assertIsNone(store.full_log(other["task_id"], "shared-name"))
        self.assertNotIn("owner_id", store.public_task(own))

    def test_final_state_survives_late_completion_and_logs(self):
        task = store.create_task("alice", PAYLOAD); key = task["task_id"]
        self.assertTrue(store.transition(key, "running"))
        store.append_log(key, {"log_id": "first", "message": "evidence"})
        self.assertTrue(store.transition(key, "cancelled", error="user cancelled"))
        self.assertFalse(store.transition(key, "completed", result="late report"))
        store.append_log(key, {"message": "late log"})
        restored = store.get_task(key)
        self.assertEqual(restored["status"], "cancelled")
        self.assertIsNone(restored["final_report"])
        self.assertEqual(len(store.log_page(key)["events"]), 1)

    def test_pagination_and_event_resume(self):
        key = store.create_task("alice", PAYLOAD)["task_id"]
        for index in range(7): store.append_log(key, {"log_id": str(index), "message": f"event {index}"})
        latest = store.log_page(key, 3)
        older = store.log_page(key, 3, before_id=latest["next_before_id"])
        self.assertEqual([log["log_id"] for log in latest["events"]], ["4", "5", "6"])
        self.assertEqual([log["log_id"] for log in older["events"]], ["1", "2", "3"])
        first = store.events_after(key, 0, 3)
        resumed = store.events_after(key, first[-1]["id"])
        self.assertEqual(len(first + resumed), 8)
        self.assertEqual(len({event["id"] for event in first + resumed}), 8)

    def test_full_log_body_survives_summary_truncation(self):
        key = store.create_task("alice", PAYLOAD)["task_id"]
        content = "complete evidence " * 1000
        store.append_log(key, {"log_id": "full", "message": content})
        event = store.log_page(key)["events"][0]
        self.assertTrue(event["is_truncated"])
        self.assertEqual(len(event["message"]), 1000)
        self.assertEqual(store.full_log(key, "full"), content)

    def test_seed_import_is_idempotent_and_never_overwrites_private_task(self):
        demo, seed = self.demo()
        self.assertEqual(store.import_seed(seed)["imported_tasks"], 0)
        self.assertEqual(len(store.log_page(demo)["events"]), 1)
        private = store.create_task("alice", PAYLOAD)
        seed["tasks"][0]["task_id"] = private["task_id"]
        store.import_seed(seed)
        self.assertFalse(store.get_task(private["task_id"])["is_demo"])

    def test_export_and_account_delete_include_only_owned_data(self):
        own = store.create_task("alice", PAYLOAD); other = store.create_task("bob", PAYLOAD)
        demo, _ = self.demo()
        store.append_log(own["task_id"], {"message": "alice evidence"})
        root = store.task_dir(own["task_id"]); root.mkdir(parents=True); (root / "processed.json").write_text("{}")
        exported = store.export_user("alice")
        self.assertEqual([t["task_id"] for t in exported["tasks"]], [own["task_id"]])
        self.assertEqual(len(exported["logs"]), 1)
        self.assertEqual(delete_user_tasks("alice"), 1)
        self.assertIsNone(store.get_task(own["task_id"]))
        self.assertFalse(root.exists())
        self.assertIsNotNone(store.get_task(other["task_id"]))
        self.assertIsNotNone(store.get_task(demo))

    def test_rag_has_no_cross_account_report_leak(self):
        for owner in ("alice", "bob"):
            task = store.create_task(owner, PAYLOAD)
            store.transition(task["task_id"], "completed", result=f"private_unique_evidence {owner} report")
        service = ScopedKnowledge()
        service.public = Mock()
        service.public.search.side_effect = lambda *a, **kw: {"items": [], "total": 0, "index": {}}
        token = knowledge_owner.set("alice")
        try: result = service.search("private_unique_evidence", filters={"owner_id": "bob"})
        finally: knowledge_owner.reset(token)
        self.assertEqual(len(result["items"]), 1)
        self.assertIn("alice", result["items"][0]["content"])
        self.assertNotIn("bob", json.dumps(result))

    def test_packaged_seed_has_valid_complete_log_associations(self):
        seed = json.loads((settings.PACKAGE_ROOT / "data/demo-seed.json").read_text())
        self.assertEqual(seed["unmatched_logs"], 0)
        self.assertEqual(len(seed["tasks"]), 24)
        self.assertEqual(sum(len(logs) for logs in seed["logs"].values()), 615)
        store.import_seed(seed)
        self.assertEqual(len(store.list_tasks(None, True)), 24)

class ApiTest(TemporaryStore, unittest.TestCase):
    def setUp(self):
        self.init_store()
        app = FastAPI(); app.include_router(api.router)
        self.client = TestClient(app)
        self.alice = AuthUser(id="alice", username="alice", display_name="Alice", created_at=store.now())
        self.bob = AuthUser(id="bob", username="bob", display_name="Bob", created_at=store.now())
        self.auth = patch.object(api, "get_user_by_session", side_effect=lambda token: {"alice": self.alice, "bob": self.bob}.get(token))
        self.auth.start(); self.addCleanup(self.auth.stop)
        self.own = store.create_task("alice", PAYLOAD)
        self.other = store.create_task("bob", PAYLOAD)
        self.demo_id, _ = self.demo()

    def login(self, who="alice"): self.client.cookies.set("cryptorisk_session", who)

    def test_public_routes_and_readonly_demo(self):
        for path in ("capabilities", "dapps", "knowledge/vulnerabilities", "knowledge/cases", "knowledge/summary", "rag/status"):
            self.assertEqual(self.client.get("/api/attackpilot/" + path).status_code, 200, path)
        self.assertEqual([task["task_id"] for task in self.client.get("/api/attackpilot/tasks").json()], [self.demo_id])
        self.login()
        self.assertEqual(self.client.post(f"/api/attackpilot/tasks/{self.demo_id}/cancel").status_code, 403)

    def test_private_task_every_read_and_mutation_is_scoped(self):
        self.login()
        key = self.other["task_id"]
        for suffix in ("", "/logs", "/events", "/macro-analysis", "/automated-review", "/agent-log-files", "/agent-log-files/aW52YWxpZA"):
            self.assertEqual(self.client.get(f"/api/attackpilot/tasks/{key}{suffix}").status_code, 404, suffix)
        for suffix in ("cancel", "archive", "unarchive"):
            self.assertEqual(self.client.post(f"/api/attackpilot/tasks/{key}/{suffix}").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/attackpilot/tasks/{key}").status_code, 404)
        self.assertEqual(self.client.get(f"/api/attackpilot/task/{key}/log/shared-name").status_code, 404)
        self.assertEqual(self.client.post("/api/attackpilot/assistant/chat", json={"question": "show report", "task_id": key}).status_code, 404)

    def test_login_required_and_missing_model_is_explicit(self):
        self.assertEqual(self.client.post("/api/attackpilot/tx-review", json={"tx_hash": HASH}).status_code, 401)
        self.login()
        with patch.object(settings, "LLM_API_KEY", ""):
            response = self.client.post("/api/attackpilot/tx-review/deep-analysis", json={"tx_hash": HASH})
        self.assertEqual(response.status_code, 503)
        self.assertIn("DEEPSEEK_API_KEY", response.json()["detail"])

    def test_hash_limits_chain_and_module_validation(self):
        self.login()
        for body in ({"tx_hash": "bad"}, {"tx_hash": HASH, "chain": "unknown"}, {"tx_hashes": [HASH] * 51}, {"tx_hash": HASH, "modules": ["invalid"]}):
            self.assertEqual(self.client.post("/api/attackpilot/tx-review/deep-analysis", json=body).status_code, 422)

    def test_create_deep_task_persists_normalized_payload(self):
        self.login()
        with patch.object(api, "require_capability"):
            response = self.client.post("/api/attackpilot/tx-review/deep-analysis", json={"tx_hash": HASH, "modules": ["patch_verification"]})
        self.assertEqual(response.status_code, 201)
        task = store.get_task(response.json()["task_id"])
        self.assertEqual(task["owner_id"], "alice")
        self.assertEqual(task["payload"]["transaction_hash"], [HASH])
        self.assertEqual(task["enabled_modules"], normalize_modules(["patch_verification"]))

    def test_cancel_archive_delete_lifecycle(self):
        self.login(); key = self.own["task_id"]
        self.assertEqual(self.client.delete(f"/api/attackpilot/tasks/{key}").status_code, 409)
        self.assertEqual(self.client.post(f"/api/attackpilot/tasks/{key}/cancel").status_code, 200)
        self.assertEqual(self.client.post(f"/api/attackpilot/tasks/{key}/archive").status_code, 200)
        self.assertNotIn(key, [task["task_id"] for task in self.client.get("/api/attackpilot/tasks").json()])
        self.assertEqual(self.client.post(f"/api/attackpilot/tasks/{key}/unarchive").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/attackpilot/tasks/{key}").status_code, 200)

    def test_sse_resume_contains_only_new_event_ids(self):
        self.login(); key = self.own["task_id"]
        store.append_log(key, {"message": "evidence"}); store.transition(key, "completed", result="report")
        cursor = store.events_after(key, 0)[1]["id"]
        response = self.client.get(f"/api/attackpilot/tasks/{key}/events", headers={"Last-Event-ID": str(cursor)})
        ids = [int(line.split(": ")[1]) for line in response.text.splitlines() if line.startswith("id: ")]
        self.assertTrue(ids)
        self.assertTrue(all(value > cursor for value in ids))
        self.assertEqual(response.headers["x-accel-buffering"], "no")

    def test_public_rag_rebuild_requires_admin(self):
        self.login()
        self.assertEqual(self.client.post("/api/attackpilot/rag/rebuild").status_code, 403)

    def test_completed_live_task_report_shape_and_macro_do_not_reuse_demo_cache(self):
        self.login(); key = self.own["task_id"]
        store.transition(key, "completed", result="private report")
        response = self.client.get(f"/api/attackpilot/tasks/{key}/automated-review")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(f"/api/attackpilot/tasks/{key}/macro-analysis").status_code, 404)

    def test_external_rpc_failure_is_not_reported_as_successful_live_observation(self):
        self.login()
        with patch.object(api, "require_capability"), patch.object(api.reference, "_load_tx_observation", AsyncMock(return_value={"status": "unavailable", "errors": ["RPC request timed out"]})):
            response = self.client.post("/api/attackpilot/tx-review", json={"tx_hash": HASH})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["live_observation_status"], "unavailable")

    def test_known_case_hash_is_never_matched_on_the_wrong_chain(self):
        self.login()
        with patch.object(api, "require_capability"), patch.object(api.reference, "_find_raw_tx_matches", return_value=[{"name": "Ethereum example", "platform": "Ethereum"}]), patch.object(api.reference, "_find_generated_case_matches", return_value=[]), patch.object(api.reference, "_load_tx_observation", AsyncMock(return_value={"status": "unavailable"})):
            response = self.client.post("/api/attackpilot/tx-review", json={"tx_hash": HASH, "chain": "bnbchain"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["matched_cases"], [])

class WorkflowTest(TemporaryStore, unittest.IsolatedAsyncioTestCase):
    def setUp(self): self.init_store()

    async def test_restart_marks_interrupted_tasks_and_new_queue_runs(self):
        previous = store.create_task("alice", PAYLOAD)
        manager = TaskManager()
        seen = []
        async def fake_run(task):
            seen.append(task["task_id"])
            store.transition(task["task_id"], "completed", result="test report")
        with patch.object(manager, "_run", side_effect=fake_run):
            await manager.start()
            self.assertEqual(store.get_task(previous["task_id"])["status"], "failed")
            task = store.create_task("alice", PAYLOAD)
            try:
                for _ in range(20):
                    if task["task_id"] in seen: break
                    await asyncio.sleep(.1)
                self.assertIn(task["task_id"], seen)
            finally: await manager.stop()

    async def test_cancelled_child_process_is_reaped(self):
        process = await asyncio.create_subprocess_exec(sys.executable, "-c", "import time; time.sleep(60)", start_new_session=True)
        await TaskManager()._terminate(process)
        self.assertIsNotNone(process.returncode)

    async def test_cancel_terminates_tools_in_separate_sessions(self):
        root = Path(self.temp.name)
        code = "import subprocess,sys,time,pathlib; child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],start_new_session=True); pathlib.Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(60)"
        process = await asyncio.create_subprocess_exec(sys.executable, "-c", code, str(root / "child.pid"), env={**os.environ, "ATTACKPILOT_WORK_DIR": str(root)}, start_new_session=True)
        try:
            for _ in range(40):
                if (root / "child.pid").exists(): break
                await asyncio.sleep(.05)
            child_pid = int((root / "child.pid").read_text())
            self.assertIn(child_pid, TaskManager._task_groups(root))
            await TaskManager()._terminate(process, root)
            for _ in range(40):
                stat = Path(f"/proc/{child_pid}/stat")
                if not stat.exists() or stat.read_text().split(") ")[1].startswith("Z"): break
                await asyncio.sleep(.05)
            else: self.fail("Separate-session tool survived cancellation")
        finally:
            await TaskManager()._terminate(process, root)

    async def test_default_queue_runs_only_one_task_at_a_time(self):
        manager = TaskManager(); release = asyncio.Event(); active = []
        async def fake_run(task):
            store.transition(task["task_id"], "running"); active.append(task["task_id"])
            await release.wait()
            store.transition(task["task_id"], "completed", result="report")
        with patch.dict(os.environ, {"ATTACKPILOT_MAX_TASKS": "1"}), patch.object(manager, "_run", side_effect=fake_run):
            await manager.start()
            first = store.create_task("alice", PAYLOAD); second = store.create_task("alice", PAYLOAD)
            try:
                for _ in range(20):
                    if active: break
                    await asyncio.sleep(.1)
                self.assertEqual(active, [first["task_id"]])
                self.assertEqual(store.get_task(second["task_id"])["status"], "pending")
            finally:
                release.set(); await manager.stop()

    async def test_compile_only_patch_never_calls_tenderly(self):
        from app.attackpilot.agents.FixAgent import FixAgent
        agent = FixAgent.__new__(FixAgent)
        agent._check_cancelled = Mock()
        agent.process_fix_report = Mock(return_value=(True, {"faulty_functions": []}))
        agent.get_format_contracts = Mock(return_value="source")
        agent._load_compile_result = AsyncMock(return_value={})
        agent._load_runtime_bytecode = AsyncMock(return_value={})
        agent.metrics_collector = None
        agent.query = AsyncMock(return_value="patch content")
        agent._update_contracts_with_patch = Mock(return_value={})
        agent.compile_patched_codes = AsyncMock(return_value=(True, {}))
        agent.prepare_bundle_data = AsyncMock(side_effect=AssertionError("Unexpected Tenderly request"))
        agent._deploy_contracts = AsyncMock(side_effect=AssertionError("Unexpected deployment"))
        agent.run_patch_verification_from_tenderly = AsyncMock(side_effect=AssertionError("Unexpected replay"))
        with patch("app.attackpilot.agents.FixAgent.SolidityCodePatcher") as patcher:
            patcher.return_value.apply_patches.return_value = (True, "", {})
            result = await agent.handle({}, verify=False)
        self.assertTrue(result[0]); self.assertIn("not requested", result[1])
        agent.prepare_bundle_data.assert_not_called(); agent._deploy_contracts.assert_not_called(); agent.run_patch_verification_from_tenderly.assert_not_called()

    async def test_unverified_patch_report_never_gets_verified_heading(self):
        from app.attackpilot.agents.GlobalMemoryAgent import GlobalMemoryAgent
        agent = GlobalMemoryAgent.__new__(GlobalMemoryAgent)
        agent.query = AsyncMock(return_value="Root cause report")
        agent._serialize_memory_for_prompt = Mock(return_value="context")
        for verdict in ("PATCH_GENERATED", "UNVERIFIED", "INEFFECTIVE_PATCH"):
            result = await agent.get_final_result({"verdict": verdict, "reason": "not verified"}, {}, "", "patch")
            self.assertIn("Applied Patches (Unverified)", result)
            self.assertNotIn("Applied Patches (Verified)", result)

    async def test_mock_worker_persists_complete_report_and_full_logs(self):
        from app.attackpilot import worker
        task = store.create_task("alice", PAYLOAD); key = task["task_id"]
        store.transition(key, "running")
        report = {"report": "offline report", "time": {"total": 1}, "verification": {"status": "skipped"}}
        mock_workflow = Mock(last_result=report, process_single_dapp=AsyncMock(return_value=("Test case", "offline report")))
        with patch("app.attackpilot.workflow.WorkFlow", return_value=mock_workflow), patch.object(settings, "prepare_work_dir"), patch.object(settings, "WORK_ROOT", Path(self.temp.name)):
            await worker.run(key)
        self.assertEqual(store.get_task(key)["status"], "completed")
        self.assertEqual(store.get_task(key)["result"], report)

class ModelHistoryTest(unittest.TestCase):
    def test_tool_pair_and_reasoning_content_survive_trimming(self):
        messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "old" * 1000}, {"role": "assistant", "content": "", "reasoning_content": "reasoning state", "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "trace", "arguments": "{}"}}]}, {"role": "tool", "tool_call_id": "call-1", "content": "evidence"}, {"role": "user", "content": "continue"}]
        result = tool_history(messages, 900, len)
        self.assertEqual([item["role"] for item in result], ["system", "assistant", "tool", "user"])
        self.assertEqual(result[1]["reasoning_content"], "reasoning state")
        self.assertEqual(messages[1]["content"], "old" * 1000)

    def test_module_dependencies_are_complete(self):
        self.assertEqual(set(normalize_modules(["patch_verification"])), {"attack_detection", "fault_localization", "rag_retrieval", "patch_generation", "patch_verification"})
        self.assertNotIn("patch_verification", normalize_modules(["patch_generation"]))

    def test_task_cancellation_uses_separate_mutation_quota(self):
        from app.services.rate_limit_service import check_rate_limit, reset_rate_limit_state
        reset_rate_limit_state()
        with patch.dict(os.environ, {"API_RATE_LIMIT_ENABLED": "1", "AGENT_RATE_LIMIT_PER_5_MINUTES": "1"}):
            self.assertTrue(check_rate_limit(identity="ap-test", path="/api/attackpilot/tasks", method="POST").allowed)
            self.assertFalse(check_rate_limit(identity="ap-test", path="/api/attackpilot/tasks", method="POST").allowed)
            self.assertTrue(check_rate_limit(identity="ap-test", path="/api/attackpilot/tasks/uuid/cancel", method="POST").allowed)
        reset_rate_limit_state()

if __name__ == "__main__": unittest.main()
