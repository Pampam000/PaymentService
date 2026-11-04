import asyncio
import json
import unittest
from unittest.mock import patch
from uuid import uuid4

import httpx
from pydantic import SecretStr

from payment_service.core.observability import log_operation
from payment_service.core.observability import increment_counter, record_issue
from payment_service.core.db import database_available, session_factory
from payment_service.models.operations import MetricCounter, ReconciliationIssue
from payment_service.main import app


class ObservabilityTests(unittest.TestCase):
    def test_log_uses_only_allowlisted_fields(self) -> None:
        with patch("payment_service.core.observability.logger.warning") as info:
            log_operation("payment_create", "error", error_class="provider_error")
        payload = json.loads(info.call_args.args[0])
        self.assertEqual(set(payload), {
            "correlation_id", "operation", "local_id", "provider_id", "outcome", "error_class",
        })
        self.assertNotIn("secret", info.call_args.args[0].lower())

    def test_metrics_require_admin_token_and_expose_counts(self) -> None:
        async def run() -> None:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
                self.assertEqual((await client.get("/internal/metrics")).status_code, 401)
                response = await client.get("/internal/metrics", headers={"Authorization": "Bearer admin-test"})
                self.assertEqual(response.status_code, 200)
                self.assertIn("payment_service_operation_age_seconds", response.text)
                self.assertIn("payment_service_unresolved_discrepancies", response.text)
                self.assertIn('payment_service_api_errors_total{code="unauthorized"}', response.text)

        with patch("payment_service.core.auth.settings") as settings:
            settings.admin_token = SecretStr("admin-test")
            asyncio.run(run())

    def test_worker_signals_survive_separate_processes(self) -> None:
        if not asyncio.run(database_available()):
            self.skipTest("Local PostgreSQL is unavailable")
        issue_id = uuid4()

        async def run() -> None:
            await record_issue("payment", issue_id, True)
            await increment_counter("delivery")
            async with session_factory()() as session:
                self.assertIsNotNone(await session.get(ReconciliationIssue, ("payment", issue_id)))
                self.assertGreater((await session.get(MetricCounter, "delivery")).value, 0)
            await record_issue("payment", issue_id, False)
            async with session_factory()() as session:
                self.assertIsNone(await session.get(ReconciliationIssue, ("payment", issue_id)))

        asyncio.run(run())

    def test_invalid_webhook_body_does_not_reach_operation_log(self) -> None:
        async def run() -> None:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
                response = await client.post("/webhooks/yookassa", json={"secret": "sensitive-test-value"})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(json.loads(records.records[0].message)["correlation_id"], response.json()["request_id"])

        with self.assertLogs("payment_service.operations") as records:
            asyncio.run(run())
        self.assertNotIn("sensitive-test-value", " ".join(records.output))


if __name__ == "__main__":
    unittest.main()
