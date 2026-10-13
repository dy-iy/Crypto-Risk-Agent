from pathlib import Path
import hashlib
import json
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.attackpilot import api, report_translation as translation, settings, store
from app.attackpilot.language import CHINESE_OUTPUT_RULES, chinese_messages
from app.schemas_auth import AuthUser


class TranslationApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = patch.object(settings, "DATABASE_PATH", Path(self.temp.name) / "test.sqlite3")
        self.database.start()
        self.addCleanup(self.database.stop)
        app = FastAPI()
        app.include_router(api.router)
        self.client = TestClient(app)
        self.user = None
        async def caller():
            yield self.user
        app.dependency_overrides[api.caller] = caller
        self.report = "# Attack Summary\n\nThe attacker called `withdraw()` and transferred 18.6 ETH."
        self.task = store.create_task("alice", {"name": "Translation test"})
        self.key = self.task["task_id"]
        store.transition(self.key, "completed", result=self.report)
        self.demo_id = str(uuid.uuid4())
        store.import_seed({"tasks": [{"task_id": self.demo_id, "dapp_name": "Public report", "status": "completed", "created_at": store.now(), "final_report": self.report}]})

    def login(self, name="alice"):
        self.user = AuthUser(id=name, username=name, display_name=name, created_at=store.now())

    def path(self, key=None):
        return f"/api/attackpilot/tasks/{key or self.key}/report-translation"

    def test_private_derivatives_follow_task_ownership(self):
        for name in (None, "bob"):
            if name:
                self.login(name)
            self.assertEqual(self.client.get(self.path()).status_code, 404)
            self.assertEqual(self.client.post(self.path()).status_code, 404)

    def test_guest_reads_cache_but_cannot_trigger_model(self):
        response = self.client.get(self.path(self.demo_id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "missing")
        self.assertEqual(self.client.post(self.path(self.demo_id)).status_code, 401)

    def test_translation_cached_and_original_demo_is_unchanged(self):
        self.login()
        original = store.get_task(self.demo_id)
        chinese = "# 攻击摘要\n\n攻击者调用 `withdraw()` 并转移了 18.6 ETH。"
        with patch.object(settings, "LLM_API_KEY", "test-key"), patch.object(translation, "translate_report", AsyncMock(return_value=chinese)) as model:
            first = self.client.post(self.path(self.demo_id))
            second = self.client.post(self.path(self.demo_id))
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.json()["translated_report"], chinese)
            self.assertEqual(second.json()["status"], "ready")
            self.assertEqual(model.await_count, 1)
        self.user = None
        self.assertEqual(self.client.get(self.path(self.demo_id)).json()["translated_report"], chinese)
        self.assertEqual(store.get_task(self.demo_id), original)

    def test_model_failure_never_caches_partial_translation(self):
        self.login()
        with patch.object(settings, "LLM_API_KEY", "test-key"), patch.object(translation, "translate_report", AsyncMock(side_effect=ValueError("secret upstream detail"))):
            response = self.client.post(self.path())
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("secret upstream", response.text)
        self.assertEqual(self.client.get(self.path()).json()["status"], "missing")
        self.assertEqual(store.get_task(self.key)["final_report"], self.report)

    def test_source_change_does_not_reuse_stale_cache_and_delete_cascades(self):
        self.login()
        with patch.object(settings, "LLM_API_KEY", "test-key"), patch.object(translation, "translate_report", AsyncMock(return_value="中文译文")):
            self.assertEqual(self.client.post(self.path()).status_code, 200)
        exported = store.export_user("alice")
        self.assertEqual(len(exported["report_translations"]), 1)
        self.assertEqual(store.export_user("bob")["report_translations"], [])
        with store.connection() as db:
            db.execute("UPDATE tasks SET final_report=? WHERE task_id=?", ("Changed original report", self.key))
        self.assertEqual(self.client.get(self.path()).json()["status"], "missing")
        store.delete_task(self.key)
        with store.connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM report_translations").fetchone()[0], 0)

    def test_chinese_report_needs_no_model(self):
        self.login()
        with store.connection() as db:
            db.execute("UPDATE tasks SET final_report=? WHERE task_id=?", ("# 攻击摘要\n\n攻击者利用漏洞转移了 18.6 ETH，尚未执行补丁验证。", self.key))
        with patch.object(settings, "LLM_API_KEY", ""), patch.object(translation, "translate_report", AsyncMock()) as model:
            response = self.client.post(self.path())
        self.assertEqual(response.json()["status"], "original")
        model.assert_not_awaited()

    def test_local_import_validates_evidence_and_never_packages_private_reports(self):
        from evals.import_attackpilot_translations import import_translations, write_public_bundle
        directory = Path(self.temp.name) / "translations"
        directory.mkdir()
        translated = "# 攻击摘要\n\n攻击者调用 `withdraw()` 并转移了 18.6 ETH。"
        for key in (self.key, self.demo_id):
            (directory / f"{key}.md").write_text(self.report)
            (directory / f"{key}.zh-CN.md").write_text(translated)
        self.assertEqual(len(import_translations(directory)), 2)
        destination = directory / "public.json"
        self.assertEqual(write_public_bundle(destination), 1)
        public = json.loads(destination.read_text())
        self.assertEqual([item["task_id"] for item in public["items"]], [self.demo_id])
        (directory / f"{self.key}.zh-CN.md").write_text(translated.replace("18.6", "18.7"))
        with self.assertRaisesRegex(ValueError, "Evidence counts changed"):
            import_translations(directory)

    def test_packaged_translations_are_idempotent_and_ignore_private_or_stale_sources(self):
        directory = Path(self.temp.name) / "package"
        (directory / "data").mkdir(parents=True)
        item = {"source_hash": hashlib.sha256(self.report.encode()).hexdigest(), "language": "zh-CN", "translated_report": "中文历史译文", "model": "assistant-translation"}
        (directory / "data/report-translations.zh-CN.json").write_text(json.dumps({"items": [
            {**item, "task_id": self.key},
            {**item, "task_id": self.demo_id, "source_hash": "stale-source-hash"},
            {**item, "task_id": self.demo_id},
        ]}))
        with patch.object(settings, "PACKAGE_ROOT", directory):
            store.import_seed({})
            store.import_seed({})
        with store.connection() as db:
            rows = db.execute("SELECT task_id FROM report_translations").fetchall()
        self.assertEqual([row["task_id"] for row in rows], [self.demo_id])


class TranslationContentTest(unittest.IsolatedAsyncioTestCase):
    async def test_markdown_evidence_is_protected_and_restored_exactly(self):
        address = "0x" + "a" * 40
        source = f"# Attack Summary\n\nThe attacker called `withdraw()` with 18.6 ETH at {address}.\n\n```solidity\nfunction withdraw() public {{ balance = 0; }}\n```"
        async def complete(**kwargs):
            text = kwargs["messages"][-1]["content"]
            for before, after in {"Attack Summary": "攻击摘要", "The attacker called": "攻击者调用", "with": "使用", "at": "位于"}.items():
                text = text.replace(before, after)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])
        client = Mock(create_chat_completion=AsyncMock(side_effect=complete))
        with patch.object(translation, "LLMClient", return_value=client):
            report = await translation.translate_report(source)
        self.assertIn("攻击摘要", report)
        for evidence in ("`withdraw()`", "18.6", address, "```solidity\nfunction withdraw() public { balance = 0; }\n```"):
            self.assertIn(evidence, report)
        self.assertNotIn("APKEEP_", report)

    async def test_missing_evidence_is_rejected(self):
        client = Mock(create_chat_completion=AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="攻击者调用提现函数转走资金。"))])))
        with patch.object(translation, "LLMClient", return_value=client):
            with self.assertRaises(ExceptionGroup):
                await translation.translate_report("The attacker called `withdraw()` and transferred 18.6 ETH.")

    def test_chunking_preserves_all_bytes_and_never_splits_evidence(self):
        source = ("Long report paragraph with `withdraw()` and 18.6 ETH.\n\n" * 1000)
        masked, values = translation._protect(source)
        chunks = translation._chunks(masked)
        self.assertGreater(len(chunks), 1)
        self.assertEqual("".join(chunks), masked)
        self.assertEqual(sum(len(translation.PLACEHOLDER.findall(chunk)) for chunk in chunks), len(values))

    def test_language_rule_keeps_protocols_and_does_not_mutate_history(self):
        messages = [{"role": "system", "content": "Return JSON"}, {"role": "user", "content": "Analyze"}]
        result = chinese_messages(messages)
        self.assertEqual(messages[0]["content"], "Return JSON")
        self.assertIn("JSON 字段名、枚举值", result[0]["content"])
        self.assertEqual(chinese_messages(result)[0]["content"].count(CHINESE_OUTPUT_RULES), 1)

    def test_translation_uses_analysis_quota_without_blocking_cancel(self):
        from app.services.rate_limit_service import match_rate_limit_rule
        with patch.dict("os.environ", {"API_RATE_LIMIT_ENABLED": "1"}):
            self.assertEqual(match_rate_limit_rule("/api/attackpilot/tasks/example/report-translation", "POST").name, "agent")
            self.assertEqual(match_rate_limit_rule("/api/attackpilot/tasks/example/cancel", "POST").name, "mutation")


if __name__ == "__main__":
    unittest.main()
