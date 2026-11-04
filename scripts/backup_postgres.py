"""Create a retained custom-format PostgreSQL backup outside the service tree."""

import argparse
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
from uuid import uuid4

from sqlalchemy.engine import make_url

from payment_service.core.config import settings


def backup(output_dir: Path, *, keep_days: int = 14) -> Path:
    output_dir = output_dir.resolve()
    if not output_dir.is_dir():
        raise ValueError("Backup directory must already exist")
    if output_dir.is_relative_to(Path(__file__).resolve().parents[1]):
        raise ValueError("Backup directory must be outside the service tree")
    if os.name != "nt" and output_dir.stat().st_mode & 0o077:
        raise ValueError("Backup directory must be accessible only to its owner")
    url = make_url(settings.database_url.get_secret_value().replace("postgresql+asyncpg://", "postgresql://", 1))
    if url.drivername != "postgresql" or not url.database:
        raise ValueError("A PostgreSQL DATABASE_URL is required")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = output_dir / f"payment_service_{timestamp}_{uuid4().hex[:8]}.dump"
    temporary = output_dir / f".{destination.name}.partial"
    environment = os.environ.copy()
    if url.password:
        environment["PGPASSWORD"] = url.password
    command = ["pg_dump", "--format=custom", "--no-owner", "--no-acl",
               "--file", str(temporary), "--host", url.host or "localhost",
               "--port", str(url.port or 5432), "--username", url.username or "",
               url.database]
    try:
        with temporary.open("xb"):
            pass
        if os.name != "nt":
            temporary.chmod(0o600)
        subprocess.run(command, env=environment, check=True, capture_output=True)
        if temporary.stat().st_size == 0:
            raise RuntimeError("pg_dump produced an empty file")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    for old in output_dir.glob("payment_service_*.dump"):
        if old != destination and datetime.fromtimestamp(old.stat().st_mtime, timezone.utc) < cutoff:
            old.unlink()
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a PostgreSQL backup")
    parser.add_argument("output_dir", type=Path, help="Existing protected directory outside the service tree")
    parser.add_argument("--keep-days", type=int, default=14)
    args = parser.parse_args()
    if args.keep_days < 1:
        parser.error("--keep-days must be positive")
    print(backup(args.output_dir, keep_days=args.keep_days))


if __name__ == "__main__":
    main()
