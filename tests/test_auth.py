import unittest
from unittest.mock import patch

from litestar import Litestar, get, post
from litestar.testing import TestClient
from pydantic import SecretStr

from payment_service.core.auth import authorize_internal_request


@post("/payments")
async def create_payment() -> dict[str, str]:
    return {"status": "ok"}


@get("/payments/{id:str}")
async def read_payment(id: str) -> dict[str, str]:
    return {"id": id}


@post("/payments/{id:str}/refunds")
async def create_refund(id: str) -> dict[str, str]:
    return {"id": id}


@get("/refunds/{id:str}")
async def read_refund(id: str) -> dict[str, str]:
    return {"id": id}


@post("/webhooks/yookassa", status_code=200)
async def webhook() -> dict[str, str]:
    return {"status": "accepted"}


class AuthTests(unittest.TestCase):
    def test_credentials_are_scoped_to_routes(self) -> None:
        with patch("payment_service.core.auth.settings") as settings:
            settings.backend_token = SecretStr("backend-secret")
            settings.admin_token = SecretStr("admin-secret")
            app = Litestar(
                route_handlers=[create_payment, read_payment, create_refund, read_refund, webhook],
                before_request=authorize_internal_request,
            )
            with TestClient(app) as client:
                for method, path, token in (
                    ("post", "/payments", "backend-secret"),
                    ("get", "/payments/one", "backend-secret"),
                    ("post", "/payments/one/refunds", "admin-secret"),
                    ("get", "/refunds/one", "admin-secret"),
                ):
                    self.assertEqual(getattr(client, method)(path).status_code, 401)
                    self.assertEqual(getattr(client, method)(path, headers={"Authorization": "Bearer wrong"}).status_code, 401)
                    self.assertEqual(getattr(client, method)(path, headers={"Authorization": f"Bearer {token}"}).status_code, 201 if method == "post" else 200)
                self.assertEqual(client.post("/payments/one/refunds", headers={"Authorization": "Bearer backend-secret"}).status_code, 401)
                self.assertEqual(client.get("/payments/one", headers={"Authorization": "Bearer admin-secret"}).status_code, 401)
                self.assertEqual(client.post("/webhooks/yookassa").status_code, 200)


if __name__ == "__main__":
    unittest.main()
