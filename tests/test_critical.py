"""The 14 critical situations required by the task (section 10).
Synthetic fixtures only — not evidence of trading performance."""

from __future__ import annotations

import copy
import json
import sqlite3
from datetime import timedelta

import pytest

from conftest import CONTINUATION_LONG_OBS, MARKET, STANDARD_SHOTS, T0, Env, windows_for
from lar_ofi.config import canonical_json, load_config
from lar_ofi.engine import assess
from lar_ofi.evaluation import evaluate
from lar_ofi.intake import ManifestError
from lar_ofi.journal import (JournalError, import_price_bars, record_prediction, resolve_predictions,
                             verify_journal)
from lar_ofi.l2 import (BookDelta, BookSnapshot, InsufficientL2Data, L2DataUnavailable, L2Disabled, Trade,
                        compute_l2_metrics, replay, replenishment_times)
from lar_ofi.observations import ObservationError, add_observation
from lar_ofi.report import build_report


def run(env: Env, dataset_id, decision_time=T0, cfg=None, previous_states=None):
    cfg = cfg or env.cfg
    inp = env.engine_input(dataset_id, decision_time=decision_time, previous_states=previous_states)
    return inp, assess(inp, cfg)


def without(spec, *fields):
    return [o for o in spec if o[1] not in fields]


def replace(spec, field, value):
    return [(o[0], o[1], value, *o[3:]) if o[1] == field else o for o in spec]


# 1 ---------------------------------------------------------------------------
def test_01_no_screenshots_gives_wait(env):
    res = env.import_(env.manifest(shots={}))
    assert res.status == "NO_SCREENSHOTS"
    _, a = run(env, res.dataset_id)
    assert a["decision"] == "WAIT"
    assert a["data_status"] == "NO_DATA"
    assert "NO_SCREENSHOTS" in a["blocking_issues"]


def test_01b_screenshots_without_observations_give_wait(env):
    res = env.import_(env.manifest())
    _, a = run(env, res.dataset_id)
    assert a["decision"] == "WAIT"
    assert a["data_status"] == "NO_DATA"


# 2 ---------------------------------------------------------------------------
@pytest.mark.parametrize("key,value", [("instrument", "ETHUSDT"), ("exchange", "Binance"),
                                       ("contract_type", "SPOT")])
def test_02_wrong_instrument_dataset_rejected(env, key, value):
    with pytest.raises(ManifestError, match=f"WRONG_{key.upper()}"):
        env.import_(env.manifest(**{key: value}))
    assert env.conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0] == 0


def test_02b_screenshot_of_wrong_instrument_rejected(env):
    shots = copy.deepcopy(STANDARD_SHOTS)
    shots["flow_5m.png"]["chart_instrument"] = "ETHUSDT"
    res = env.import_(env.manifest(shots))
    rejected = {r["file_name"]: r["issues"] for r in res.rejected}
    assert "flow_5m.png" in rejected
    assert any(i.startswith("WRONG_INSTRUMENT") for i in rejected["flow_5m.png"])
    assert "flow_5m.png" not in env.shot_ids(res.dataset_id)


# 3 ---------------------------------------------------------------------------
def test_03_missing_timestamp_gives_insufficient_data(env):
    shots = copy.deepcopy(STANDARD_SHOTS)
    shots["flow_5m.png"]["offset_s"] = None
    ds = env.scenario(CONTINUATION_LONG_OBS, shots=shots)
    _, a = run(env, ds)
    assert a["data_status"] == "INSUFFICIENT_DATA"
    assert a["decision"] == "WAIT"
    assert any("TIMESTAMP_MISSING" in b for b in a["blocking_issues"])


def test_03b_naive_timestamp_is_rejected_not_guessed(env):
    shots = copy.deepcopy(STANDARD_SHOTS)
    path = env.manifest(shots)
    m = json.loads(path.read_text())
    m["screenshots"][0]["captured_at_utc"] = "2026-10-20T09:59:00"  # no zone: UTC or Warsaw?
    path.write_text(json.dumps(m))
    res = env.import_(path)
    assert any(any("TIMESTAMP_INVALID" in i for i in r["issues"]) for r in res.rejected)


# 4 ---------------------------------------------------------------------------
def test_04_stale_data_gives_wait_under_block_policy(env):
    ds = env.scenario(CONTINUATION_LONG_OBS)
    _, fresh = run(env, ds, decision_time=T0)
    assert fresh["decision"] == "LONG"
    _, stale = run(env, ds, decision_time=T0 + timedelta(minutes=20))
    assert stale["decision"] == "WAIT"
    assert any(b.startswith("STALE") for b in stale["blocking_issues"])


def test_04b_stale_data_excluded_under_exclude_policy(env):
    cfg = load_config(overrides={"freshness": {"stale_policy": "exclude"}})
    ds = env.scenario(CONTINUATION_LONG_OBS)
    _, a = run(env, ds, decision_time=T0 + timedelta(minutes=20), cfg=cfg)
    assert a["decision"] == "WAIT"
    assert a["blocking_issues"] == []
    assert {e["file_name"] for e in a["excluded_screenshots"]} >= {"flow_5m.png", "conf_1m.png"}


def test_04c_chart_not_updated_gives_wait(env):
    shots = copy.deepcopy(STANDARD_SHOTS)
    shots["flow_5m.png"]["last_update_offset_s"] = -15 - 600  # data 10 min older than the screenshot
    ds = env.scenario(CONTINUATION_LONG_OBS, shots=shots)
    _, a = run(env, ds)
    assert a["decision"] == "WAIT"
    assert any("DATA_NOT_UPDATED" in b for b in a["blocking_issues"])


def test_04d_unsynchronised_screenshots_give_wait(env):
    shots = copy.deepcopy(STANDARD_SHOTS)
    shots["conf_1m.png"]["offset_s"] = -10
    shots["flow_5m.png"]["offset_s"] = -250  # fresh, after the 10:05 close, but 240 s apart from conf_1m
    ds = env.scenario(CONTINUATION_LONG_OBS, shots=shots)
    _, a = run(env, ds)
    assert a["decision"] == "WAIT"
    assert any(b.startswith("UNSYNCHRONISED") for b in a["blocking_issues"])


# 5 ---------------------------------------------------------------------------
def test_05_conflicting_aggression_sources_give_wait(env):
    ds = env.scenario(replace(CONTINUATION_LONG_OBS, "cvd_trend", "FALLING"))
    _, a = run(env, ds)
    assert a["decision"] == "WAIT"
    assert "AGGRESSION_SOURCES_DISAGREE" in {c["code"] for c in a["conflicts"]}


def test_05b_conflicting_readings_across_timeframes_give_wait(env):
    shots = copy.deepcopy(STANDARD_SHOTS)
    shots["flow_1m.png"] = {"timeframe": "1M", "indicators": ["Agg. Volume Footprint"], "offset_s": -12}
    spec = CONTINUATION_LONG_OBS + [("flow_1m.png", "price_response_to_aggression", "REVERSED")]
    ds = env.scenario(spec, shots=shots)
    _, a = run(env, ds)
    assert a["decision"] == "WAIT"
    assert "READINGS_DISAGREE" in {c["code"] for c in a["conflicts"]}


def test_05c_price_inconsistent_with_value_area_gives_wait(env):
    ds = env.scenario(replace(CONTINUATION_LONG_OBS, "last_price", 67000.0))  # inside VA but recorded ABOVE
    _, a = run(env, ds)
    assert a["decision"] == "WAIT"
    assert "PRICE_POSITION_MISMATCH" in {c["code"] for c in a["conflicts"]}


# 6 ---------------------------------------------------------------------------
def test_06_unreadable_values_become_unknown(env):
    spec = [o for o in CONTINUATION_LONG_OBS if o[1] != "oi_change"]
    ds = env.scenario(spec)
    ids = env.shot_ids(ds)
    oid = add_observation(env.conn, ds, ids["flow_5m.png"], "oi_change", "RISING", readability="UNREADABLE")
    stored = env.conn.execute("SELECT value_json FROM observations WHERE observation_id=?", (oid,)).fetchone()
    assert json.loads(stored[0]) == "UNKNOWN"
    _, a = run(env, ds)
    assert a["market_state"]["oi_change"] == "UNKNOWN"
    assert a["setups"]["CONTINUATION"]["state"] == "CANDIDATE_LONG"  # cannot confirm without OI
    assert a["decision"] == "WAIT"


def test_06b_uncertain_reading_treated_as_unknown_by_default(env):
    spec = [o for o in CONTINUATION_LONG_OBS if o[1] != "oi_change"]
    ds = env.scenario(spec)
    w = windows_for(STANDARD_SHOTS)["flow_5m.png"]
    add_observation(env.conn, ds, env.shot_ids(ds)["flow_5m.png"], "oi_change", "RISING", readability="UNCERTAIN",
                    window_start=w[0], window_end=w[1])
    _, a = run(env, ds)
    assert a["market_state"]["oi_change"] == "UNKNOWN"
    assert a["decision"] == "WAIT"
    cfg = load_config(overrides={"observations": {"use_uncertain": True}})
    _, b = run(env, ds, cfg=cfg)
    assert b["decision"] == "LONG"


# 7 ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["ofi", "queue_imbalance", "liquidity_resiliency"])
def test_07_l2_quantities_cannot_be_entered_from_screenshots(env, name):
    res = env.import_(env.manifest())
    with pytest.raises(ObservationError, match="L2"):
        add_observation(env.conn, res.dataset_id, env.shot_ids(res.dataset_id)["heat_5m_b.png"], name, 0.5)


def test_07b_screenshot_mode_reports_no_ofi(env):
    ds = env.scenario(CONTINUATION_LONG_OBS)
    inp, a = run(env, ds)
    assert a["market_state"]["l2_metrics"].startswith("DISABLED")
    report = build_report(a, inp, env.cfg)
    assert "ofi_intervals" not in canonical_json(report)
    assert "queue_imbalance_last" not in canonical_json(report)


def test_07c_l2_metrics_refuse_without_data(env):
    with pytest.raises(L2Disabled):
        compute_l2_metrics(None, env.cfg)
    enabled = load_config(overrides={"l2": {"enabled": True}})
    with pytest.raises(L2DataUnavailable):
        compute_l2_metrics(None, enabled)
    gappy = replay([BookSnapshot(0.0, 10, ((100.0, 1.0),), ((101.0, 1.0),)),
                    BookDelta(1.0, 12, bids=((100.0, 2.0),))])
    assert gappy.report.gaps == [(11, 12)]
    with pytest.raises(L2DataUnavailable):
        compute_l2_metrics(gappy, enabled)


# 8 ---------------------------------------------------------------------------
def test_08_single_snapshot_cannot_measure_replenishment(env):
    res = env.import_(env.manifest())
    ids = env.shot_ids(res.dataset_id)
    with pytest.raises(ObservationError, match="single snapshot"):
        add_observation(env.conn, res.dataset_id, ids["heat_5m_b.png"], "ask_side_after_consumption",
                        "NOT_REPLENISHED")


def test_08b_comparison_against_non_heatmap_is_not_measurable(env):
    spec = [o if o[1] != "ask_side_after_consumption" else (*o[:3], "flow_5m.png") for o in CONTINUATION_LONG_OBS]
    ds = env.scenario(spec)
    _, a = run(env, ds)
    assert a["market_state"]["ask_side_visual_change"] == "UNKNOWN"
    assert any("VISUAL_CHANGE_NOT_ASSESSABLE" in n for n in a["market_state"]["visual_change_notes"])
    assert a["setups"]["CONTINUATION"]["state"] == "CANDIDATE_LONG"
    assert a["decision"] == "WAIT"


def test_08c_comparison_with_later_screenshot_is_not_measurable(env):
    spec = [o if o[1] != "ask_side_after_consumption" else ("heat_5m_a.png", o[1], o[2], "heat_5m_b.png")
            for o in CONTINUATION_LONG_OBS]
    ds = env.scenario(spec)
    _, a = run(env, ds)
    assert a["market_state"]["ask_side_visual_change"] == "UNKNOWN"
    assert a["decision"] == "WAIT"


def test_08d_l2_single_snapshot_cannot_measure_replenishment():
    stream = replay([BookSnapshot(0.0, 1, ((100.0, 5.0),), ((101.0, 5.0),)), Trade(0.5, 101.0, 5.0, "BUY")])
    with pytest.raises(InsufficientL2Data):
        replenishment_times(stream, fraction=0.8, max_wait_s=30)


# 9 ---------------------------------------------------------------------------
def test_09_concordant_cvd_and_footprint_are_one_evidence_group(env):
    ds_both = env.scenario(CONTINUATION_LONG_OBS, name="both")
    ds_fp = env.scenario(without(CONTINUATION_LONG_OBS, "cvd_trend"), name="fponly")
    _, both = run(env, ds_both)
    _, fp = run(env, ds_fp)
    assert both["market_state"]["trade_aggression"] == "BUY"
    assert any("ONE evidence group" in n for n in both["market_state"]["trade_aggression_notes"])
    # Adding concordant CVD does not add a confirmation: same decision, same number of
    # supporting condition items, and exactly one trade-aggression condition.
    assert both["decision"] == fp["decision"] == "LONG"
    conds = lambda a: [e for e in a["evidence_for"] if e["statement"].startswith("[")]
    assert len(conds(both)) == len(conds(fp))
    aggr_items = [e for e in conds(both) if "trade aggression" in e["statement"]]
    assert len(aggr_items) == 1


# 10 --------------------------------------------------------------------------
def _bars_csv(path, start, n, price=68000.0, step=10.0):
    start = start.replace(second=0)  # bars open on whole minutes
    lines = ["open_time_utc,open,high,low,close"]
    for i in range(n):
        o = price + step * i
        lines.append(f"{(start + timedelta(minutes=i)).strftime('%Y-%m-%dT%H:%M:%SZ')},{o},{o + step + 5},{o - 5},{o + step}")
    path.write_text("\n".join(lines))
    return path


def _journal_one(env, cfg, obs=CONTINUATION_LONG_OBS):
    ds = env.scenario(obs)
    inp = env.engine_input(ds, decision_time=T0)
    report = build_report(assess(inp, cfg), inp, cfg)
    return record_prediction(env.conn, report, inp, cfg, recorded_at=T0 + timedelta(seconds=5))


def test_10_no_cost_config_means_no_profitability_claim(env):
    rec = _journal_one(env, env.cfg)
    assert rec["resolution_rule"]["cost_model"] is None
    import_price_bars(env.conn, str(_bars_csv(env.tmp / "b.csv", T0 - timedelta(minutes=30), 60)),
                      "user_csv_1m", MARKET, T0)
    resolve_predictions(env.conn, T0 + timedelta(hours=1))
    rows = env.conn.execute("SELECT outcome, net_return_bps FROM resolutions").fetchall()
    assert rows and all(r["net_return_bps"] is None for r in rows)
    assert all(r["outcome"] == "UNSCORABLE" for r in rows)  # no neutral band either -> not scored
    s = evaluate(env.conn, env.cfg, T0 + timedelta(hours=1))
    for h in s["segments"]["ALL"]["horizons"].values():
        assert h["after_costs"]["non_overlapping"]["status"] == "NO_COST_MODEL"


def test_10b_cost_model_only_from_explicit_user_values(env):
    assert load_config()["costs"].get("taker_fee_bps") is None  # nothing shipped
    cfg = load_config(overrides={"costs": {"taker_fee_bps": 1.0, "spread_bps": 0.2, "slippage_bps": 0.5}})
    rec = _journal_one(env, cfg)
    assert rec["resolution_rule"]["cost_model"]["round_trip_bps"] == pytest.approx(1 + 1 + 0.2 + 1.0)
    import_price_bars(env.conn, str(_bars_csv(env.tmp / "b.csv", T0 - timedelta(minutes=30), 60)),
                      "user_csv_1m", MARKET, T0)
    resolve_predictions(env.conn, T0 + timedelta(hours=1))
    s = evaluate(env.conn, cfg, T0 + timedelta(hours=1))
    assert s["segments"]["ALL"]["horizons"]["5"]["after_costs"]["non_overlapping"]["status"] == "COST_MODEL_PRESENT"


# 11 --------------------------------------------------------------------------
def test_11_recorded_prediction_and_result_cannot_be_changed(env):
    cfg = load_config(overrides={"evaluation": {"neutral_band_bps": 2.0}})
    rec = _journal_one(env, cfg)
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        env.conn.execute("UPDATE predictions SET decision='SHORT' WHERE prediction_id=?", (rec["prediction_id"],))
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        env.conn.execute("DELETE FROM predictions")
    import_price_bars(env.conn, str(_bars_csv(env.tmp / "b.csv", T0 - timedelta(minutes=30), 60)),
                      "user_csv_1m", MARKET, T0)
    resolve_predictions(env.conn, T0 + timedelta(hours=1))
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        env.conn.execute("UPDATE resolutions SET outcome='HIT'")
    again = resolve_predictions(env.conn, T0 + timedelta(hours=2))
    assert again["resolved"] == []  # already resolved; nothing re-scored
    assert verify_journal(env.conn) == []


def test_11b_tampering_outside_sqlite_triggers_is_detected(env):
    rec = _journal_one(env, env.cfg)
    env.conn.execute("DROP TRIGGER predictions_no_update")
    env.conn.execute("UPDATE predictions SET decision='SHORT' WHERE prediction_id=?", (rec["prediction_id"],))
    problems = verify_journal(env.conn)
    assert problems and "content hash mismatch" in problems[0]


# 12 --------------------------------------------------------------------------
def test_12_future_screenshots_do_not_affect_earlier_decision(env):
    shots = copy.deepcopy(STANDARD_SHOTS)
    shots["later_30m.png"] = {"timeframe": "30M", "indicators": ["Agg. TPO"], "offset_s": 600}
    spec = CONTINUATION_LONG_OBS + [("later_30m.png", "returned_inside_value", "YES")]
    ds = env.scenario(spec, shots=shots, import_time=T0 + timedelta(minutes=15))  # historical re-analysis
    _, a = run(env, ds, decision_time=T0)
    assert a["decision"] == "LONG"
    assert any("FUTURE_DATA" in r for e in a["excluded_screenshots"] for r in e["reasons"])
    _, later = run(env, ds, decision_time=T0 + timedelta(seconds=600))
    assert later["decision"] == "WAIT"


def test_12b_journal_rejects_future_or_late_recording(env):
    ds = env.scenario(CONTINUATION_LONG_OBS)
    inp = env.engine_input(ds, decision_time=T0)
    report = build_report(assess(inp, env.cfg), inp, env.cfg)
    with pytest.raises(JournalError, match="TIME_ORDER_VIOLATION"):
        record_prediction(env.conn, report, inp, env.cfg, recorded_at=T0 - timedelta(seconds=1))
    with pytest.raises(JournalError, match="LATE_RECORDING"):
        record_prediction(env.conn, report, inp, env.cfg, recorded_at=T0 + timedelta(minutes=10))


def test_12c_resolution_entry_is_after_recording_and_baseline_uses_past_only(env):
    cfg = load_config(overrides={"evaluation": {"neutral_band_bps": 1.0}})
    _journal_one(env, cfg)  # decision at T0 = 10:09:30, recorded at 10:09:35
    import_price_bars(env.conn, str(_bars_csv(env.tmp / "b.csv", T0 - timedelta(minutes=30), 60)),
                      "user_csv_1m", MARKET, T0)
    resolve_predictions(env.conn, T0 + timedelta(hours=1))
    r = env.conn.execute("SELECT * FROM resolutions WHERE horizon_minutes=5").fetchone()
    assert r["entry_time_utc"] == "2026-10-20T10:10:00Z"  # first full minute after recording
    assert r["exit_time_utc"] == "2026-10-20T10:15:00Z"
    base = json.loads(r["baselines_json"])["MOMENTUM_SAME_HORIZON"]
    assert base["direction"] == "LONG"  # rising synthetic bars before entry


# 13 --------------------------------------------------------------------------
def test_13_reimport_same_dataset_creates_no_duplicates(env):
    path = env.manifest()
    first = env.import_(path)
    counts = [env.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("datasets", "screenshots")]
    second = env.import_(path)
    assert second.dataset_id == first.dataset_id
    assert second.created is False
    assert [env.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("datasets", "screenshots")] == counts


def test_13b_reimport_price_bars_creates_no_duplicates(env):
    csv = _bars_csv(env.tmp / "b.csv", T0, 10)
    a = import_price_bars(env.conn, str(csv), "user_csv_1m", MARKET, T0)
    b = import_price_bars(env.conn, str(csv), "user_csv_1m", MARKET, T0)
    assert (a["inserted"], b["inserted"], b["duplicates"]) == (10, 0, 10)
    assert env.conn.execute("SELECT COUNT(*) FROM price_bars").fetchone()[0] == 10


def test_13c_duplicate_file_inside_one_dataset_rejected(env, tmp_path):
    from conftest import png_bytes
    content = png_bytes(4242)
    shots = {"a.png": {"timeframe": "5M", "indicators": ["Agg. CVD"], "offset_s": -5, "content": content},
             "b.png": {"timeframe": "5M", "indicators": ["Agg. CVD"], "offset_s": -5, "content": content}}
    res = env.import_(env.manifest(shots))
    assert len(res.accepted) == 1
    assert "DUPLICATE_FILE_IN_DATASET" in res.rejected[0]["issues"]


# 14 --------------------------------------------------------------------------
def test_14_identical_inputs_identical_outputs(env, tmp_path):
    ds = env.scenario(CONTINUATION_LONG_OBS)
    inp = env.engine_input(ds)
    out1 = canonical_json(assess(copy.deepcopy(inp), env.cfg))
    out2 = canonical_json(assess(copy.deepcopy(inp), env.cfg))
    assert out1 == out2
    # an independent database built from identical files and observations
    other = Env(tmp_path / "other")
    (tmp_path / "other").mkdir(exist_ok=True)
    other.tmp = tmp_path / "other"
    other.data_dir = other.tmp / "data"
    ds2 = other.scenario(CONTINUATION_LONG_OBS)
    assert ds2 == ds
    assert canonical_json(assess(other.engine_input(ds2), other.cfg)) == out1
