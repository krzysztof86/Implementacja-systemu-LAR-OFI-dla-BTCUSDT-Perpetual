"""End-to-end through the CLI entry point (no network, synthetic data)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import lar_ofi.cli as cli
from conftest import CONTINUATION_LONG_OBS, STANDARD_SHOTS, obs_items, windows_for
from lar_ofi.cli import main
from lar_ofi.timeutil import now_utc

# Fixed past moment: the CLI imports with the real clock, so fixtures must lie in the past.
T_PAST = datetime(2026, 1, 15, 10, 9, 30, tzinfo=timezone.utc)


def _run(capsys, *args):
    rc = main(list(args))
    out = capsys.readouterr().out
    return rc, json.loads(out)


def _prepare(env, capsys, tmp_path, t0):
    base = ["--data-dir", str(tmp_path / "home")]
    rc, imp = _run(capsys, *base, "import", str(env.manifest(t0=t0)))
    assert rc == 0, imp
    ids = {a["file_name"]: a["screenshot_id"] for a in imp["accepted"]}
    (tmp_path / "obs.json").write_text(json.dumps(obs_items(CONTINUATION_LONG_OBS, ids,
                                                            windows_for(STANDARD_SHOTS, t0))))
    rc, res = _run(capsys, *base, "observe-file", imp["dataset_id"], str(tmp_path / "obs.json"))
    assert rc == 0, res
    return base, imp["dataset_id"], ids


def test_cli_import_observe_analyze(env, capsys, tmp_path):
    base, ds, ids = _prepare(env, capsys, tmp_path, T_PAST)
    rc, again = _run(capsys, *base, "import", str(env.tmp / "m" / "manifest.json"))
    assert again["created"] is False

    rc, tmpl = _run(capsys, *base, "template", ds, "--out", str(tmp_path / "t.json"))
    template = json.loads((tmp_path / "t.json").read_text())
    assert all("procedure" in item and "record_UNKNOWN_when" in item for item in template)

    rc, rej = _run(capsys, *base, "observe", ds, "--screenshot", ids["heat_5m_b.png"], "--field", "ofi",
                   "--value", "1.0")
    assert rc == 2 and rej["status"] == "REJECTED"
    rc, rej = _run(capsys, *base, "observe", ds, "--screenshot", ids["conf_1m.png"], "--field", "liquidations",
                   "--value", "BOTH")
    assert rc == 2 and "window_start_utc" in rej["error"]
    w = windows_for(STANDARD_SHOTS, T_PAST)["conf_1m.png"]
    rc, ok = _run(capsys, *base, "observe", ds, "--screenshot", ids["conf_1m.png"], "--field", "absorption_signal",
                  "--value", "NONE", "--window-start", w[0], "--window-end", w[1])
    assert rc == 0 and ok["status"] == "OK"

    rc, an = _run(capsys, *base, "analyze", ds, "--decision-time", "2026-01-15T10:09:30Z",
                  "--out", str(tmp_path / "rep"))
    assert an["decision"] == "LONG"
    md = next((tmp_path / "rep").glob("*.md")).read_text()
    assert "NOT_CALIBRATED" in md and "Dowody ZA" in md and "data_as_of" in md

    rc, l2 = _run(capsys, *base, "l2-status")
    assert l2["l2_enabled"] is False

    rc, v = _run(capsys, *base, "vision", ds)
    assert rc == 2 and v["status"] == "NOT_CONFIGURED"


def test_cli_predict_on_old_screenshots_is_not_recorded(env, capsys, tmp_path):
    """Regression (P0): `predict` used to set as_of = now, so the lateness limit
    could never trigger. Old screenshots must now be refused, not journaled."""
    base, ds, _ = _prepare(env, capsys, tmp_path, T_PAST)
    rc, pred = _run(capsys, *base, "predict", ds)
    assert rc == 2 and pred["status"] == "NOT_RECORDED"
    assert "LATE_RECORDING" in pred["error"]
    rc, ver = _run(capsys, *base, "verify-journal")
    assert ver["status"] == "OK"


def test_cli_predict_detects_late_recording_with_simulated_clock(env, capsys, tmp_path, monkeypatch):
    """Integration: fresh screenshots, but the decision is made 300 s after the
    newest screenshot. Must be refused; a prompt decision must be recorded."""
    t0 = now_utc() - timedelta(seconds=2)
    base, ds, _ = _prepare(env, capsys, tmp_path, t0)
    newest = t0 - timedelta(seconds=10)  # conf_1m.png, the newest data-bearing screenshot

    late = iter([newest + timedelta(seconds=300), newest + timedelta(seconds=301)])
    monkeypatch.setattr(cli, "_clock", lambda: next(late))
    rc, pred = _run(capsys, *base, "predict", ds)
    assert rc == 2 and "LATE_RECORDING" in pred["error"]

    held = iter([newest + timedelta(seconds=20), newest + timedelta(seconds=90)])  # held 70 s after deciding
    monkeypatch.setattr(cli, "_clock", lambda: next(held))
    rc, pred = _run(capsys, *base, "predict", ds)
    assert rc == 2 and "after the decision time" in pred["error"]

    prompt = iter([newest + timedelta(seconds=20), newest + timedelta(seconds=21)])
    monkeypatch.setattr(cli, "_clock", lambda: next(prompt))
    rc, pred = _run(capsys, *base, "predict", ds)
    assert rc == 0 and pred["status"] == "RECORDED"
    assert pred["data_as_of_utc"] < pred["decision_time_utc"] < pred["recorded_at_utc"]


def test_cli_import_bars_requires_market(env, capsys, tmp_path):
    base = ["--data-dir", str(tmp_path / "home")]
    csv = tmp_path / "bars.csv"
    csv.write_text("open_time_utc,open,high,low,close\n2026-01-15T10:00:00Z,1,2,0.5,1.5\n")
    rc, out = _run(capsys, *base, "import-bars", str(csv))
    assert rc == 2 and "MARKET_UNDECLARED" in out["error"]
    rc, out = _run(capsys, *base, "import-bars", str(csv), "--instrument", "BTCUSDT", "--exchange", "Bybit",
                   "--contract-type", "USDT_PERPETUAL")
    assert rc == 0 and out["inserted"] == 1
