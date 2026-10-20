"""Phase 5 regression tests: one or more per audit finding.
Synthetic fixtures only — not evidence of trading performance."""

from __future__ import annotations

import copy
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from conftest import (CONTINUATION_LONG_OBS, FAILED_AUCTION_SHORT_OBS, MARKET, STANDARD_SHOTS, T0, Env, iso,
                      windows_for)
from lar_ofi.config import load_config
from lar_ofi.db import SchemaError, connect
from lar_ofi.engine import assess
from lar_ofi.evaluation import _segment_summary, mcnemar_exact_p, non_overlapping
from lar_ofi.intake import ManifestError
from lar_ofi.journal import (JournalError, import_price_bars, momentum_baseline, record_prediction,
                             resolve_predictions)
from lar_ofi.observations import ObservationError, add_observation, observation_template
from lar_ofi.registry import FIELDS
from lar_ofi.report import build_report


def _assess(env, ds, decision_time=T0, cfg=None):
    inp = env.engine_input(ds, decision_time=decision_time)
    cfg = cfg or env.cfg
    return inp, build_report(assess(inp, cfg), inp, cfg)


def _replace(spec, field, value):
    return [(o[0], o[1], value, *o[3:]) if o[1] == field else o for o in spec]


# ===========================================================================
# P0.1 — three timestamps; lateness measured from data_as_of
# ===========================================================================

def test_p0_report_separates_data_as_of_and_decision_time(env):
    ds = env.scenario(CONTINUATION_LONG_OBS)
    _, r = _assess(env, ds)
    assert r["decision_time_utc"] == iso(T0)
    assert r["data_as_of_utc"] == iso(T0 - timedelta(seconds=10))  # conf_1m.png, newest data-bearing shot
    assert r["data_content_latest_utc"] == iso(T0 - timedelta(seconds=11))
    assert r["data_as_of_basis"] == "USED_SCREENSHOTS"


def test_p0_late_decision_on_old_data_is_refused_even_if_recorded_promptly(env):
    """The old bug: as_of = now made recorded_at - as_of = 0. Now the delay is
    measured from the newest data actually used."""
    ds = env.scenario(CONTINUATION_LONG_OBS)
    decision = T0 + timedelta(seconds=300)
    inp, r = _assess(env, ds, decision_time=decision)
    with pytest.raises(JournalError, match="LATE_RECORDING.*newest data used"):
        record_prediction(env.conn, r, inp, env.cfg, recorded_at=decision + timedelta(seconds=1))
    assert env.conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 0


def test_p0_record_held_back_after_decision_is_refused(env):
    ds = env.scenario(CONTINUATION_LONG_OBS)
    inp, r = _assess(env, ds)
    with pytest.raises(JournalError, match="after the decision time"):
        record_prediction(env.conn, r, inp, env.cfg, recorded_at=T0 + timedelta(seconds=31))
    rec = record_prediction(env.conn, r, inp, env.cfg, recorded_at=T0 + timedelta(seconds=30))
    row = env.conn.execute("SELECT data_as_of_utc, decision_time_utc, recorded_at_utc FROM predictions").fetchone()
    assert tuple(row) == (rec["data_as_of_utc"], rec["decision_time_utc"], rec["recorded_at_utc"])


def test_p0_future_screenshot_does_not_move_data_as_of(env):
    shots = copy.deepcopy(STANDARD_SHOTS)
    shots["late_1m.png"] = {"timeframe": "1M", "indicators": ["Agg. Liquidations"], "offset_s": 120}
    spec = CONTINUATION_LONG_OBS + [("late_1m.png", "liquidations", "NONE_SIGNIFICANT")]
    ds = env.scenario(spec, shots=shots, import_time=T0 + timedelta(minutes=5))
    _, r = _assess(env, ds)
    assert r["data_as_of_utc"] == iso(T0 - timedelta(seconds=10))


def test_p0_stale_screenshots_still_count_for_data_as_of(env):
    ds = env.scenario(CONTINUATION_LONG_OBS)
    _, r = _assess(env, ds, decision_time=T0 + timedelta(hours=1))
    assert r["decision"] == "WAIT"
    assert r["data_as_of_utc"] == iso(T0 - timedelta(seconds=10))
    assert r["data_as_of_basis"] == "DATA_BEARING_NONE_USABLE"


def test_p0_data_as_of_ignores_newer_screenshot_that_was_not_used(env):
    """An excluded (unverifiable) newer screenshot must not make old used data
    look recent: lateness is measured from the newest data actually used."""
    cfg = load_config(overrides={"freshness": {"stale_policy": "exclude"}})
    shots = copy.deepcopy(STANDARD_SHOTS)
    shots["conf_1m.png"]["last_update_offset_s"] = None  # FRESHNESS_UNVERIFIABLE -> excluded
    ds = env.scenario(CONTINUATION_LONG_OBS, shots=shots)
    _, r = _assess(env, ds, cfg=cfg)
    assert r["data_as_of_basis"] == "USED_SCREENSHOTS"
    assert r["data_as_of_utc"] == iso(T0 - timedelta(seconds=15))  # flow_5m.png, not conf_1m.png


def test_p0_no_data_cannot_be_journaled(env):
    res = env.import_(env.manifest())
    inp, r = _assess(env, res.dataset_id)
    with pytest.raises(JournalError, match="NO_DATA_AS_OF"):
        record_prediction(env.conn, r, inp, env.cfg, recorded_at=T0 + timedelta(seconds=1))


def test_p0_v1_journal_is_not_mixed_with_v2(tmp_path):
    db = tmp_path / "old.sqlite"
    raw = sqlite3.connect(db)
    raw.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    raw.execute("INSERT INTO meta VALUES ('schema_version', '1')")
    raw.commit()
    raw.close()
    with pytest.raises(SchemaError, match="schema v1"):
        connect(db)


# ===========================================================================
# P0.2 — momentum baseline uses only prices known at decision time
# ===========================================================================

def _bars_with_jump(path, start, n, jump_bar_open):
    """Falling 1m bars, then one bar that jumps up, then rising bars."""
    lines = ["open_time_utc,open,high,low,close"]
    price = 70000.0
    for i in range(n):
        t = start + timedelta(minutes=i)
        o = price
        if t < jump_bar_open:
            c = o - 10
        elif t == jump_bar_open:
            c = o + 500
        else:
            c = o + 10
        lines.append(f"{iso(t)},{o},{max(o, c) + 1},{min(o, c) - 1},{c}")
        price = c
    path.write_text("\n".join(lines))
    return path


def test_p0_momentum_baseline_between_minute_boundaries_has_no_lookahead(env):
    """Decision 10:09:30, recorded 10:09:35, simulated entry 10:10:00. The 10:09
    bar (closing 10:10) jumps up. The old rule read open(10:10) and would say
    LONG; prices known at 10:09:30 were falling, so the baseline must say SHORT."""
    cfg = load_config(overrides={"evaluation": {"neutral_band_bps": 1.0}})
    ds = env.scenario(CONTINUATION_LONG_OBS)
    inp, r = _assess(env, ds, cfg=cfg)
    record_prediction(env.conn, r, inp, cfg, recorded_at=T0 + timedelta(seconds=5))
    start = datetime(2026, 10, 20, 9, 30, tzinfo=timezone.utc)
    jump = datetime(2026, 10, 20, 10, 9, tzinfo=timezone.utc)
    import_price_bars(env.conn, str(_bars_with_jump(env.tmp / "j.csv", start, 60, jump)), "user_csv_1m",
                      MARKET, T0)
    resolve_predictions(env.conn, T0 + timedelta(hours=1))
    row = env.conn.execute("SELECT * FROM resolutions WHERE horizon_minutes=5").fetchone()
    base = json.loads(row["baselines_json"])["MOMENTUM_SAME_HORIZON"]
    assert base["direction"] == "SHORT"
    assert base["known_at_utc"] == "2026-10-20T10:09:00Z" <= iso(T0)
    assert base["reference_bar_open_utc"] == "2026-10-20T10:08:00Z"
    assert row["entry_time_utc"] == "2026-10-20T10:10:00Z"  # entry stays a separate, later price


def test_p0_momentum_baseline_unit(env):
    import_price_bars(env.conn, str(_bars_with_jump(env.tmp / "j.csv",
                                                    datetime(2026, 10, 20, 9, 30, tzinfo=timezone.utc), 60,
                                                    datetime(2026, 10, 20, 10, 9, tzinfo=timezone.utc))),
                      "src", MARKET, T0)
    m = {**MARKET, "interval": "1m"}
    exactly_on_boundary = momentum_baseline(env.conn, "src", m, datetime(2026, 10, 20, 10, 10, tzinfo=timezone.utc), 5)
    assert exactly_on_boundary["direction"] == "LONG"  # the 10:09 bar has closed at 10:10:00
    assert momentum_baseline(env.conn, "src", m, T0, 5)["direction"] == "SHORT"


# ===========================================================================
# P1 — observation reproducibility
# ===========================================================================

def test_p1_every_enabled_field_has_a_written_procedure():
    for name, spec in FIELDS.items():
        if spec.enabled:
            assert spec.protocol.get("procedure") and spec.protocol.get("unknown_when"), name
            assert spec.protocol.get("measurement"), name


def test_p1_qualitative_fields_declare_the_quantitative_data_they_lack():
    for name in ("passive_liquidity_above", "ask_side_after_consumption", "bid_side_after_consumption"):
        assert FIELDS[name].protocol["measurement"] == "QUALITATIVE_VISUAL"
        assert "L2" in FIELDS[name].protocol["quantitative_data"]


def test_p1_window_fields_require_a_valid_window(env):
    res = env.import_(env.manifest())
    ids = env.shot_ids(res.dataset_id)
    flow = ids["flow_5m.png"]
    with pytest.raises(ObservationError, match="window_start_utc and window_end_utc are required"):
        add_observation(env.conn, res.dataset_id, flow, "cvd_trend", "RISING")
    with pytest.raises(ObservationError, match="bar boundary"):
        add_observation(env.conn, res.dataset_id, flow, "cvd_trend", "RISING",
                        window_start="2026-10-20T09:50:00Z", window_end="2026-10-20T10:06:00Z")
    with pytest.raises(ObservationError, match="after the screenshot was captured"):
        add_observation(env.conn, res.dataset_id, flow, "cvd_trend", "RISING",
                        window_start="2026-10-20T09:50:00Z", window_end="2026-10-20T10:10:00Z")
    # UNKNOWN needs no window
    add_observation(env.conn, res.dataset_id, flow, "cvd_trend", "UNKNOWN")


def test_p1_window_not_ending_at_latest_closed_bar_is_unknown(env):
    shots = STANDARD_SHOTS
    old = dict(windows_for(shots))
    w_end = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)  # one 5M bar too early
    old["flow_5m.png"] = (iso(w_end - timedelta(minutes=15)), iso(w_end))
    e = env
    res = e.import_(e.manifest())
    ids = e.shot_ids(res.dataset_id)
    from conftest import obs_items
    from lar_ofi.observations import add_observations_from_list
    _, errors = add_observations_from_list(e.conn, res.dataset_id, obs_items(CONTINUATION_LONG_OBS, ids, old))
    assert not errors
    _, r = _assess(e, res.dataset_id)
    flow_fields = [f for f in r["resolved_fields"] if f["field"] == "footprint_aggression"][0]
    assert flow_fields["value"] == "UNKNOWN"
    assert any("WINDOW_NOT_LATEST_CLOSED_BAR" in n for n in flow_fields["notes"])
    assert r["decision"] == "WAIT"


@pytest.mark.parametrize("views", [("A", "B"), (None, None)])
def test_p1_heatmap_comparison_needs_identical_view_settings(env, views):
    shots = copy.deepcopy(STANDARD_SHOTS)
    for name, v in zip(("heat_5m_a.png", "heat_5m_b.png"), views):
        shots[name].pop("view_settings")
        if v:
            shots[name]["view_settings"] = v
    ds = env.scenario(CONTINUATION_LONG_OBS, shots=shots)
    _, r = _assess(env, ds)
    assert r["market_state"]["ask_side_visual_change"] == "UNKNOWN"
    assert any("view_settings" in n for n in r["market_state"]["visual_change_notes"])
    assert r["decision"] == "WAIT"


def test_p1_visual_comparison_is_not_labelled_as_resiliency(env):
    ds = env.scenario(CONTINUATION_LONG_OBS)
    _, r = _assess(env, ds)
    assert "ask_side_resiliency" not in r["market_state"]
    c4 = r["setups"]["CONTINUATION"]["variants"]["LONG"]["confirmation"][2]
    assert c4["id"] == "C-4" and "not L2 resiliency" in c4["text"]
    assert "Liquidity Resiliency" in r["market_state"]["l2_metrics"]


def test_p1_template_carries_procedures(env):
    res = env.import_(env.manifest())
    t = observation_template(env.conn, res.dataset_id)
    fp = [i for i in t if i["field"] == "footprint_aggression"][0]
    assert fp["measurement"] == "SIGN_RULE" and "window_start_utc" in fp and fp["procedure"]


# ===========================================================================
# P1 — strategy rules: closed bars, 5M/1M merging, per-layer freshness
# ===========================================================================

@pytest.mark.parametrize("offset,expect", [(-570, "LONG"), (-571, "WAIT")])
def test_p1_30m_screenshot_must_contain_latest_closed_bar(env, offset, expect):
    """T0 = 10:09:30; the last 30M close was 10:00:00 (570 s earlier)."""
    shots = copy.deepcopy(STANDARD_SHOTS)
    shots["auction_30m.png"]["offset_s"] = offset
    ds = env.scenario(CONTINUATION_LONG_OBS, shots=shots)
    _, r = _assess(env, ds)
    assert r["decision"] == expect
    if expect == "WAIT":
        assert any("MISSING_LATEST_CLOSED_BAR" in b for b in r["blocking_issues"])


@pytest.mark.parametrize("offset,expect", [(-270, "LONG"), (-271, "WAIT")])
def test_p1_5m_screenshot_must_contain_latest_closed_bar(env, offset, expect):
    """The last 5M close before T0 was 10:05:00 (270 s earlier). The sync policy
    is widened here so that only the closed-bar rule is exercised."""
    cfg = load_config(overrides={"sync": {"micro_max_skew_seconds": 600}})
    shots = copy.deepcopy(STANDARD_SHOTS)
    shots["flow_5m.png"]["offset_s"] = offset
    ds = env.scenario(CONTINUATION_LONG_OBS, shots=shots)
    _, r = _assess(env, ds, cfg=cfg)
    assert r["decision"] == expect
    if expect == "WAIT":
        assert any("MISSING_LATEST_CLOSED_BAR" in b for b in r["blocking_issues"])


@pytest.mark.parametrize("bars,expect", [(1, "CANDIDATE_LONG"), (2, "CONFIRMED_LONG")])
def test_p1_acceptance_boundary(env, bars, expect):
    ds = env.scenario(_replace(CONTINUATION_LONG_OBS, "closed_bars_outside_value", bars))
    _, r = _assess(env, ds)
    assert r["setups"]["CONTINUATION"]["state"] == expect


def _shots_with_1m_flow():
    shots = copy.deepcopy(STANDARD_SHOTS)
    shots["flow_1m.png"] = {"timeframe": "1M", "indicators": ["Agg. Volume Footprint"], "offset_s": -12}
    return shots


def test_p1_1m_reading_alone_cannot_satisfy_a_5m_condition(env):
    shots = _shots_with_1m_flow()
    spec = [o for o in CONTINUATION_LONG_OBS if o[1] != "price_response_to_aggression"]
    spec += [("flow_1m.png", "price_response_to_aggression", "ADVANCED")]
    ds = env.scenario(spec, shots=shots)
    _, r = _assess(env, ds)
    pr = [f for f in r["resolved_fields"] if f["field"] == "price_response_to_aggression"][0]
    assert pr["value"] == "UNKNOWN" and "decision timeframe 5M" in pr["notes"][-1]
    assert r["setups"]["CONTINUATION"]["state"] == "CANDIDATE_LONG"
    assert r["decision"] == "WAIT"


def test_p1_concordant_1m_reading_adds_no_evidence(env):
    shots = _shots_with_1m_flow()
    ds = env.scenario(CONTINUATION_LONG_OBS + [("flow_1m.png", "price_response_to_aggression", "ADVANCED")],
                      shots=shots)
    _, r = _assess(env, ds)
    pr = [f for f in r["resolved_fields"] if f["field"] == "price_response_to_aggression"][0]
    assert pr["value"] == "ADVANCED" and any("not counted as additional evidence" in n for n in pr["notes"])
    ds2 = env.scenario(CONTINUATION_LONG_OBS, name="only5m")
    _, r2 = _assess(env, ds2)
    count = lambda rep: len([e for e in rep["evidence_for"] if e["statement"].startswith("[")])
    assert r["decision"] == r2["decision"] == "LONG" and count(r) == count(r2)


def test_p1_analysis_timeframe_selects_the_decision_timeframe(env):
    ds = env.scenario(CONTINUATION_LONG_OBS)
    path = env.manifest(name="one_minute", analysis_timeframe="1M")
    res = env.import_(path)
    from conftest import obs_items
    from lar_ofi.observations import add_observations_from_list
    add_observations_from_list(env.conn, res.dataset_id,
                               obs_items(CONTINUATION_LONG_OBS, env.shot_ids(res.dataset_id)))
    _, r_5m = _assess(env, ds)
    _, r_1m = _assess(env, res.dataset_id)
    assert r_5m["decision"] == "LONG"
    assert r_1m["analysis_timeframe"] == "1M" and r_1m["decision"] == "WAIT"  # 5M readings are now secondary


def test_p1_analysis_timeframe_must_be_micro(env):
    with pytest.raises(ManifestError, match="micro timeframes"):
        env.import_(env.manifest(analysis_timeframe="30M"))


def test_p1_failed_auction_still_confirms_under_new_rules(env):
    ds = env.scenario(FAILED_AUCTION_SHORT_OBS)
    _, r = _assess(env, ds)
    assert r["decision"] == "SHORT"


# ===========================================================================
# P1 — evaluation
# ===========================================================================

def test_p1_mcnemar_exact_values():
    assert mcnemar_exact_p(0, 0) == 1.0
    assert mcnemar_exact_p(5, 5) == 1.0
    assert mcnemar_exact_p(10, 0) == pytest.approx(2 / 1024)
    assert mcnemar_exact_p(0, 10) == pytest.approx(2 / 1024)


def _row(i, start, outcome, mom, step_min=1, h=5):
    entry = start + timedelta(minutes=i * step_min)
    return {"prediction_id": f"p{i:03d}", "recorded_at": iso(entry), "decision": "LONG", "active_setup": "X",
            "market_state": "S", "regime_tag": "T", "data_status": "SUFFICIENT", "conflict": False,
            "config_sha256": "c" * 64, "rules_applied": ["D5"], "missing": [],
            "rule": {"cost_model": None, "horizons_minutes": [h]},
            "res": {h: {"outcome": outcome, "entry_time_utc": iso(entry),
                        "exit_time_utc": iso(entry + timedelta(minutes=h)), "net_return_bps": None,
                        "baselines_json": json.dumps({"MOMENTUM_SAME_HORIZON": {"outcome": mom},
                                                      "ALWAYS_LONG": {"outcome": outcome}})}}}


def test_p1_overlapping_predictions_are_thinned():
    start = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
    rows = [_row(i, start, "HIT", "MISS", step_min=1) for i in range(10)]  # 1 min apart, 5 min horizon
    kept = non_overlapping(rows, 5)
    assert [r["prediction_id"] for r in kept] == ["p000", "p005"]
    seg = _segment_summary(rows, [5], min_n=1, independent=True, alpha=0.05)
    ov = seg["horizons"]["5"]["overlap"]
    assert (ov["n_scored"], ov["n_non_overlapping"], ov["n_in_overlapping_windows"]) == (10, 2, 10)


def test_p1_high_accuracy_equal_to_baseline_is_not_an_edge():
    """100% hits, but ALWAYS_LONG hits on exactly the same calls: the paired
    test has no discordant pairs, so there is no evidence of an edge (the old
    Wilson-vs-point rule compared an interval with a point estimate)."""
    start = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
    rows = [_row(i, start, "HIT", "HIT", step_min=5) for i in range(200)]
    seg = _segment_summary(rows, [5], min_n=100, independent=True, alpha=0.05)
    assert seg["horizons"]["5"]["claim"].startswith("NO_EVIDENCE_OF_EDGE")


def test_p1_claim_only_from_independent_segment_and_bonferroni():
    start = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
    rows = []
    for i in range(200):
        r = _row(i, start, "HIT", "MISS", step_min=5)
        base = json.loads(r["res"][5]["baselines_json"])
        base["ALWAYS_LONG"]["outcome"] = "MISS"
        r["res"][5]["baselines_json"] = json.dumps(base)
        rows.append(r)
    dev = _segment_summary(rows, [5], min_n=100, independent=False, alpha=0.05)
    test = _segment_summary(rows, [5], min_n=100, independent=True, alpha=0.05)
    assert dev["horizons"]["5"]["claim"].startswith("IN_SAMPLE_DESCRIPTIVE_ONLY")
    claim = test["horizons"]["5"]["claim"]
    assert claim.startswith("PRELIMINARY_ONLY") and "Bonferroni over 2" in claim
    assert "not evidence of after-cost profitability" in claim
    assert test["horizons"]["5"]["after_costs"]["non_overlapping"]["status"] == "NO_COST_MODEL"


def test_p1_insufficient_non_overlapping_sample():
    start = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
    rows = [_row(i, start, "HIT", "MISS", step_min=1) for i in range(150)]  # 150 calls, 30 non-overlapping
    seg = _segment_summary(rows, [5], min_n=100, independent=True, alpha=0.05)
    assert seg["horizons"]["5"]["claim"].startswith("INSUFFICIENT_SAMPLE: 30 decided non-overlapping")


# ===========================================================================
# P2 — data integrity
# ===========================================================================

def test_p2_bars_of_another_market_never_settle_a_prediction(env):
    from test_critical import _bars_csv, _journal_one
    cfg = load_config(overrides={"evaluation": {"neutral_band_bps": 1.0}})
    _journal_one(env, cfg)
    eth = {"instrument": "ETHUSDT", "exchange": "Bybit", "contract_type": "USDT_PERPETUAL"}
    import_price_bars(env.conn, str(_bars_csv(env.tmp / "b.csv", T0 - timedelta(minutes=30), 60)),
                      "user_csv_1m", eth, T0)
    out = resolve_predictions(env.conn, T0 + timedelta(hours=1))
    assert out["resolved"] == [] and all("MISSING_BARS" in p["reason"] for p in out["pending"])
    spot = {"instrument": "BTCUSDT", "exchange": "Bybit", "contract_type": "SPOT"}
    import_price_bars(env.conn, str(env.tmp / "b.csv"), "user_csv_1m", spot, T0)
    assert resolve_predictions(env.conn, T0 + timedelta(hours=1))["resolved"] == []


def test_p2_bar_market_must_be_declared_and_consistent(env):
    p = env.tmp / "s.csv"
    p.write_text("open_time_utc,open,high,low,close\n2026-10-20T10:00:00Z,1,2,0.5,1.5\n")
    with pytest.raises(JournalError, match="MARKET_UNDECLARED"):
        import_price_bars(env.conn, str(p), "x", None, T0)
    q = env.tmp / "t.csv"
    q.write_text("open_time_utc,open,high,low,close,symbol,exchange,contract_type\n"
                 "2026-10-20T10:00:00Z,1,2,0.5,1.5,ETHUSDT,Bybit,USDT_PERPETUAL\n")
    r = import_price_bars(env.conn, str(q), "x", MARKET, T0)
    assert r["inserted"] == 0 and "differs from declared" in r["errors"][0]
    r2 = import_price_bars(env.conn, str(q), "x", None, T0)
    assert r2["markets"] == [{"instrument": "ETHUSDT", "exchange": "BYBIT", "contract_type": "USDT_PERPETUAL"}]


def test_p2_missing_last_update_cannot_pass_as_fresh(env):
    shots = copy.deepcopy(STANDARD_SHOTS)
    shots["flow_5m.png"]["last_update_offset_s"] = None
    ds = env.scenario(CONTINUATION_LONG_OBS, shots=shots)
    _, r = _assess(env, ds)
    assert r["decision"] == "WAIT"
    assert any("FRESHNESS_UNVERIFIABLE" in b for b in r["blocking_issues"])


def test_p2_user_live_attestation_is_accepted_and_recorded(env):
    shots = copy.deepcopy(STANDARD_SHOTS)
    shots["flow_5m.png"]["last_update_offset_s"] = None
    shots["flow_5m.png"]["live_feed_confirmed"] = True
    ds = env.scenario(CONTINUATION_LONG_OBS, shots=shots)
    inp, r = _assess(env, ds)
    assert r["decision"] == "LONG"
    flow = [s for s in inp["screenshots"] if s["file_name"] == "flow_5m.png"][0]
    assert flow["live_feed_confirmed"] is True and "user attests live feed" in flow["issues"][-1]


def test_p2_live_attestation_must_be_boolean(env):
    shots = copy.deepcopy(STANDARD_SHOTS)
    shots["flow_5m.png"]["live_feed_confirmed"] = "yes"
    res = env.import_(env.manifest(shots))
    assert any("LIVE_FEED_CONFIRMED_NOT_BOOLEAN" in i for r in res.rejected for i in r["issues"])


def test_p2_require_update_evidence_can_be_disabled_explicitly(env):
    cfg = load_config(overrides={"freshness": {"require_update_evidence": False}})
    shots = copy.deepcopy(STANDARD_SHOTS)
    shots["flow_5m.png"]["last_update_offset_s"] = None
    ds = env.scenario(CONTINUATION_LONG_OBS, shots=shots)
    _, r = _assess(env, ds, cfg=cfg)
    assert r["decision"] == "LONG"


def test_env_helper_is_isolated(tmp_path):
    e = Env(tmp_path)
    assert e.conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "2"


def test_p1_protocol_document_is_generated_from_registry():
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("gen_protocol_doc", root / "scripts" / "gen_protocol_doc.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert (root / "PROTOKOL_OBSERWACJI.md").read_text(encoding="utf-8") == mod.render()
