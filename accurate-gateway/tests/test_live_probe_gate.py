"""Phase 5: live probe must refuse fixture mode / missing credentials."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "scripts" / "phase5_live_probe.py"


def test_live_probe_rejects_fixture_mode():
    env = os.environ.copy()
    env["GATEWAY_MODE"] = "fixture"
    env.pop("ACCURATE_API_TOKEN", None)
    env.pop("ACCURATE_DATABASE_ID", None)
    proc = subprocess.run(
        [sys.executable, str(PROBE)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "live" in proc.stdout.lower() or "fixture" in proc.stdout.lower()


def test_live_probe_rejects_missing_credentials():
    env = os.environ.copy()
    env["GATEWAY_MODE"] = "live"
    env.pop("ACCURATE_API_TOKEN", None)
    env.pop("ACCURATE_DATABASE_ID", None)
    # Clear settings cache side effects via fresh process
    proc = subprocess.run(
        [sys.executable, str(PROBE)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "ACCURATE_API_TOKEN" in proc.stdout
