"""Setup state machine: LONG/SHORT mirrors, CANDIDATE/INVALIDATED/WAIT
transitions and the rule that weak evidence alone never confirms."""

from __future__ import annotations

from conftest import CONTINUATION_LONG_OBS, FAILED_AUCTION_SHORT_OBS, T0
from lar_ofi.config import load_config
from lar_ofi.engine import assess

MIRROR = {"ABOVE": "BELOW", "BELOW": "ABOVE", "UP": "DOWN", "DOWN": "UP", "BUY_DOMINANT": "SELL_DOMINANT",
          "BUY": "SELL", "RISING": "FALLING", "FALLING": "RISING", "THIN": "THIN", "THICK": "THICK",
          "LONGS_LIQUIDATED": "SHORTS_LIQUIDATED", "ASK_SIDE": "BID_SIDE"}
FIELD_MIRROR = {"passive_liquidity_above": "passive_liquidity_below",
                "ask_side_after_consumption": "bid_side_after_consumption"}


def mirror(spec, keep_oi=False):
    out = []
    for o in spec:
        file_name, field, value = o[:3]
        if field in ("last_price", "prev_vah", "prev_val"):
            continue
        if field == "oi_change" and keep_oi:
            out.append(o)
            continue
        out.append((file_name, FIELD_MIRROR.get(field, field), MIRROR.get(value, value), *o[3:]))
    return out


def run(env, spec, cfg=None, previous_states=None, name="m"):
    ds = env.scenario(spec, name=name)
    return assess(env.engine_input(ds, decision_time=T0, previous_states=previous_states), cfg or env.cfg)


def test_continuation_short_mirror(env):
    a = run(env, mirror(CONTINUATION_LONG_OBS, keep_oi=True))  # OI rising with a sell-off = new shorts
    assert a["setups"]["CONTINUATION"]["state"] == "CONFIRMED_SHORT"
    assert a["decision"] == "SHORT"


def test_failed_auction_long_mirror(env):
    a = run(env, mirror(FAILED_AUCTION_SHORT_OBS))
    assert a["setups"]["FAILED_AUCTION"]["state"] == "CONFIRMED_LONG"
    assert a["decision"] == "LONG"


def test_continuation_candidate_before_acceptance(env):
    spec = [o if o[1] != "closed_bars_outside_value" else (o[0], o[1], 1) for o in CONTINUATION_LONG_OBS]
    a = run(env, spec)
    assert a["setups"]["CONTINUATION"]["state"] == "CANDIDATE_LONG"
    assert a["decision"] == "WAIT"
    assert any(c.startswith("C-2") for c in a["confirmation_condition"])


def test_mere_violation_of_vah_is_not_confirmation(env):
    spec = [("auction_30m.png", "price_vs_prev_value_area", "ABOVE"),
            ("auction_30m.png", "violation_side", "UP")]
    a = run(env, spec)
    assert a["setups"]["CONTINUATION"]["state"] in ("WAIT", "CANDIDATE_LONG")
    assert a["decision"] == "WAIT"


def test_absorbed_buying_invalidates_continuation(env):
    spec = [o if o[1] != "price_response_to_aggression" else (o[0], o[1], "STALLED") for o in CONTINUATION_LONG_OBS]
    a = run(env, spec)
    assert a["setups"]["CONTINUATION"]["state"] == "INVALIDATED"
    assert "C-X2" in a["setups"]["CONTINUATION"]["reason"]
    assert a["decision"] == "WAIT"


def test_previous_candidate_invalidated_when_trigger_lost(env):
    spec = [o if o[1] != "price_vs_prev_value_area" else (o[0], o[1], "INSIDE") for o in CONTINUATION_LONG_OBS]
    spec = [o for o in spec if o[1] not in ("last_price", "closed_bars_outside_value")]
    a = run(env, spec, previous_states={"CONTINUATION": "CANDIDATE_LONG"})
    assert a["setups"]["CONTINUATION"]["state"] == "INVALIDATED"


def test_wick_or_delta_or_absorption_alone_never_confirms_failed_auction(env):
    spec = [("auction_30m.png", "violation_side", "UP"),
            ("auction_30m.png", "price_vs_prev_value_area", "INSIDE"),
            ("auction_30m.png", "returned_inside_value", "YES"),
            ("conf_1m.png", "absorption_signal", "ASK_SIDE"),
            ("flow_5m.png", "footprint_aggression", "SELL_DOMINANT")]
    a = run(env, spec)
    assert a["setups"]["FAILED_AUCTION"]["state"] == "WAIT"
    assert a["decision"] == "WAIT"


def test_failed_auction_needs_replenishment_from_two_snapshots(env):
    spec = [o for o in FAILED_AUCTION_SHORT_OBS if o[1] != "ask_side_after_consumption"]
    a = run(env, spec)
    assert a["setups"]["FAILED_AUCTION"]["state"] == "CANDIDATE_SHORT"
    assert a["decision"] == "WAIT"
    relaxed = load_config(overrides={"thresholds": {"require_resiliency_for_confirmation": False}})
    b = assess(env.engine_input(a["dataset_id"], decision_time=T0), relaxed)
    assert b["decision"] == "SHORT"  # falls back to visible THICK ask liquidity; documented, uncalibrated


def test_failed_auction_invalidated_by_acceptance(env):
    spec = [("auction_30m.png", "violation_side", "UP"), ("auction_30m.png", "price_vs_prev_value_area", "ABOVE"),
            ("auction_30m.png", "closed_bars_outside_value", 2), ("auction_30m.png", "returned_inside_value", "NO"),
            ("flow_5m.png", "aggression_at_extreme", "BUY"), ("flow_5m.png", "price_response_at_extreme", "STALLED")]
    a = run(env, spec)
    assert a["setups"]["FAILED_AUCTION"]["state"] == "INVALIDATED"


def test_opposite_live_setups_give_wait(env):
    # Continuation SHORT candidate (below value, selling) while failed-auction LONG is a candidate.
    spec = [("auction_30m.png", "price_vs_prev_value_area", "BELOW"), ("auction_30m.png", "violation_side", "DOWN"),
            ("auction_30m.png", "closed_bars_outside_value", 1), ("auction_30m.png", "returned_inside_value", "NO"),
            ("flow_5m.png", "footprint_aggression", "SELL_DOMINANT"),
            ("flow_5m.png", "price_response_to_aggression", "ADVANCED"),
            ("flow_5m.png", "aggression_at_extreme", "BUY"),
            ("flow_5m.png", "price_response_at_extreme", "STALLED")]
    a = run(env, spec)
    states = {k: v["state"] for k, v in a["setups"].items()}
    assert a["decision"] == "WAIT"
    assert states["CONTINUATION"] == "CANDIDATE_SHORT"


def test_disabled_layer_observations_are_ignored(env):
    import copy
    from conftest import STANDARD_SHOTS
    shots = copy.deepcopy(STANDARD_SHOTS)
    shots["gex_30m.png"] = {"timeframe": "30M", "indicators": ["GEX"], "offset_s": -25}
    ds = env.scenario(CONTINUATION_LONG_OBS + [("gex_30m.png", "gex_sign", "NEGATIVE")], shots=shots)
    a = assess(env.engine_input(ds, decision_time=T0), env.cfg)
    assert a["decision"] == "LONG"
    assert any(i["reason"] == "LAYER_E_DISABLED" for i in a["ignored_observations"])


def test_probability_is_never_a_number(env):
    a = run(env, CONTINUATION_LONG_OBS)
    assert a["probability"] == "NOT_CALIBRATED"
    assert a["calibration_status"] == "NOT_CALIBRATED"
