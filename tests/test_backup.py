import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import SecretStr

from scripts.backup_postgres import backup


class BackupTests(unittest.TestCase):
    def test_backup_uses_password_environment_and_keeps_dump(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            def dump(command, *, env, check, capture_output):
                self.assertEqual(env["PGPASSWORD"], "test-password")
                self.assertNotIn("test-password", " ".join(command))
                Path(command[command.index("--file") + 1]).write_bytes(b"test-dump")

            with patch("scripts.backup_postgres.Path.is_relative_to", return_value=False), patch(
                "scripts.backup_postgres.settings"
            ) as settings, patch(
                "scripts.backup_postgres.subprocess.run", side_effect=dump
            ):
                settings.database_url = SecretStr(
                    "postgresql://payment_service:test-password@localhost:5432/payment_service"
                )
                result = backup(Path(directory))
            self.assertEqual(result.read_bytes(), b"test-dump")


if __name__ == "__main__":
    unittest.main()
