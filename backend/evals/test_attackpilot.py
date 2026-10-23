from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.attackpilot import api, settings, store
from app.attackpilot.demo_catalog import RETIRED_DEMO_TASK_IDS
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

    def test_seed_import_retires_only_selected_archive_demos_and_cascades(self):
        unrelated, _ = self.demo()
        retained_file = store.task_dir(unrelated) / "agent-logs" / "TraceAgent.log"
        retained_file.parent.mkdir(parents=True)
        retained_file.write_text("public evidence")
        old_seed = {"tasks": [], "logs": {}}
        with store.connection() as db:
            for task_id in RETIRED_DEMO_TASK_IDS:
                retired_file = store.task_dir(task_id) / "agent-logs" / "TraceAgent.log"
                retired_file.parent.mkdir(parents=True)
                retired_file.write_text("retired evidence")
                task = {"task_id": task_id, "dapp_name": "Retired public sample", "status": "completed", "created_at": store.now(), "final_report": "Retired report"}
                old_seed["tasks"].append(task)
                old_seed["logs"][task_id] = [{"log_id": "retired-log", "message": "retired evidence"}]
                # Simulate records imported by an earlier release, including archived rows.
                db.execute("INSERT INTO tasks(task_id,is_demo,dapp_name,status,archived,created_at,final_report,source) VALUES (?,1,?,'completed',1,?,?,'archive')", (task_id, task["dapp_name"], task["created_at"], task["final_report"]))
                db.execute("INSERT INTO logs(task_id,log_id,message,full_content) VALUES (?,'retired-log','retired evidence','retired evidence')", (task_id,))
                db.execute("INSERT INTO events(task_id,payload) VALUES (?,?)", (task_id, json.dumps({"type": "TASK_FINAL", "task_id": task_id})))
                db.execute("INSERT INTO report_translations(task_id,source_hash,language,translated_report,model,translated_at) VALUES (?,'hash','zh-CN','旧译文','test',?)", (task_id, store.now()))

        # Even an old seed must neither restore the task nor its dependent records.
        for _ in range(2):
            self.assertEqual(store.import_seed(old_seed)["imported_tasks"], 0)
            self.assertEqual([task["task_id"] for task in store.list_tasks(None, True)], [unrelated])
            with store.connection() as db:
                for task_id in RETIRED_DEMO_TASK_IDS:
                    self.assertFalse(store.task_dir(task_id).exists())
                    self.assertIsNone(db.execute("SELECT task_id FROM tasks WHERE task_id=?", (task_id,)).fetchone())
                    for table in ("logs", "events", "report_translations"):
                        self.assertEqual(db.execute(f"SELECT count(*) FROM {table} WHERE task_id=?", (task_id,)).fetchone()[0], 0)
        self.assertEqual(store.full_log(unrelated, "demo-log"), "public evidence")
        self.assertEqual(retained_file.read_text(), "public evidence")

    def test_retired_demo_ids_never_delete_same_id_private_tasks(self):
        old_seed = {"tasks": [], "logs": {}}
        originals = {}
        for task_id in RETIRED_DEMO_TASK_IDS:
            with patch.object(store.uuid, "uuid4", return_value=uuid.UUID(task_id)):
                store.create_task("alice", PAYLOAD)
            store.append_log(task_id, {"log_id": "private-log", "message": "private evidence"})
            store.transition(task_id, "completed", result="Private report")
            private_file = store.task_dir(task_id) / "private-evidence.txt"
            private_file.parent.mkdir(parents=True)
            private_file.write_text("private evidence")
            originals[task_id] = store.get_task(task_id)
            old_seed["tasks"].append({"task_id": task_id, "dapp_name": "Retired public sample", "status": "completed", "created_at": store.now(), "final_report": "Retired report"})
            old_seed["logs"][task_id] = [{"log_id": "retired-log", "message": "retired evidence"}]

        for _ in range(2):
            self.assertEqual(store.import_seed(old_seed)["imported_tasks"], 0)
            for task_id, original in originals.items():
                self.assertEqual(store.get_task(task_id), original)
                self.assertEqual(store.full_log(task_id, "private-log"), "private evidence")
                self.assertIsNone(store.full_log(task_id, "retired-log"))
                self.assertEqual(len(store.events_after(task_id, 0)), 3)
                self.assertEqual((store.task_dir(task_id) / "private-evidence.txt").read_text(), "private evidence")

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
        self.assertEqual(RETIRED_DEMO_TASK_IDS, {"d3b80eaa-2dea-492a-9727-588b346e99be", "b38e5109-36c2-43ad-a2aa-cead703697f3"})
        self.assertEqual(seed["unmatched_logs"], 0)
        self.assertEqual(len(seed["tasks"]), 22)
        self.assertEqual(sum(len(logs) for logs in seed["logs"].values()), 550)
        task_ids = {task["task_id"] for task in seed["tasks"]}
        self.assertFalse(task_ids & RETIRED_DEMO_TASK_IDS)
        self.assertFalse(set(seed["logs"]) & RETIRED_DEMO_TASK_IDS)
        self.assertTrue({"0b53f3ab-ff2b-4eed-8703-c9347927c62c", "a3c56880-4b5e-49da-a96a-1499d8ea2554"} <= task_ids)
        store.import_seed(seed)
        self.assertEqual(len(store.list_tasks(None, True)), 22)

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
        payloads = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        self.assertEqual(sum(item.get("type") == "TASK_FINAL" for item in payloads), 1)
        resumed = self.client.get(f"/api/attackpilot/tasks/{key}/events", headers={"Last-Event-ID": str(ids[-1])})
        self.assertIn('"type": "TASK_FINAL"', resumed.text)

    def test_public_rag_rebuild_requires_admin(self):
        self.login()
        self.assertEqual(self.client.post("/api/attackpilot/rag/rebuild").status_code, 403)

    def test_sse_first_final_contains_latest_evidence_revision(self):
        self.login(); key = self.own['task_id']
        store.transition(key, 'completed', result='old report')
        with store.connection() as db:
            db.execute('UPDATE tasks SET final_report=?,result=? WHERE task_id=?',
                       ('revised report', json.dumps({'report': 'revised report'}), key))
            store._event(db, key, {'type': 'TASK_FINAL', 'task_id': key, 'status': 'completed', 'final_report': 'revised report'})
        response = self.client.get(f'/api/attackpilot/tasks/{key}/events')
        finals = [json.loads(line[6:]) for line in response.text.splitlines()
                  if line.startswith('data: ') and json.loads(line[6:]).get('type') == 'TASK_FINAL']
        self.assertEqual(len(finals), 1)
        self.assertEqual(finals[0]['final_report'], 'revised report')
        self.assertEqual(finals[0]['result']['report'], 'revised report')

    def test_completed_live_task_report_shape_and_macro_do_not_reuse_demo_cache(self):
        self.login(); key = self.own["task_id"]
        store.transition(key, "completed", result="private report")
        response = self.client.get(f"/api/attackpilot/tasks/{key}/automated-review")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(f"/api/attackpilot/tasks/{key}/macro-analysis").status_code, 404)

    def test_report_reads_and_historical_events_validate_the_same_evidence(self):
        from evals.test_attackpilot_failures import ReplayEvidenceRegressionTests
        fixture = ReplayEvidenceRegressionTests()
        fixture.setUp()
        replay = fixture.report()
        original = {'report': 'Historical analysis body', 'applied_patches': fixture.patches,
                    'replay_evidence': replay, 'verification': fixture.adjudicate(replay)}
        self.assertEqual(original['verification']['status'], 'verified')
        self.login()
        for variant in ('valid', 'old_unbound', 'changed_replay', 'changed_patch'):
            with self.subTest(variant=variant):
                result = deepcopy(original)
                if variant == 'old_unbound':
                    result['verification'].pop('replay_evidence_sha256')
                elif variant == 'changed_replay':
                    result['replay_evidence']['transactions'][0]['patched']['gas_used'] += 1
                elif variant == 'changed_patch':
                    result['applied_patches'] += '\n// changed after verification'
                key = store.create_task('alice', PAYLOAD)['task_id']
                store.transition(key, 'completed', result=result)
                persisted = store.get_task(key)
                # Simulate a TASK_FINAL persisted before response normalization.
                event = {**persisted, 'type': 'TASK_FINAL'}
                event.pop('payload'); event.pop('owner_id')
                with store.connection() as db:
                    db.execute('UPDATE events SET payload=? WHERE task_id=? AND json_extract(payload, "$.type")="TASK_FINAL"', (json.dumps(event), key))
                detail = self.client.get(f'/api/attackpilot/tasks/{key}').json()
                listing = next(item for item in self.client.get('/api/attackpilot/tasks').json() if item['task_id'] == key)
                streamed = self.client.get(f'/api/attackpilot/tasks/{key}/events').text
                final = next(json.loads(line[6:]) for line in streamed.splitlines()
                             if line.startswith('data: ') and json.loads(line[6:]).get('type') == 'TASK_FINAL')
                for response in (detail, listing, final):
                    state = response['result']['verification']
                    self.assertEqual(state['status'], 'verified' if variant == 'valid' else 'unverified')
                    self.assertEqual(state['dimensions']['normal_regression']['status'], 'not_run')
                    self.assertIsNone(state['dimensions']['profit']['usd'])
                    self.assertEqual(response['final_report'], original['report'])
                self.assertEqual(store.get_task(key), persisted)

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

class ObservationTest(unittest.IsolatedAsyncioTestCase):
    async def test_rpc_observation_rejects_mixed_blocks_and_unbound_trace(self):
        sender, target = '0x' + '1' * 40, '0x' + '2' * 40
        identity = {'blockHash': '0x' + 'b' * 64, 'blockNumber': '0x10', 'transactionIndex': '0x0'}
        payloads = {
            'eth_getTransactionByHash': {**identity, 'hash': HASH, 'from': sender, 'to': target, 'input': '0x', 'value': '0x0'},
            'eth_getTransactionReceipt': {**identity, 'transactionHash': HASH, 'status': '0x1', 'gasUsed': '0x5208', 'logs': []},
            'debug_traceTransaction': {'type': 'CALL', 'from': sender, 'to': target, 'input': '0x', 'value': '0x0'},
        }
        cases = [
            (None, None, None, 'ok'),
            ('eth_getTransactionReceipt', 'blockHash', '0x' + 'c' * 64, 'unavailable'),
            ('eth_getTransactionReceipt', 'transactionIndex', '0x1', 'unavailable'),
            ('eth_getTransactionReceipt', 'gasUsed', None, 'partial'),
            ('debug_traceTransaction', 'to', sender, 'partial'),
            ('debug_traceTransaction', 'type', 'UNSUPPORTED', 'partial'),
        ]
        for method, field, value, expected in cases:
            with self.subTest(method=method, field=field):
                responses = deepcopy(payloads)
                if method:
                    responses[method][field] = value
                def respond(request):
                    body = json.loads(request.content)
                    return httpx.Response(200, json={'jsonrpc': '2.0', 'id': body['id'], 'result': responses[body['method']]})
                client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
                with patch.object(api.reference, 'JSONRPCS', {'Ethereum': ['https://rpc.invalid']}), patch('httpx.AsyncClient', return_value=client):
                    observation = await api.reference._load_tx_observation(HASH, 'ethereum')
                self.assertEqual(observation['status'], expected)
                signals, metrics = api.reference._analyze_tx_observation(observation)
                if expected != 'ok':
                    self.assertTrue(observation['errors'])
                    self.assertNotEqual(api.reference._risk_from_signals(signals, False, expected), 'low')
                if expected == 'unavailable':
                    self.assertEqual(metrics['trace_call_count'], 0)
                    self.assertIsNone(metrics['receipt_status'])

    async def test_missing_batch_observations_stay_unknown(self):
        request = api.TxDetectRequest(tx_hashes=[HASH, '0x' + 'b' * 64])
        with patch.object(api.reference, '_matches_on_chain', return_value=[]), patch.object(api.reference, '_load_tx_observation', AsyncMock(return_value={'status': 'unavailable', 'errors': ['RPC unavailable']})):
            result = await api.reference.detect_transaction_set(request)
        self.assertEqual(result.risk_level, 'unknown')
        self.assertEqual(result.analyzed_count, 2)
        self.assertTrue(all(item.risk_level == 'unknown' for item in result.auxiliary_candidates))
        self.assertTrue(all('数据不足' in item.summary for item in result.auxiliary_candidates))
        self.assertEqual(set(result.recommended_tx_hashes), set(request.tx_hashes))

    async def test_integer_revert_status_keeps_failure_signal(self):
        signals, metrics = api.reference._analyze_tx_observation({'status': 'partial', 'receipt': {'status': 0}})
        self.assertEqual(metrics['receipt_status'], '0x0')
        self.assertIn('reverted_tx', [signal['id'] for signal in signals])


class WorkflowTest(TemporaryStore, unittest.IsolatedAsyncioTestCase):
    def setUp(self): self.init_store()

    async def test_restart_marks_interrupted_tasks_and_new_queue_runs(self):
        previous = store.create_task("alice", PAYLOAD)
        store.transition(previous["task_id"], "running")
        queued = store.create_task("alice", PAYLOAD)
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
                self.assertIn(queued["task_id"], seen)
                self.assertEqual(store.get_task(queued["task_id"])["status"], "completed")
            finally: await manager.stop()

    async def test_waiting_api_process_takes_over_queue_lock(self):
        leader, follower = TaskManager(), TaskManager()
        seen = []
        async def fake_run(task):
            seen.append(task["task_id"])
            store.transition(task["task_id"], "completed", result="report")
        with patch.object(follower, "_run", side_effect=fake_run):
            try:
                await leader.start()
                await follower.start()
                self.assertIsNotNone(follower.scheduler)
                await leader.stop()
                queued = store.create_task("alice", PAYLOAD)
                async with asyncio.timeout(5):
                    while queued["task_id"] not in seen:
                        await asyncio.sleep(.05)
                self.assertEqual(store.get_task(queued["task_id"])["status"], "completed")
            finally:
                await follower.stop()
                await leader.stop()

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
        agent.session_id = "session"
        agent.mcp_client = Mock()
        address, uid = "0x" + "1" * 40, "0x" + "1" * 40 + "::Contract.sol"
        agent.mcp_client.call_tool = AsyncMock(return_value={
            "address": address, "file_index": 0,
            "contract_info": [{"id": 0, "path": "Contract.sol", "source": "contract Before {}"}],
        })
        agent.process_fix_report = Mock(return_value=(True, {"faulty_functions": [
            {"trigger_point": {"transaction_hash": HASH, "index": 0}},
        ]}))
        agent.get_format_contracts = Mock(return_value="source")
        agent._load_compile_result = AsyncMock(return_value={})
        agent._load_runtime_bytecode = AsyncMock(return_value={})
        agent.metrics_collector = None
        agent.query = AsyncMock(return_value="patch content")
        agent._update_contracts_with_patch = Mock(return_value={address: Mock()})
        agent.compile_patched_codes = AsyncMock(return_value=(True, {address: Mock()}))
        agent.prepare_bundle_data = AsyncMock(side_effect=AssertionError("Unexpected Tenderly request"))
        agent._deploy_contracts = AsyncMock(side_effect=AssertionError("Unexpected deployment"))
        agent.run_patch_verification_from_tenderly = AsyncMock(side_effect=AssertionError("Unexpected replay"))
        with patch("app.attackpilot.agents.FixAgent.SolidityCodePatcher") as patcher:
            patcher.return_value.apply_patches.return_value = (True, "", {uid: "contract After {}"})
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
            self.assertIn("Applied Patches（实际应用补丁）", result)
            self.assertNotIn("Applied Patches (Verified)", result)

    async def test_mock_worker_persists_complete_report_and_full_logs(self):
        from app.attackpilot import worker
        task = store.create_task("alice", PAYLOAD); key = task["task_id"]
        store.transition(key, "running")
        from app.attackpilot.workflow import REPORT_POLICY_VERSION, request_fingerprint
        report = {"report": "offline report", "time": {"total": 1}, "verification": {"status": "skipped"},
                  "report_policy_version": REPORT_POLICY_VERSION, "request_fingerprint": request_fingerprint(PAYLOAD),
                  "enabled_modules": ['attack_detection'], 'baseline_validation': {'transactions': {HASH: {
                      'schema_version': 1, 'status': 'validated', 'method': 'rpc_receipt_vs_tenderly_original_replay',
                      'original_transaction_hash': HASH, 'network_id': '1', 'block_number': 1,
                      'transaction_index': 0, 'gas_used': 21000, 'log_count': 0, 'receipt_status': 1,
                      'block_hash': '0x' + 'b' * 64, 'ordered_logs_sha256': 'c' * 64, 'receipt_digest': 'd' * 64,
                  }}}}
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

class HistoricalPriceRegressionTest(unittest.IsolatedAsyncioTestCase):
    """Exercise public valuation entry points with offline provider responses."""

    WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
    BLOCK = "0x" + "b" * 64
    TIMESTAMP = 1_506_000_000

    @staticmethod
    def _client(respond, before_read=None):
        class Response:
            status = 200

            def __init__(self, request):
                self.request, self.content, self.consumed = request, self, False

            async def __aenter__(self): return self
            async def __aexit__(self, *args): return False

            async def read(self, size):
                if self.consumed:
                    return b""
                if before_read is not None:
                    await before_read(self.request)
                self.consumed = True
                return json.dumps(respond(self.request)).encode()

        class Client:
            def __init__(self): self.requests = []
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return False

            def post(self, url, *, json, **kwargs):
                self.requests.append(json)
                return Response(json)

        return Client()

    async def test_transaction_details_reach_graph_and_role_price_readers(self):
        from app.attackpilot.agents.TxRoleAgent import TxRoleAgent
        from app.attackpilot.process.pyg import DAppProcess
        from app.attackpilot.process.fund_graph import FundFlowGraphBuilder
        from app.attackpilot.utils import chainlink, price
        from app.attackpilot.utils.balance_utils import NATIVE_TOKEN_ADDRESS

        hashes = [HASH, "0x" + "c" * 64]
        details = {
            tx: {"hash": tx, "block_number": 500_000 + index,
                 "block_hash": "0x" + format(500_000 + index, "064x"),
                 "transaction_index": index, "timestamp": self.TIMESTAMP + index * 12,
                 "balance_diff": [{"address": "0x" + "d" * 40, "original": "0", "dirty": str(10 ** 18)}]}
            for index, tx in enumerate(hashes)
        }
        process = DAppProcess({}, {}, None)
        role = TxRoleAgent.__new__(TxRoleAgent)
        role._platform, role.NATIVE_TOKEN_ADDRESS = "Ethereum", NATIVE_TOKEN_ADDRESS
        oracle = AsyncMock(return_value={"status": "available", "price": 2000,
                                        "timestamp": self.TIMESTAMP - 12})
        with patch.object(process, "_load_transaction_time", AsyncMock(return_value={
            item["block_number"]: item["timestamp"] for item in details.values()
        })), patch.object(chainlink, "get_chainlink_price", oracle), patch.object(
            price, "_get_defillama_price", AsyncMock(return_value={})
        ):
            transactions, ordered = await process.format_transactions(
                "Ethereum", details, {tx: item["balance_diff"] for tx, item in details.items()}, {}
            )
            async with price.price_quote_scope():
                graph = await FundFlowGraphBuilder("Ethereum").add_transactions(transactions)
                balances = await role.get_balance_change({
                    "transaction_hash_list": hashes, "transaction_to_detail": details,
                    "dapp": {"platform": "Ethereum"},
                }, transactions)
        self.assertEqual(ordered, hashes)
        self.assertEqual(set(balances), set(hashes))
        self.assertEqual([edge["dollar_value"] for *_, edge in graph.edges(data=True)], [2000, 2000])
        self.assertEqual(oracle.await_count, 2)
        expected = [
            {"number": item["block_number"], "hash": item["block_hash"], "timestamp": item["timestamp"]}
            for item in details.values()
        ]
        self.assertEqual([call.kwargs["block_context"] for call in oracle.await_args_list], expected)

    async def test_missing_or_invalid_block_hash_never_becomes_transaction_hash(self):
        from app.attackpilot.utils import chainlink, price

        oracle = AsyncMock(return_value={"status": "unavailable", "reason": "rpc_timeout"})
        with patch.object(chainlink, "get_chainlink_price", oracle), patch.object(
            price, "_get_defillama_price", AsyncMock(return_value={})
        ):
            for block_hash in (None, "", "0x123", HASH + "0"):
                with self.subTest(block_hash=block_hash):
                    await price.get_token_price(f"ethereum:{self.WETH}", self.TIMESTAMP, block_context={
                        "hash": HASH, "block_number": 500_000, "block_hash": block_hash,
                        "timestamp": self.TIMESTAMP,
                    })
                    self.assertNotIn("block_context", oracle.await_args.kwargs)

    async def _archive_quote(self, *, hint=False, same_second=False, ambiguous=False, mismatch=False):
        from app.attackpilot.utils import chainlink
        from app.attackpilot.utils.chainlink_config import DEFAULT_FEEDS

        requested, target, latest = self.TIMESTAMP, 500_000, 1_000_000
        aggregator = "0x" + "d" * 40
        round_id = (1 << 64) + 25
        def words(*items): return "0x" + "".join(format(item, "064x") for item in items)
        def string(value):
            encoded = value.encode()
            return words(32, len(encoded)) + encoded.hex().ljust(((len(encoded) + 31) // 32) * 64, "0")
        def header(number):
            timestamp = 0 if number == 0 else 1_500_000_000 + number * 12
            if same_second and number == target - 1:
                timestamp = requested
            return {"number": hex(number), "timestamp": hex(timestamp),
                    "hash": "0x" + format(number, "064x"), "parentHash": "0x" + format(max(0, number - 1), "064x")}

        def respond(request):
            method, params = request["method"], request["params"]
            if method == "eth_chainId":
                result = "0x1"
            elif method == "eth_getBlockByNumber":
                result = header(latest if params[0] == "latest" else int(params[0], 16))
            elif method == "eth_call":
                selector, number = params[0]["data"][:10], int(params[1], 16)
                if selector == chainlink._selector("latestRoundData()"):
                    next_publication = target if ambiguous else target + 2
                    updated = requested - 36 if number < next_publication else requested + (0 if ambiguous else 24)
                    result = words(round_id, 2000 * 10 ** 8, updated, updated, round_id)
                elif selector in (chainlink._selector("phaseAggregators(uint16)"), chainlink._selector("aggregator()")):
                    result = words(int(aggregator, 16))
                elif selector == chainlink._selector("typeAndVersion()"):
                    result = string("AccessControlledOffchainAggregator 4.0.0")
                elif selector == chainlink._selector("description()"):
                    result = string("ETH / USD")
                elif selector == chainlink._selector("decimals()"):
                    result = words(8)
                else:
                    raise AssertionError(f"Unexpected contract selector: {selector}")
            else:
                raise AssertionError(f"Unexpected RPC method: {method}")
            return {"jsonrpc": "2.0", "id": request["id"], "result": result}

        client = self._client(respond)
        context = {"number": target, "hash": self.BLOCK if mismatch else header(target)["hash"], "timestamp": requested}
        config = {"enabled": True, "feeds": DEFAULT_FEEDS, "max_rpc_calls": 80, "timeout_seconds": 5}
        with patch.object(chainlink, "get_chainlink_config", return_value=config), patch.object(
            chainlink, "JSONRPCS", {"Ethereum": ["https://offline.invalid"]}
        ), patch.object(chainlink.aiohttp, "ClientSession", return_value=client), patch.object(
            chainlink, "_read_cache", return_value=None
        ), patch.object(chainlink, "_write_cache"):
            result = await chainlink.get_chainlink_price("ethereum", self.WETH, requested,
                                                       block_context=context if hint else None)
        return result, client.requests

    async def test_archive_block_hint_preserves_quote_and_reduces_rpc_work(self):
        plain, plain_calls = await self._archive_quote()
        hinted, hinted_calls = await self._archive_quote(hint=True)
        self.assertEqual(plain["status"], "available", plain)
        self.assertEqual(hinted["status"], "available", hinted)
        for field in ("price_exact", "timestamp", "round_id", "successor", "historical_snapshot"):
            self.assertEqual(hinted[field], plain[field], field)
        self.assertEqual(hinted["price_exact"], "2000.00000000")
        self.assertLess(len(hinted_calls), len(plain_calls))
        self.assertLessEqual(len(hinted_calls), 20)
        self.assertFalse(hinted["transaction_state_verified"])

    async def test_same_second_blocks_search_back_before_requested_second(self):
        plain, _ = await self._archive_quote(same_second=True)
        hinted, _ = await self._archive_quote(hint=True, same_second=True)
        self.assertEqual(hinted["status"], "available", hinted)
        self.assertEqual(hinted["historical_snapshot"], plain["historical_snapshot"])
        self.assertEqual(hinted["historical_snapshot"]["before"]["number"], 499_998)
        self.assertEqual(hinted["historical_snapshot"]["after"]["number"], 499_999)

    async def test_publication_in_transaction_second_remains_ambiguous(self):
        result, _ = await self._archive_quote(hint=True, ambiguous=True)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], "timestamp_order_ambiguous")
        self.assertIsNone(result["price"])

    async def test_rpc_rejects_transaction_hint_with_wrong_block_hash(self):
        result, calls = await self._archive_quote(hint=True, mismatch=True)
        self.assertEqual(result["reason"], "historical_block_context_mismatch")
        self.assertIsNone(result["price"])
        self.assertFalse(any(call["method"] == "eth_call" for call in calls))

    async def test_unknown_lp_and_future_vendor_quote_do_not_become_valuations(self):
        from app.attackpilot.utils import chainlink, price

        lp = "0x" + "1" * 40
        oracle = AsyncMock(return_value={"status": "unsupported", "reason": "feed_not_configured"})
        with patch.object(chainlink, "get_chainlink_price", oracle), patch.object(
            price, "_get_defillama_price", AsyncMock(side_effect=[{}, {"price": 5, "timestamp": self.TIMESTAMP + 1}])
        ):
            missing = await price.get_token_price(f"ethereum:{lp}", self.TIMESTAMP)
            future = await price.get_token_price(f"ethereum:{lp}", self.TIMESTAMP)
        self.assertEqual(missing[f"ethereum:{lp}"]["valuation_status"], "unavailable")
        self.assertIsNone(missing[f"ethereum:{lp}"]["price"])
        self.assertEqual(future[f"ethereum:{lp}"]["reason_code"], "future_quote")
        self.assertIsNone(future[f"ethereum:{lp}"]["price"])

    async def test_rpc_accepts_out_of_order_completions_but_rejects_wrong_ids(self):
        from app.attackpilot.utils.chainlink import _ReadError, _Rpc

        second_done = asyncio.Event()
        completed = []
        async def before_read(request):
            if request["id"] == 1:
                await second_done.wait()
            else:
                second_done.set()
            completed.append(request["id"])
        client = self._client(lambda request: {"jsonrpc": "2.0", "id": request["id"], "result": request["method"]}, before_read)
        rpc = _Rpc(client, {"max_rpc_calls": 2})
        result = await asyncio.wait_for(asyncio.gather(rpc.request("first", []), rpc.request("second", [])), 1)
        self.assertEqual(result, ["first", "second"])
        self.assertEqual(completed, [2, 1])
        with self.assertRaisesRegex(_ReadError, "rpc_budget_exceeded"):
            await rpc.request("third", [])
        self.assertEqual(len(client.requests), 2)
        invalid = self._client(lambda request: {"jsonrpc": "2.0", "id": request["id"] + 1, "result": "wrong response"})
        with self.assertRaisesRegex(_ReadError, "invalid_response"):
            await _Rpc(invalid, {"max_rpc_calls": 1}).request("first", [])

    async def test_parallel_rpc_failure_reaps_siblings_before_returning(self):
        from app.attackpilot.utils.chainlink import _ReadError, _parallel_reads

        started, stopped = asyncio.Event(), asyncio.Event()
        async def hanging():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        async def failing():
            await started.wait()
            raise _ReadError("rpc_timeout")
        with self.assertRaisesRegex(_ReadError, "rpc_timeout"):
            await asyncio.wait_for(_parallel_reads(hanging(), failing()), 1)
        self.assertTrue(stopped.is_set())

    async def test_parallel_rpc_cancellation_reaps_all_children(self):
        from app.attackpilot.utils.chainlink import _parallel_reads

        started = [asyncio.Event(), asyncio.Event()]
        stopped = []
        async def hanging(index):
            started[index].set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.append(index)
        operation = asyncio.create_task(_parallel_reads(hanging(0), hanging(1)))
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started)), 1)
        operation.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await operation
        self.assertCountEqual(stopped, [0, 1])

    async def test_unavailable_quote_is_shared_within_task_and_retried_in_next_task(self):
        from app.attackpilot.utils import chainlink, price

        oracle = AsyncMock(return_value={"status": "unavailable", "reason": "rpc_timeout"})
        vendor = AsyncMock(return_value={})
        coin = f"ethereum:{self.WETH}"
        with patch.object(chainlink, "get_chainlink_price", oracle), patch.object(price, "_get_defillama_price", vendor):
            async with price.price_quote_scope():
                first, second = await asyncio.gather(price.get_token_price(coin, self.TIMESTAMP),
                                                     price.get_token_price(coin, self.TIMESTAMP))
                first[coin]["chainlink"]["reason"] = "consumer mutation"
                third = await price.get_token_price(coin, self.TIMESTAMP)
                self.assertEqual(second, third)
                self.assertEqual(third[coin]["reason_code"], "rpc_timeout")
                self.assertEqual(oracle.await_count, 1)
                self.assertEqual(vendor.await_count, 1)
            async with price.price_quote_scope():
                await price.get_token_price(coin, self.TIMESTAMP)
        self.assertEqual(oracle.await_count, 2)
        self.assertEqual(vendor.await_count, 2)

    async def test_cancelled_price_consumer_does_not_cancel_shared_quote(self):
        from app.attackpilot.utils import chainlink, price

        started, release = asyncio.Event(), asyncio.Event()
        async def oracle(*args, **kwargs):
            started.set()
            await release.wait()
            return {"status": "unavailable", "reason": "rpc_timeout"}
        coin = f"ethereum:{self.WETH}"
        with patch.object(chainlink, "get_chainlink_price", AsyncMock(side_effect=oracle)) as reader, patch.object(
            price, "_get_defillama_price", AsyncMock(return_value={})
        ):
            async with price.price_quote_scope():
                first = asyncio.create_task(price.get_token_price(coin, self.TIMESTAMP))
                await asyncio.wait_for(started.wait(), 1)
                second = asyncio.create_task(price.get_token_price(coin, self.TIMESTAMP))
                first.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await first
                release.set()
                result = await asyncio.wait_for(second, 1)
                self.assertEqual(result[coin]["reason_code"], "rpc_timeout")
                self.assertEqual(reader.await_count, 1)

    async def test_distinct_block_hashes_do_not_share_task_quote(self):
        from app.attackpilot.utils import chainlink, price

        oracle = AsyncMock(return_value={"status": "unavailable", "reason": "rpc_timeout"})
        contexts = [{"number": 500_000, "hash": value, "timestamp": self.TIMESTAMP}
                    for value in (self.BLOCK, "0x" + "c" * 64)]
        with patch.object(chainlink, "get_chainlink_price", oracle), patch.object(
            price, "_get_defillama_price", AsyncMock(return_value={})
        ):
            async with price.price_quote_scope():
                for context in (*contexts, *contexts):
                    await price.get_token_price(f"ethereum:{self.WETH}", self.TIMESTAMP, block_context=context)
        self.assertEqual(oracle.await_count, 2)
        self.assertEqual([call.kwargs["block_context"] for call in oracle.await_args_list], contexts)

    async def test_task_scope_exit_reaps_pending_quote(self):
        from app.attackpilot.utils import chainlink, price

        started, stopped = asyncio.Event(), asyncio.Event()
        async def oracle(*args, **kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        with patch.object(chainlink, "get_chainlink_price", AsyncMock(side_effect=oracle)):
            async with price.price_quote_scope():
                consumer = asyncio.create_task(price.get_token_price(f"ethereum:{self.WETH}", self.TIMESTAMP))
                await asyncio.wait_for(started.wait(), 1)
                consumer.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await consumer
            self.assertTrue(stopped.is_set())


class CompilerInstallationTest(unittest.TestCase):
    VERSION = "0.8.23+commit.f704f362"
    BINARY = b"official-compiler-fixture"

    def manifest(self):
        import hashlib

        build = {"path": f"solc-linux-amd64-v{self.VERSION}", "version": "0.8.23",
                 "build": "commit.f704f362", "longVersion": self.VERSION,
                 "sha256": "0x" + hashlib.sha256(self.BINARY).hexdigest()}
        return {"builds": [build], "releases": {"0.8.23": build["path"]}}

    def download(self, url, output, limit):
        output.write(json.dumps(self.manifest()).encode() if url.endswith("list.json") else self.BINARY)

    def test_stable_selection_rejects_other_commit_and_prerelease(self):
        from app.attackpilot.prepare import _compiler_build

        manifest = self.manifest()
        nightly = {**manifest["builds"][0], "prerelease": "nightly.2023.10.20"}
        manifest["builds"].insert(0, nightly)
        self.assertEqual(_compiler_build(manifest, "v0.8.23")["longVersion"], self.VERSION)
        self.assertEqual(_compiler_build(manifest, "v" + self.VERSION)["longVersion"], self.VERSION)
        with self.assertRaisesRegex(ValueError, "No unique"):
            _compiler_build(manifest, "v0.8.23+commit.12345678")
        manifest["builds"] = [nightly]
        with self.assertRaisesRegex(ValueError, "No unique"):
            _compiler_build(manifest, "0.8.23")

    def test_installs_atomically_and_reuses_verified_existing_binary(self):
        import subprocess
        from app.attackpilot import prepare

        version_output = subprocess.CompletedProcess([], 0, stdout=f"Version: {self.VERSION}.Linux.g++\n")
        with tempfile.TemporaryDirectory() as directory, patch.object(
            prepare.platform, "system", return_value="Linux"
        ), patch.object(prepare.platform, "machine", return_value="x86_64"), patch.object(
            prepare, "_download_compiler_asset", side_effect=self.download
        ) as download, patch.object(prepare.subprocess, "run", return_value=version_output):
            first = prepare.install_compiler("v" + self.VERSION, directory)
            target = Path(first["path"])
            self.assertTrue(first["installed"])
            self.assertEqual(target.read_bytes(), self.BINARY)
            self.assertEqual(target.stat().st_mode & 0o777, 0o755)
            self.assertEqual(list(Path(directory).iterdir()), [target])
            second = prepare.install_compiler("v" + self.VERSION, directory)
            self.assertFalse(second["installed"])
            binary_calls = [call for call in download.call_args_list if not call.args[0].endswith("list.json")]
            self.assertEqual(len(binary_calls), 1)

    def test_bad_checksum_preserves_existing_file_and_removes_temporary_files(self):
        from app.attackpilot import prepare

        def corrupt_download(url, output, limit):
            if url.endswith("list.json"):
                self.download(url, output, limit)
            else:
                output.write(b"corrupted-download")

        with tempfile.TemporaryDirectory() as directory, patch.object(
            prepare.platform, "system", return_value="Linux"
        ), patch.object(prepare.platform, "machine", return_value="x86_64"), patch.object(
            prepare, "_download_compiler_asset", side_effect=corrupt_download
        ), patch.object(prepare.subprocess, "run") as execute:
            target = Path(directory) / self.manifest()["builds"][0]["path"]
            target.write_bytes(b"previous-installation")
            with self.assertRaisesRegex(RuntimeError, "SHA256"):
                prepare.install_compiler(self.VERSION, directory)
            self.assertEqual(target.read_bytes(), b"previous-installation")
            self.assertEqual(list(Path(directory).iterdir()), [target])
            execute.assert_not_called()

    def test_wrong_reported_version_and_interrupted_download_leave_no_installation(self):
        import subprocess
        from app.attackpilot import prepare

        def interrupted_download(url, output, limit):
            self.download(url, output, limit)
            if not url.endswith("list.json"):
                raise TimeoutError("connection interrupted")

        version_output = subprocess.CompletedProcess([], 0, stdout="Version: 0.8.22+commit.4fc1097e.Linux.g++\n")
        with tempfile.TemporaryDirectory() as directory, patch.object(
            prepare.platform, "system", return_value="Linux"
        ), patch.object(prepare.platform, "machine", return_value="x86_64"), patch.object(
            prepare.subprocess, "run", return_value=version_output
        ):
            for download in (self.download, interrupted_download):
                with self.subTest(download=download.__name__), patch.object(
                    prepare, "_download_compiler_asset", side_effect=download
                ):
                    with self.assertRaises(RuntimeError):
                        prepare.install_compiler(self.VERSION, directory)
                    self.assertEqual(list(Path(directory).iterdir()), [])

    def test_unsupported_platform_and_malformed_version_do_not_download(self):
        from app.attackpilot import prepare

        with patch.object(prepare, "_download_compiler_asset") as download, patch.object(
            prepare.platform, "system", return_value="Darwin"
        ):
            with self.assertRaisesRegex(ValueError, "Linux x86_64"):
                prepare.install_compiler(self.VERSION, "/unused")
            download.assert_not_called()
        with patch.object(prepare, "_download_compiler_asset") as download, patch.object(
            prepare.platform, "system", return_value="Linux"
        ), patch.object(prepare.platform, "machine", return_value="x86_64"):
            with self.assertRaisesRegex(ValueError, "stable Solidity"):
                prepare.install_compiler("../../compiler", "/unused")
            download.assert_not_called()

    def test_download_rejects_oversize_response_and_external_redirect(self):
        import io
        from app.attackpilot import prepare

        url = prepare.SOLC_SOURCES[0] + "list.json"
        for redirect, headers, payload in (
            (url, {"Content-Length": "5"}, b""),
            (url, {}, b"12345"),
            ("https://untrusted.invalid/compiler", {}, b"123"),
        ):
            response = io.BytesIO(payload)
            response.headers = headers
            response.geturl = lambda redirect=redirect: redirect
            with self.subTest(redirect=redirect, headers=headers), patch.object(
                prepare, "urlopen", return_value=response
            ):
                with self.assertRaises(ValueError):
                    prepare._download_compiler_asset(url, io.BytesIO(), 4)


class SourceLookupRegressionTest(unittest.IsolatedAsyncioTestCase):
    ADDRESS = '0x' + '7' * 40

    def downloader_client(self, *responses):
        client = Mock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.get = AsyncMock(side_effect=responses)
        return client

    async def test_explorer_retries_one_transient_connect_timeout(self):
        from app.attackpilot.downloaders.contract import ContractSourceDownloader
        response = httpx.Response(200, text='{"result": []}', request=httpx.Request('GET', 'https://example.test'))
        client = self.downloader_client(httpx.ConnectTimeout('unavailable'), response)
        with patch('app.attackpilot.downloaders.defs.httpx.AsyncClient', return_value=client), patch(
                'app.attackpilot.downloaders.defs.asyncio.sleep', AsyncMock()):
            result = await ContractSourceDownloader('https://example.test?chainid=1')._fetch(contract_address=self.ADDRESS)
        self.assertEqual(result, response.text)
        self.assertEqual(client.get.await_count, 2)

    async def test_explorer_retry_is_bounded_and_does_not_retry_auth_or_cancel(self):
        from app.attackpilot.downloaders.contract import ContractSourceDownloader
        auth = httpx.Response(403, request=httpx.Request('GET', 'https://example.test'))
        for responses, expected, attempts in (([httpx.ConnectTimeout('a'), httpx.ConnectTimeout('b')], httpx.ConnectTimeout, 2),
                                              ([auth], httpx.HTTPStatusError, 1),
                                              ([asyncio.CancelledError()], asyncio.CancelledError, 1)):
            client = self.downloader_client(*responses)
            with patch('app.attackpilot.downloaders.defs.httpx.AsyncClient', return_value=client), patch(
                    'app.attackpilot.downloaders.defs.asyncio.sleep', AsyncMock()), self.assertRaises(expected):
                await ContractSourceDownloader('https://example.test?chainid=1')._fetch(contract_address=self.ADDRESS)
            self.assertEqual(client.get.await_count, attempts)

    def dao(self, source):
        from app.attackpilot.daos.tenderly import TenderlyDao
        dao = object.__new__(TenderlyDao)
        dao.source_downloader = Mock(download=AsyncMock(side_effect=source))
        dao.bytecode_downloader = Mock(download=AsyncMock(return_value='0x6000'))
        return dao

    async def test_source_timeout_and_unverified_are_distinct_and_survive_patch_tool(self):
        from app.attackpilot.entities.contract import ContractEntity
        from app.attackpilot.mcp_tools import mcp_server
        from types import SimpleNamespace
        for value, expected, retryable in ((httpx.ConnectTimeout('private endpoint'), 'source_fetch_failed', True),
                                           ({'SourceCode': ''}, 'source_not_verified', False)):
            dao = self.dao([value])
            rows = await dao._supplement_missing_contracts([self.ADDRESS], [], block_number=123)
            lookup = rows[0]['source_lookup']
            self.assertEqual(lookup['reason_code'], expected)
            self.assertIs(lookup['retryable'], retryable)
            self.assertNotIn('private endpoint', json.dumps(rows))
            entity = ContractEntity(rows[0])
            tree = SimpleNamespace(node_map={0: SimpleNamespace(to_addr=self.ADDRESS)}, contracts={self.ADDRESS: entity})
            with patch.object(mcp_server, '_get_session_context', return_value=object()), patch.object(
                    mcp_server, '_get_target_tree', return_value=tree):
                item = await mcp_server.get_patch_items.fn('session', HASH + '::0')
            self.assertEqual(item['source_lookup'], lookup)
            dao.bytecode_downloader.download.assert_awaited_once_with(contract_address=self.ADDRESS, quantity=123)

    async def test_empty_existing_source_is_replaced_once_without_losing_compile_settings(self):
        source = {'SourceCode': '{' + json.dumps({'language': 'Solidity', 'sources': {
                    'Token.sol': {'content': 'pragma solidity ^0.8.20; contract Token {}'}},
                    'settings': {'optimizer': {'enabled': True, 'runs': 777}, 'evmVersion': 'paris',
                                 'metadata': {'bytecodeHash': 'none'}, 'libraries': {'Token.sol': {'L': self.ADDRESS}}}}) + '}',
                  'ContractName': 'Token', 'CompilerVersion': 'v0.8.20+commit.a1b79de6', 'ABI': '[]',
                  'OptimizationUsed': '1', 'Runs': '200'}
        dao = self.dao([source])
        original = {'address': self.ADDRESS, 'deployed_bytecode': '0x6000', 'data': {
            'contract_info': [{'id': 7, 'path': 'Token.sol', 'source': ''}], 'states': [{'name': 'state'}]}}
        rows = await dao._supplement_missing_contracts([self.ADDRESS, self.ADDRESS.upper().replace('0X', '0x')], [original])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['data']['contract_info'][0]['id'], 7)
        self.assertEqual(rows[0]['data']['states'], original['data']['states'])
        self.assertEqual(rows[0]['optimization_runs'], 777)
        self.assertEqual(rows[0]['evm_version'], 'paris')
        self.assertEqual(rows[0]['compiler_settings']['metadata'], {'bytecodeHash': 'none'})
        self.assertEqual(rows[0]['libraries']['Token.sol']['L'], self.ADDRESS)
        self.assertEqual(original['data']['contract_info'][0]['source'], '')
        dao.source_downloader.download.assert_awaited_once()
        dao.bytecode_downloader.download.assert_not_awaited()

    async def test_source_fanout_is_limited_and_duplicate_addresses_are_not_requeried(self):
        active = peak = 0
        async def source(**kwargs):
            nonlocal active, peak
            active += 1; peak = max(peak, active)
            await asyncio.sleep(.01)
            active -= 1
            return {'SourceCode': '', 'ContractName': ''}
        dao = self.dao(source)
        addresses = ['0x' + format(index, '040x') for index in range(1000, 1012)]
        rows = await dao._supplement_missing_contracts(addresses + addresses[:3], [])
        self.assertEqual(len(rows), 12)
        self.assertEqual(peak, 3)
        self.assertEqual(dao.source_downloader.download.await_count, 12)

    async def test_empty_source_cache_is_not_treated_as_permanent_unverified_fact(self):
        from app.attackpilot.downloaders.contract import ContractSourceDownloader
        with tempfile.TemporaryDirectory() as temp, patch('app.attackpilot.downloaders.contract.CACHE_DIR', temp):
            path = Path(temp) / 'source' / (self.ADDRESS + '.json')
            path.parent.mkdir()
            path.write_text(json.dumps({'SourceCode': ''}))
            self.assertIsNone(await ContractSourceDownloader('unused')._preprocess(self.ADDRESS))
            path.write_text(json.dumps({'SourceCode': 'contract Verified {}'}))
            self.assertEqual((await ContractSourceDownloader('unused')._preprocess(self.ADDRESS))['SourceCode'], 'contract Verified {}')

    async def test_patch_tool_recovers_source_ids_without_fabricating_trace_locations(self):
        from app.attackpilot.entities.contract import ContractEntity
        from app.attackpilot.entities.trace import MixTraceItem
        from app.attackpilot.mcp_tools import mcp_server
        from types import SimpleNamespace
        source = 'contract Token { function guard() external {} }'
        start = source.index('function')
        node = MixTraceItem({'to': self.ADDRESS, 'from': '0x'+'1'*40, 'address': self.ADDRESS,
                             'call_type': 'DELEGATECALL', 'input': '0x12345678', 'absolute_position': 9})
        contract = ContractEntity({'address': self.ADDRESS, 'public': True, 'contract_name': 'Token',
                                   'data': {'contract_info': [
                                       {'id': 77, 'path': 'Other.sol', 'source': 'contract Other {}'},
                                       {'id': 31, 'path': 'Token.sol', 'source': source}]}})
        tree = SimpleNamespace(node_map={9: node}, contracts={self.ADDRESS: contract})
        resolution = {'filename': 'Token.sol', 'source_file_id': 1, 'code_start': start,
                      'code_length': len('function guard() external {}'), 'line_number': 1,
                      'function_name': 'guard', 'selector': '0x12345678',
                      'declaring_contract': 'Token', 'source_mapping': 'compiled_ast_function_selector',
                      'compiled': object()}
        with patch.object(mcp_server, '_get_session_context', return_value=object()), patch.object(
                mcp_server, '_get_target_tree', return_value=tree), patch.object(
                mcp_server, '_get_mix_tree', return_value=tree), patch.object(
                mcp_server.ContractDao, 'resolve_source_function', AsyncMock(return_value=resolution)) as resolve:
            result = await mcp_server.get_patch_items.fn('session', HASH+'::9')
            rendered = await mcp_server.get_function_source_code.fn('session', 9)
        self.assertEqual(result['file_index'], 31)
        self.assertEqual(result['source_mapping']['source_file_id'], 1)
        self.assertEqual(node.function_loc.file_index, -1)
        self.assertEqual(node.function_loc.code_start, -1)
        self.assertIn('function guard() external {}', rendered)
        self.assertIn('compiled_ast_function_selector', rendered)
        self.assertNotIn('compiled', result['source_mapping'])
        json.dumps(result)
        resolve.assert_awaited_once()

    async def test_unknown_selector_and_internal_call_cannot_invent_patch_file(self):
        from app.attackpilot.entities.contract import ContractEntity
        from app.attackpilot.entities.trace import MixTraceItem
        from app.attackpilot.mcp_tools import mcp_server
        from types import SimpleNamespace
        contract = ContractEntity({'address': self.ADDRESS, 'public': True, 'contract_name': 'Token',
                                   'data': {'contract_info': [{'id': 3, 'path': 'Token.sol',
                                                              'source': 'contract Token {}'}]}})
        for call_type in ('CALL', 'JUMP'):
            node = MixTraceItem({'to': self.ADDRESS, 'from': '0x'+'1'*40, 'address': self.ADDRESS,
                                 'call_type': call_type, 'input': '0x12345678', 'absolute_position': 9})
            tree = SimpleNamespace(node_map={9: node}, contracts={self.ADDRESS: contract})
            with patch.object(mcp_server, '_get_session_context', return_value=object()), patch.object(
                    mcp_server, '_get_target_tree', return_value=tree), patch.object(
                    mcp_server.ContractDao, 'resolve_source_function', AsyncMock(side_effect=ValueError('Unknown selector'))) as resolve:
                result = await mcp_server.get_patch_items.fn('session', HASH+'::9')
            self.assertEqual(result['file_index'], -1)
            self.assertIsNone(result['source_mapping'])
            if call_type == 'JUMP':
                resolve.assert_not_awaited()


if __name__ == "__main__": unittest.main()
