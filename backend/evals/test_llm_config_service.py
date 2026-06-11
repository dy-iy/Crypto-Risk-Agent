from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services.llm_config_service import (
    DEFAULT_DEEPSEEK_TIMEOUT,
    EXPECTED_DEEPSEEK_MODEL,
    get_deepseek_config,
)


class LlmConfigServiceTest(unittest.TestCase):
    def test_defaults_match_project_model_contract(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            config = get_deepseek_config()

        self.assertEqual(config.model, EXPECTED_DEEPSEEK_MODEL)
        self.assertEqual(config.timeout, DEFAULT_DEEPSEEK_TIMEOUT)
        self.assertTrue(config.timeout_valid)

    def test_invalid_timeout_falls_back_to_default(self) -> None:
        with patch.dict(
            "os.environ",
            {"DEEPSEEK_TIMEOUT": "invalid", "DEEPSEEK_MODEL": EXPECTED_DEEPSEEK_MODEL},
            clear=True,
        ):
            config = get_deepseek_config()

        self.assertEqual(config.timeout, DEFAULT_DEEPSEEK_TIMEOUT)
        self.assertFalse(config.timeout_valid)

    def test_timeout_outside_safe_range_falls_back_to_default(self) -> None:
        with patch.dict(
            "os.environ",
            {"DEEPSEEK_TIMEOUT": "999", "DEEPSEEK_MODEL": EXPECTED_DEEPSEEK_MODEL},
            clear=True,
        ):
            config = get_deepseek_config()

        self.assertEqual(config.timeout, DEFAULT_DEEPSEEK_TIMEOUT)
        self.assertFalse(config.timeout_valid)


if __name__ == "__main__":
    unittest.main()
