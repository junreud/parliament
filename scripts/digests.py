"""Queue bounded weekly/daily digests through the local administrator API."""

import argparse
import json
import logging
import os
import urllib.request
from datetime import datetime, timedelta, timezone


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never forward an administrator credential through a redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main() -> None:
    """Queue, never deliver, without logging email addresses or token payloads."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frequency", choices=("daily", "weekly"), required=True)
    args = parser.parse_args()
    key = os.environ.get("TRACKING_ADMIN_KEY")
    if not key:
        parser.error("TRACKING_ADMIN_KEY required")
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=1 if args.frequency == "daily" else 7)
    body = json.dumps(
        {"frequency": args.frequency, "from": start.isoformat(), "to": end.isoformat()}
    ).encode()
    request = urllib.request.Request(
        "http://127.0.0.1:8080/admin/tracking/digests/build",
        data=body,
        headers={"Content-Type": "application/json", "X-Parliament-Ingestion-Key": key},
    )
    with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError("digest queue request failed")
        result = json.loads(response.read(65536))
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger(__name__).info("digest queue completed; result=%s", result)


if __name__ == "__main__":
    main()
