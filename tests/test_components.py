"""Intake, observations, journal, evaluation and L2 math."""

from __future__ import annotations

from datetime import timedelta

import pytest

from conftest import CONTINUATION_LONG_OBS, MARKET, STANDARD_SHOTS, T0, windows_for
from lar_ofi.config import load_config
from lar_ofi.evaluation import evaluate, max_drawdown, render_evaluation_markdown, wilson
from lar_ofi.journal import _funding_crossed, _score_direction, import_price_bars
from lar_ofi.l2 import (BookDelta, BookSnapshot, BookTop, Trade, compute_l2_metrics, fit_price_impact, ofi,
                        ofi_contribution, queue_imbalance, replay, replenishment_times)
from lar_ofi.observations import (ObservationError, add_observation, current_observations,
                                  observation_template)


# ---- intake -----------------------------------------------------------------
def test_non_image_and_empty_files_rejected(env):
    shots = {"fake.png": {"timeframe": "5M", "indicators": ["Agg. CVD"], "offset_s": -5, "content": b"hello"},
             "empty.png": {"timeframe": "5M", "indicators": ["Agg. CVD"], "offset_s": -5, "content": b""}}
    res = env.import_(env.manifest(shots))
    issues = {r["file_name"]: r["issues"] for r in res.rejected}
    assert any("NOT_AN_IMAGE" in i for i in issues["fake.png"])
    assert "EMPTY_FILE" in issues["empty.png"]
    assert res.status == "NO_USABLE_SCREENSHOTS"


def test_unknown_indicator_and_bad_timeframe_rejected(env):
    shots = {"a.png": {"timeframe": "5M", "indicators": ["RSI"], "offset_s": -5},
             "b.png": {"timeframe": "2H", "indicators": ["Agg. CVD"], "offset_s": -5}}
    res = env.import_(env.manifest(shots))
    assert len(res.rejected) == 2


def test_workspace_limit_flagged(env):
    shots = {"a.png": {"timeframe": "5M", "offset_s": -5,
                       "indicators": ["Agg. CVD", "Agg. Volume Footprint", "Agg. Open Interest", "Agg. Liquidations"]}}
    res = env.import_(env.manifest(shots))
    assert any("MORE_THAN_3_INDICATORS" in i for i in res.accepted[0]["issues"])


def test_capture_after_import_time_rejected(env):
    shots = {"a.png": {"timeframe": "5M", "indicators": ["Agg. CVD"], "offset_s": 3600}}
    res = env.import_(env.manifest(shots))
    assert any("CAPTURED_IN_FUTURE" in i for i in res.rejected[0]["issues"])


# ---- observations -----------------------------------------------------------
def test_field_must_match_indicator_and_timeframe(env):
    res = env.import_(env.manifest())
    ids = env.shot_ids(res.dataset_id)
    with pytest.raises(ObservationError, match="none of which supplies"):
        add_observation(env.conn, res.dataset_id, ids["conf_1m.png"], "cvd_trend", "RISING")
    with pytest.raises(ObservationError, match="not in"):
        add_observation(env.conn, res.dataset_id, ids["flow_5m.png"], "cvd_trend", "UPWARDS")
    with pytest.raises(ObservationError, match="defined for"):
        add_observation(env.conn, res.dataset_id, ids["ctx_4h.png"], "closed_bars_outside_value", 2)


def test_correction_supersedes_and_keeps_history(env):
    ds = env.scenario(CONTINUATION_LONG_OBS)
    cur = {o["field"]: o for o in current_observations(env.conn, ds)}
    old = cur["oi_change"]
    w = windows_for(STANDARD_SHOTS)["flow_5m.png"]
    new_id = add_observation(env.conn, ds, old["screenshot_id"], "oi_change", "FALLING",
                             supersedes=old["observation_id"], window_start=w[0], window_end=w[1])
    cur2 = {o["field"]: o for o in current_observations(env.conn, ds)}
    assert cur2["oi_change"]["observation_id"] == new_id and cur2["oi_change"]["value"] == "FALLING"
    total = env.conn.execute("SELECT COUNT(*) FROM observations WHERE field='oi_change'").fetchone()[0]
    assert total == 2  # original kept


def test_bulk_entry_is_all_or_nothing(env):
    from lar_ofi.observations import add_observations_from_list
    res = env.import_(env.manifest())
    ids = env.shot_ids(res.dataset_id)
    items = [{"screenshot": ids["flow_5m.png"], "field": "cvd_trend", "value": "RISING"},
             {"screenshot": ids["flow_5m.png"], "field": "oi_change", "value": "SIDEWAYS"}]
    inserted, errors = add_observations_from_list(env.conn, res.dataset_id, items)
    assert inserted == [] and errors
    assert env.conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0


def test_template_lists_only_applicable_fields(env):
    res = env.import_(env.manifest())
    t = observation_template(env.conn, res.dataset_id)
    fields_conf = {i["field"] for i in t if i["file_name"] == "conf_1m.png"}
    assert fields_conf == {"last_price", "liquidations", "absorption_signal"}
    assert all("ofi" not in i["field"] for i in t)


# ---- journal math -----------------------------------------------------------
def test_scoring_bands():
    assert _score_direction("LONG", 10.0, 5.0) == ("HIT", 10.0)
    assert _score_direction("SHORT", 10.0, 5.0) == ("MISS", -10.0)
    assert _score_direction("LONG", 4.0, 5.0)[0] == "NEUTRAL"
    assert _score_direction("LONG", 4.0, None)[0] == "UNSCORABLE"


def test_funding_crossing():
    f = {"times_utc": ["08:00"], "cost_bps_if_crossed": 1.0}
    assert _funding_crossed(f, T0.replace(hour=7, minute=55), T0.replace(hour=8, minute=10))
    assert not _funding_crossed(f, T0.replace(hour=8, minute=0), T0.replace(hour=8, minute=15))


def test_bad_bars_rejected_entirely(env):
    p = env.tmp / "bad.csv"
    p.write_text("open_time_utc,open,high,low,close\n2026-10-20T10:00:30Z,1,2,0.5,1.5\n")
    r = import_price_bars(env.conn, str(p), "x", MARKET, T0)
    assert r["inserted"] == 0 and r["errors"]


# ---- evaluation -------------------------------------------------------------
def test_wilson_and_mdd():
    lo, hi = wilson(5, 10)
    assert lo < 0.5 < hi
    assert wilson(0, 0) is None
    assert max_drawdown([5, -3, -4, 2, -1]) == pytest.approx(7)


def test_evaluation_counts_and_disclosure(env):
    from test_critical import _bars_csv, _journal_one
    cfg = load_config(overrides={"evaluation": {"neutral_band_bps": 1.0}})
    _journal_one(env, cfg)
    import_price_bars(env.conn, str(_bars_csv(env.tmp / "b.csv", T0 - timedelta(minutes=30), 60)),
                      "user_csv_1m", MARKET, T0)
    from lar_ofi.journal import resolve_predictions
    resolve_predictions(env.conn, T0 + timedelta(hours=1))
    s1 = evaluate(env.conn, cfg, T0 + timedelta(hours=1))
    seg = s1["segments"]["ALL"]
    assert seg["n_assessments"] == 1 and seg["decisions"]["LONG"] == 1 and seg["coverage"] == 1.0
    assert seg["horizons"]["5"]["directional_accuracy"]["non_overlapping"]["hit"] == 1
    assert seg["horizons"]["5"]["claim"].startswith("IN_SAMPLE_DESCRIPTIVE_ONLY")
    s2 = evaluate(env.conn, cfg, T0 + timedelta(hours=2))
    assert s2["prior_evaluation_runs"] == 1
    assert any("earlier evaluation run" in w for w in s2["warnings"])
    assert "Segment ALL" in render_evaluation_markdown(s2)


def test_chronological_split(env):
    from test_critical import _journal_one
    cfg = load_config(overrides={"evaluation": {"neutral_band_bps": 1.0,
                                                "test_start_utc": "2026-10-20T12:00:00Z"}})
    _journal_one(env, cfg)
    s = evaluate(env.conn, cfg, T0 + timedelta(hours=3))
    assert s["segments"]["DEVELOPMENT"]["n_assessments"] == 1
    assert s["segments"]["TEST"]["n_assessments"] == 0


# ---- L2 math ----------------------------------------------------------------
def test_ofi_contribution_cases():
    a = BookTop(0, 100.0, 5.0, 101.0, 7.0)
    # unchanged prices: e = qb_n - qb_n-1 - qa_n + qa_n-1
    assert ofi_contribution(a, BookTop(1, 100.0, 8.0, 101.0, 7.0)) == pytest.approx(3.0)
    assert ofi_contribution(a, BookTop(1, 100.0, 5.0, 101.0, 4.0)) == pytest.approx(3.0)
    # bid improves: + new bid queue; ask unchanged
    assert ofi_contribution(a, BookTop(1, 100.5, 2.0, 101.0, 7.0)) == pytest.approx(2.0)
    # bid drops: - old bid queue
    assert ofi_contribution(a, BookTop(1, 99.5, 9.0, 101.0, 7.0)) == pytest.approx(-5.0)
    # ask lifted (moves up): + old ask queue
    assert ofi_contribution(a, BookTop(1, 100.0, 5.0, 101.5, 3.0)) == pytest.approx(7.0)
    # ask improves (moves down): - new ask queue
    assert ofi_contribution(a, BookTop(1, 100.0, 5.0, 100.5, 4.0)) == pytest.approx(-4.0)


def test_queue_imbalance_and_ofi_sum():
    tops = [BookTop(0, 100, 5, 101, 5), BookTop(1, 100, 8, 101, 5), BookTop(2, 100, 8, 101, 2)]
    assert ofi(tops) == pytest.approx(3 + 3)
    assert queue_imbalance(BookTop(0, 100, 3, 101, 1)) == pytest.approx(0.5)


def test_price_impact_fit_recovers_slope():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    fit = fit_price_impact(xs, [0.5 * x + 0.1 for x in xs])
    assert fit["beta"] == pytest.approx(0.5) and fit["r2"] == pytest.approx(1.0)


def test_replay_validates_sequence_and_computes_metrics():
    events = [BookSnapshot(0.0, 100, ((100.0, 5.0),), ((101.0, 5.0),)),
              BookDelta(1.0, 101, asks=((101.0, 0.0), (101.5, 3.0))),
              Trade(1.5, 101.5, 3.0, "BUY"),
              BookDelta(2.0, 102, asks=((101.5, 0.0), (102.0, 4.0))),
              BookDelta(3.0, 102, bids=((99.0, 1.0),)),  # stale duplicate id
              BookDelta(5.0, 103, asks=((101.5, 3.0),)),
              BookDelta(11.0, 104, bids=((100.0, 7.0),)),
              BookDelta(21.0, 105, bids=((100.5, 1.0),)),
              BookDelta(31.0, 106, asks=((101.0, 2.0),))]
    stream = replay(events)
    assert stream.report.complete and stream.report.stale_deltas_skipped == 1
    rep = replenishment_times(stream, fraction=0.8, max_wait_s=10)
    assert rep[0]["replenished_after_s"] == pytest.approx(3.5)
    cfg = load_config(overrides={"l2": {"enabled": True}})
    m = compute_l2_metrics(stream, cfg, interval_s=10.0)
    assert m["stream_report"]["complete"] is True
    assert "Cont" in m["labels"]["ofi"]
    assert len(m["ofi_intervals"]) >= 3


def test_delta_before_snapshot_marks_stream_incomplete():
    stream = replay([BookDelta(0.0, 5, bids=((100.0, 1.0),)), BookSnapshot(1.0, 10, ((100.0, 1.0),), ((101.0, 1.0),))])
    assert not stream.report.complete
