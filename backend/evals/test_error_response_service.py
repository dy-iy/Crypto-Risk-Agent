from __future__ import annotations

import unittest

from app.services.error_response_service import (
    PUBLIC_AGENT_ERROR_DETAIL,
    PUBLIC_INTERNAL_ERROR_DETAIL,
    PUBLIC_NEWS_UPDATE_ERROR_DETAIL,
    PUBLIC_RISK_ASSISTANT_ERROR_DETAIL,
    public_error_payload,
)


class ErrorResponseServiceTest(unittest.TestCase):
    def test_public_error_details_are_generic(self) -> None:
        secret_exception_text = "sk-secret stack /root/projects/Hackathon trace"

        for detail in [
            PUBLIC_AGENT_ERROR_DETAIL,
            PUBLIC_RISK_ASSISTANT_ERROR_DETAIL,
            PUBLIC_NEWS_UPDATE_ERROR_DETAIL,
            PUBLIC_INTERNAL_ERROR_DETAIL,
        ]:
            self.assertNotIn(secret_exception_text, detail)
            self.assertNotIn("{exc}", detail)
            self.assertTrue(detail.endswith("Please retry later."))

    def test_public_error_payload_can_include_job_id(self) -> None:
        payload = public_error_payload(PUBLIC_AGENT_ERROR_DETAIL, "chat-job-1")

        self.assertEqual(
            payload,
            {
                "detail": PUBLIC_AGENT_ERROR_DETAIL,
                "job_id": "chat-job-1",
            },
        )


if __name__ == "__main__":
    unittest.main()
