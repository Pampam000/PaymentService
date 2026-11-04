import argparse
from pathlib import Path

from alembic import command
from alembic.config import Config

from payment_service.core.config import settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Миграции PaymentService")
    parser.add_argument("command", choices=("upgrade", "current", "check"))
    args = parser.parse_args()
    if not settings.database_url.get_secret_value():
        parser.error("DATABASE_URL is required for migrations")

    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    if args.command == "upgrade":
        command.upgrade(config, "head")
    else:
        getattr(command, args.command)(config)


if __name__ == "__main__":
    main()
