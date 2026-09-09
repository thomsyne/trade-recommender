"""Offline estimate of M15 acquisition and snapshot storage cost.

Pure arithmetic over the New York FX trading week — no database, provider or
network access. Every quantity is an ESTIMATE from stated assumptions, not a
measurement, and is labelled as such (design §3, §14). It authorizes nothing:
this is input to a later, separate activation decision.
"""

import json

from django.core.management.base import BaseCommand

# New York FX week: Sunday 17:00 -> Friday 17:00 = 5 trading days = 120 hours.
TRADING_HOURS_PER_WEEK = 120
M15_PER_HOUR = 4
DEFAULT_INSTRUMENTS = 12  # all twelve canonical pairs
# Conservative per-row byte assumptions (a Candle row plus its first observation).
ASSUMED_CANDLE_BYTES = 400
ASSUMED_SNAPSHOT_BYTES = 8000


class Command(BaseCommand):
    help = "Estimate M15 acquisition and snapshot storage cost (offline, no DB/provider)."

    def add_arguments(self, parser):
        parser.add_argument("--instruments", type=int, default=DEFAULT_INSTRUMENTS)
        parser.add_argument("--candle-bytes", type=int, default=ASSUMED_CANDLE_BYTES)
        parser.add_argument("--snapshot-bytes", type=int, default=ASSUMED_SNAPSHOT_BYTES)

    def handle(self, *args, **options):
        instruments = options["instruments"]
        m15_per_instrument_week = TRADING_HOURS_PER_WEEK * M15_PER_HOUR
        m15_records_week = m15_per_instrument_week * instruments
        m15_records_day = m15_records_week // 5
        candle_storage_week = m15_records_week * options["candle_bytes"]
        # Upper bound: one snapshot per instrument per M15 interval.
        snapshots_week = m15_records_week
        snapshot_storage_week = snapshots_week * options["snapshot_bytes"]
        report = {
            "measured": False,
            "note": "estimates from stated assumptions; not a measurement; authorizes nothing",
            "assumptions": {
                "trading_hours_per_week": TRADING_HOURS_PER_WEEK,
                "m15_per_hour": M15_PER_HOUR,
                "instruments": instruments,
                "candle_bytes": options["candle_bytes"],
                "snapshot_bytes": options["snapshot_bytes"],
            },
            "estimates": {
                "m15_records_per_instrument_week": m15_per_instrument_week,
                "m15_records_per_day": m15_records_day,
                "m15_records_per_week": m15_records_week,
                "m15_candle_storage_bytes_per_week": candle_storage_week,
                "m15_candle_storage_mb_per_week": round(candle_storage_week / 1_000_000, 3),
                "max_snapshots_per_week": snapshots_week,
                "max_snapshot_storage_mb_per_week": round(snapshot_storage_week / 1_000_000, 3),
                "estimated_storage_mb_per_month": round(
                    (candle_storage_week + snapshot_storage_week) * 52 / 12 / 1_000_000, 3
                ),
            },
        }
        self.stdout.write(json.dumps(report, sort_keys=True, indent=2))
