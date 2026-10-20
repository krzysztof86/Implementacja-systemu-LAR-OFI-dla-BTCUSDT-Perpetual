"""End-to-end through the CLI entry point (no network, synthetic data)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from conftest import CONTINUATION_LONG_OBS, obs_items
from lar_ofi.cli import main

# Fixed past moment: the CLI imports with the real clock, so fixtures must lie in the past.
T_PAST = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)


def _run(capsys, *args):
    rc = main(list(args))
    out = capsys.readouterr().out
    return rc, json.loads(out)


def test_cli_import_observe_analyze(env, capsys, tmp_path):
    base = ["--data-dir", str(tmp_path / "home")]
    manifest = env.manifest(t0=T_PAST)
    rc, imp = _run(capsys, *base, "import", str(manifest))
    assert rc == 0 and imp["created"] is True
    ds = imp["dataset_id"]
    rc, again = _run(capsys, *base, "import", str(manifest))
    assert again["created"] is False

    rc, tmpl = _run(capsys, *base, "template", ds, "--out", str(tmp_path / "t.json"))
    ids = {a["file_name"]: a["screenshot_id"] for a in imp["accepted"]}
    (tmp_path / "obs.json").write_text(json.dumps(obs_items(CONTINUATION_LONG_OBS, ids)))
    rc, res = _run(capsys, *base, "observe-file", ds, str(tmp_path / "obs.json"))
    assert rc == 0 and len(res["inserted"]) == len(CONTINUATION_LONG_OBS)

    rc, rej = _run(capsys, *base, "observe", ds, "--screenshot", ids["heat_5m_b.png"], "--field", "ofi",
                   "--value", "1.0")
    assert rc == 2 and rej["status"] == "REJECTED"

    rc, an = _run(capsys, *base, "analyze", ds, "--as-of", "2026-01-15T10:00:00Z", "--out", str(tmp_path / "rep"))
    assert an["decision"] == "LONG"
    md = (tmp_path / "rep").glob("*.md").__next__().read_text()
    assert "NOT_CALIBRATED" in md and "Dowody ZA" in md and "Warunek zanegowania" in md

    rc, l2 = _run(capsys, *base, "l2-status")
    assert l2["l2_enabled"] is False

    rc, v = _run(capsys, *base, "vision", ds)
    assert rc == 2 and v["status"] == "NOT_CONFIGURED"


def test_cli_predict_refuses_stale_screenshots(env, capsys, tmp_path):
    """`predict` always uses the wall clock: old synthetic screenshots are stale,
    so the journaled decision is WAIT (never a backdated LONG)."""
    base = ["--data-dir", str(tmp_path / "home")]
    rc, imp = _run(capsys, *base, "import", str(env.manifest(t0=T_PAST)))
    ids = {a["file_name"]: a["screenshot_id"] for a in imp["accepted"]}
    (tmp_path / "obs.json").write_text(json.dumps(obs_items(CONTINUATION_LONG_OBS, ids)))
    _run(capsys, *base, "observe-file", imp["dataset_id"], str(tmp_path / "obs.json"))
    rc, pred = _run(capsys, *base, "predict", imp["dataset_id"])
    assert pred["status"] == "RECORDED" and pred["decision"] == "WAIT"
    rc, ver = _run(capsys, *base, "verify-journal")
    assert ver["status"] == "OK"
