import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from pydantic import SecretStr

from scripts.check_backup import check_backup


class CheckBackupTests(unittest.TestCase):
    def test_dump_is_restored_verified_and_temporary_database_removed(self) -> None:
        calls = []

        def docker(*args):
            calls.append(args)
            if args[0] == "cp" and args[1].startswith("db:"):
                Path(args[2]).write_bytes(b"backup")

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory, patch(
            "scripts.check_backup.Path.is_relative_to", return_value=False
        ), patch("scripts.check_backup.settings") as settings, patch(
            "scripts.check_backup.shutil.which", return_value="docker"
        ), patch("scripts.check_backup.run", side_effect=docker), patch(
            "scripts.check_backup.verify", new=AsyncMock(return_value=0)
        ) as verify:
            settings.environment = "development"
            settings.yoo_mode = "test"
            settings.database_url = SecretStr(
                "postgresql://payment_service:test-password@127.0.0.1:5433/payment_service"
            )
            backup, failures = check_backup(Path(directory), container="db", admin_user="botctor")
            self.assertEqual(failures, 0)
            self.assertEqual(backup.read_bytes(), b"backup")
        operations = [args[2] if args[0] == "exec" else args[0] for args in calls]
        self.assertEqual(operations, ["pg_dump", "cp", "cp", "createdb", "pg_restore", "dropdb", "rm"])
        self.assertEqual(verify.await_count, 1)
        self.assertNotIn("test-password", repr(calls))


if __name__ == "__main__":
    unittest.main()
