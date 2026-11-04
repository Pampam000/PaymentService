"""Run periodically to deliver confirmed payment events to Backend."""

import asyncio
import argparse

from payment_service.repositories.outbox import list_review_events
from payment_service.services.outbox import deliver_pending


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deliver confirmed events to Backend")
    parser.add_argument("--review", action="store_true", help="List events rejected by Backend")
    args = parser.parse_args()
    if args.review:
        for event_id in asyncio.run(list_review_events()):
            print(event_id)
    else:
        print(asyncio.run(deliver_pending()))
