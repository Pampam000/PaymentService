import os
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from payment_service.core.config import Settings


class SettingsTests(unittest.TestCase):
    def test_test_mode_never_selects_live_credentials(self) -> None:
        with patch.dict(os.environ, {
            "YOO_MODE": "test",
            "YOO_LIVE_SHOP_ID": "live-shop",
            "YOO_LIVE_SECRET_KEY": "live-secret",
        }, clear=True):
            settings = Settings(_env_file=None)
        self.assertEqual(settings.yoo_shop_id, "")
        self.assertEqual(settings.yoo_secret_key.get_secret_value(), "")
        self.assertNotIn("live-secret", repr(settings))

    def test_duplicate_test_and_live_credentials_are_rejected(self) -> None:
        with patch.dict(os.environ, {
            "YOO_TEST_SHOP_ID": "same-shop",
            "YOO_LIVE_SHOP_ID": "same-shop",
        }, clear=True):
            with self.assertRaises(ValidationError):
                Settings(_env_file=None)

    def test_validation_error_does_not_print_secret(self) -> None:
        with patch.dict(os.environ, {
            "YOO_TEST_SHOP_ID": "test-shop",
            "YOO_TEST_SECRET_KEY": "sensitive-example-key",
        }, clear=True):
            with self.assertRaises(ValidationError) as raised:
                Settings(_env_file=None)
        self.assertNotIn("sensitive-example-key", str(raised.exception))

    def test_production_requires_selected_shop_and_return_url(self) -> None:
        with patch.dict(os.environ, {
            "APP_ENV": "production",
            "DATABASE_URL": "postgresql://user:secret@localhost/db",
        }, clear=True):
            with self.assertRaises(ValidationError):
                Settings(_env_file=None)

    def test_live_mode_requires_production_and_https(self) -> None:
        values = {
            "DATABASE_URL": "postgresql://user:secret@localhost/db",
            "YOO_MODE": "live",
            "YOO_LIVE_SHOP_ID": "live-shop",
            "YOO_LIVE_SECRET_KEY": "live-secret",
            "PAYMENT_RETURN_URL": "http://example.com/return",
        }
        with patch.dict(os.environ, values, clear=True):
            with self.assertRaises(ValidationError):
                Settings(_env_file=None)
        with patch.dict(os.environ, {**values, "APP_ENV": "production"}, clear=True):
            with self.assertRaises(ValidationError):
                Settings(_env_file=None)

    def test_service_tokens_must_differ(self) -> None:
        with patch.dict(os.environ, {"BACKEND_TOKEN": "same", "ADMIN_TOKEN": "same"}, clear=True):
            with self.assertRaises(ValidationError):
                Settings(_env_file=None)


if __name__ == "__main__":
    unittest.main()
