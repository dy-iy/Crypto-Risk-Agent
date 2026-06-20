from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import feishu_binding_service as bindings


class FeishuBindingServiceTest(unittest.TestCase):
    def test_binding_status_and_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            binding_path = Path(tmpdir) / "bindings.json"
            with patch.object(bindings, "FEISHU_BINDINGS_PATH", binding_path):
                status = bindings.get_public_feishu_binding("user-1")
                self.assertFalse(status["bound"])

                saved = bindings.upsert_feishu_binding("user-1", {"open_id": "ou_1", "name": "Alice"})
                self.assertTrue(saved["bound"])
                self.assertEqual(saved["name"], "Alice")

                self.assertEqual(bindings.delete_feishu_binding("user-1"), 1)
                self.assertFalse(bindings.get_public_feishu_binding("user-1")["bound"])

    def test_oauth_state_is_one_time_and_user_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "states.json"
            with patch.object(bindings, "FEISHU_OAUTH_STATES_PATH", state_path):
                state = bindings.create_feishu_oauth_state("user-1")

                self.assertFalse(bindings.consume_feishu_oauth_state(state, "user-2"))
                self.assertFalse(bindings.consume_feishu_oauth_state(state, "user-1"))

                state = bindings.create_feishu_oauth_state("user-1")
                self.assertTrue(bindings.consume_feishu_oauth_state(state, "user-1"))
                self.assertFalse(bindings.consume_feishu_oauth_state(state, "user-1"))


if __name__ == "__main__":
    unittest.main()
