"""Base-source isolation receipts; Phase 6A must not modify active stack owners."""

import hashlib
from pathlib import Path

PINS = {
    "forecasts/models.py": "c0089b77c226e222e8570e3300dff9d9bf95bb5b20513c844b0af9262f21cb9b",
    "forecasts/recommendations.py": "e2bbd0c025984a2aded9f5dc55080c312ca776e0bd1b8c7b22856c23bc4bb896",
    "forecasts/lifecycle.py": "9ccfd4183dfebb0c7211f5f4c2df3d42920802cd8558c1074b6cdd2c40ec4db0",
    "forecasts/portfolio.py": "b91e001ee815d96f14b3f5ba57f4de7908096241c212f9a0672ec7cf68cbb3fb",
    "forecasts/paper.py": "be0cec8fa1dc0a91ee83d4c28b1dad931b38811cc1bd93157be48282fd047cbd",
    "forecasts/sizing.py": "794796b856bb332db7e6c891bd89359abb0edcf742af57b90c69f2287919c920",
    "forecasts/schedules.py": "b25f102fbd530015842cd1dca7bac0916c1f7187694f7c6dcccdbed4bffee291",
    "operations/tasks.py": "f1f4a756980f0c1639904d11b650d21e3389091583c83ef9c38b5e82a433c028",
    "market/live_schedules.py": "2df9e6ad70cc50a5a9f2cfa509973c23dfbc6f2dded53484f83d04e90dac759a",
    "research/models.py": "cb72ee3f0ea35b6e0388bdc26394c80c283607d20c7be0a473c77d6ffe5048e9",
}


def verify(root=None):
    root = root or Path(__file__).resolve().parents[1]
    changed = [
        relative
        for relative, expected in PINS.items()
        if hashlib.sha256((root / relative).read_bytes()).hexdigest() != expected
    ]
    if changed:
        raise ValueError("phase6a_protected_source_drift:" + ",".join(changed))
