# tests/unit/test_bootstrap_smoke.py
"""
Minimal, honest smoke test for Step 1.
Does not mock; it validates the real bootstrap on the current machine.
"""

from __future__ import annotations

from app.bootstrap import bootstrap
from app.lifecycle import shutdown


def test_bootstrap_creates_storage_and_config(tmp_path):
    ctx = bootstrap()
    try:
        assert ctx.platform.is_windows()
        assert ctx.paths.root().is_dir()
        assert ctx.paths.paths().database_dir.is_dir()
        assert ctx.paths.paths().logs_dir.is_dir()
        assert ctx.config.get("app.name") == "AIProduct"
        assert ctx.config.get("agent.max_steps") == 25
    finally:
        shutdown(ctx)