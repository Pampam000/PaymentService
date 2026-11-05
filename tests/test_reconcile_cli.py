import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from payment_service import reconcile, reconcile_refunds


class ReconcileCliTests(unittest.TestCase):
    def test_payment_output_includes_saved_state(self) -> None:
        payment_id = uuid4()
        payment = SimpleNamespace(status="succeeded", resolution_status="known", provider_payment_id="provider-1")
        with patch.object(reconcile, "reconcile_payment", new=AsyncMock(return_value="resolved")), patch.object(
            reconcile, "record_issue", new=AsyncMock(),
        ), patch.object(reconcile, "get_payment", new=AsyncMock(return_value=payment)), patch.object(
            reconcile, "log_operation",
        ):
            result = asyncio.run(reconcile.run_one(payment_id))
        self.assertEqual(result, f"{payment_id} outcome=resolved status=succeeded resolution_status=known")

    def test_refund_output_includes_saved_state(self) -> None:
        refund_id = uuid4()
        refund = SimpleNamespace(status="pending", resolution_status="unknown", provider_refund_id=None)
        with patch.object(reconcile_refunds, "reconcile_refund", new=AsyncMock(return_value="unknown")), patch.object(
            reconcile_refunds, "increment_counter", new=AsyncMock(),
        ), patch.object(reconcile_refunds, "get_refund_details", new=AsyncMock(return_value=(refund, None))), patch.object(
            reconcile_refunds, "log_operation",
        ):
            result = asyncio.run(reconcile_refunds.run_one(refund_id))
        self.assertEqual(result, f"{refund_id} outcome=unknown status=pending resolution_status=unknown")
