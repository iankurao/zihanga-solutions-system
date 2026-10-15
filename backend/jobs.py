"""Scheduled background work: evaluate alerts and send queued email.

Run once (e.g. from cron every 5 minutes):

    python -m backend.jobs

or keep running in a worker process:

    python -m backend.jobs --loop 300

Safe to run alongside the web app and in several processes at once: alert
evaluation is serialized by an advisory lock and each email is claimed with
FOR UPDATE SKIP LOCKED before it is sent.
"""

import argparse
import logging
import time

from backend import notifications
from backend.core.web import db
from backend.domains.alerts import _sync_alerts

logger = logging.getLogger("backend.jobs")


# Sign-in attempts are kept this long for throttling and security review.
LOGIN_ATTEMPT_RETENTION_DAYS = 90


def run_once():
    ran = _sync_alerts(force=True)
    stats = notifications.deliver_pending(db, limit=200)
    db.execute_query(
        "DELETE FROM auth_login_attempts WHERE attempted_at < now() - make_interval(days => %s)",
        (LOGIN_ATTEMPT_RETENTION_DAYS,),
    )
    logger.info("alerts evaluated=%s email=%s", ran, stats)
    return ran, stats


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--loop", type=int, default=0,
                        help="repeat every N seconds instead of running once")
    args = parser.parse_args()
    # The web process starts a delivery thread after each sync; here delivery
    # runs inline so the command finishes only when the queue is processed.
    notifications.background_delivery_enabled = False
    while True:
        try:
            print(run_once())
        except Exception:  # noqa: BLE001 - keep a looping worker alive
            logger.exception("Scheduled job run failed")
            if not args.loop:
                raise
        if not args.loop:
            break
        time.sleep(max(args.loop, 30))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
