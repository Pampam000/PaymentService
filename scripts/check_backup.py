"""Local Docker drill: dump, restore to a new database, verify, clean up."""

import argparse
import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

from sqlalchemy.engine import make_url

from payment_service.core.config import settings
from scripts.verify_restore import verify


def run(*args: str) -> None:
    subprocess.run(["docker", *args], check=True)


def check_backup(output_dir: Path, *, container: str, admin_user: str) -> tuple[Path, int]:
    if settings.environment != "development" or settings.yoo_mode != "test":
        raise ValueError("This drill requires APP_ENV=development and YOO_MODE=test")
    if shutil.which("docker") is None:
        raise RuntimeError("Docker CLI is required")
    output_dir = output_dir.resolve()
    if not output_dir.is_dir() or output_dir.is_relative_to(Path(__file__).resolve().parents[1]):
        raise ValueError("Choose an existing backup directory outside the project")
    if os.name != "nt" and output_dir.stat().st_mode & 0o077:
        raise ValueError("Backup directory must be accessible only to its owner")
    source = make_url(settings.database_url.get_secret_value().replace("postgresql+asyncpg://", "postgresql://", 1))
    if source.drivername != "postgresql" or not source.database or not source.username:
        raise ValueError("A PostgreSQL DATABASE_URL is required")
    if source.host not in ("127.0.0.1", "localhost"):
        raise ValueError("This local Docker drill requires a loopback DATABASE_URL host")

    suffix = uuid4().hex[:12]
    restore_name = f"payment_service_restore_{suffix}"
    dump_in_container = f"/tmp/payment_service_{suffix}.dump"
    restore_dump = f"/tmp/payment_service_{suffix}.restore.dump"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = output_dir / f"payment_service_{timestamp}_{suffix}.dump"
    partial = output_dir / f".{backup.name}.partial"
    created_database = False
    try:
        run("exec", container, "pg_dump", "-U", admin_user, "-Fc", "-f", dump_in_container, source.database)
        run("cp", f"{container}:{dump_in_container}", str(partial))
        if partial.stat().st_size == 0:
            raise RuntimeError("Backup file is empty")
        partial.replace(backup)
        run("cp", str(backup), f"{container}:{restore_dump}")
        run("exec", container, "createdb", "-U", admin_user, "-O", source.username, restore_name)
        created_database = True
        run("exec", container, "pg_restore", "-U", admin_user, f"--role={source.username}",
            "--no-owner", "--no-acl", "--exit-on-error", "-d", restore_name, restore_dump)
        target = source.set(database=restore_name).render_as_string(hide_password=False)
        print(f"Backup: {backup}")
        print(f"Restored database: {restore_name}")
        failures = asyncio.run(verify(target))
        return backup, failures
    finally:
        partial.unlink(missing_ok=True)
        if created_database:
            run("exec", container, "dropdb", "-U", admin_user, restore_name)
        run("exec", container, "rm", "-f", dump_in_container, restore_dump)


def main() -> None:
    parser = argparse.ArgumentParser(description="Test a PaymentService backup with the local Docker PostgreSQL")
    parser.add_argument("output_dir", type=Path, help="Existing backup directory outside the project")
    parser.add_argument("--container", default="botconstructorbackend-db-1")
    parser.add_argument("--admin-user", default="botctor")
    args = parser.parse_args()
    backup, failures = check_backup(args.output_dir, container=args.container, admin_user=args.admin_user)
    print(f"Verification: {'matched' if failures == 0 else f'{failures} unresolved'}")
    print(f"Temporary database removed. Backup retained: {backup}")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
