"""Market State Engine.

Pure function: assess(engine_input, config) -> assessment dict. No I/O, no
clock, no randomness, so identical inputs always give identical outputs.

Pipeline:
  1. screenshot usability (timestamp, future data, freshness, update lag)
  2. synchronisation of capture times inside each timeframe group
  3. observation filtering (readability, verification, disabled layers,
     comparison validity for resiliency fields)
  4. field resolution per scope (CONTEXT=4H, AUCTION=30M, MICRO=5M+1M);
     disagreeing readings -> CONFLICT
  5. consistency checks between fields
  6. derived market-state components (each tagged OBSERVED/INFERRED/...)
  7. setup evaluation and decision (lar_ofi.setups / lar_ofi.decision)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lar_ofi import ENGINE_VERSION
from lar_ofi.enums import CONFLICT, UNKNOWN, DataStatus, EvidenceKind
from lar_ofi.registry import (FIELDS, GROUP_TRADE_AGGRESSION, INDICATORS)
from lar_ofi.timeutil import floor_bar, fmt_utc, parse_utc

SCOPE_CONTEXT = "CONTEXT"
SCOPE_AUCTION = "AUCTION"
SCOPE_MICRO = "MICRO"
SCOPE_DERIVED = "DERIVED"

HEATMAP = "Agg. Order Book Heatmap"

# Micro fields used by setup conditions. They must be read on the decision
# timeframe; another micro timeframe can only contradict them.
GATING_MICRO_FIELDS = frozenset({
    "footprint_aggression", "cvd_trend", "price_response_to_aggression", "aggression_at_extreme",
    "price_response_at_extreme", "oi_change", "ask_side_after_consumption", "bid_side_after_consumption",
    "passive_liquidity_above", "passive_liquidity_below"})


def scope_of(timeframe: str, cfg: dict) -> str | None:
    tfs = cfg["timeframes"]
    if timeframe in tfs["context"]:
        return SCOPE_CONTEXT
    if timeframe in tfs["auction"]:
        return SCOPE_AUCTION
    if timeframe in tfs["micro"]:
        return SCOPE_MICRO
    return None


@dataclass
class Resolved:
    field: str
    scope: str
    value: object = UNKNOWN
    observation_ids: list[int] = field(default_factory=list)
    screenshot_ids: list[str] = field(default_factory=list)
    readings: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "field": self.field,
            "scope": self.scope,
            "value": self.value,
            "observation_ids": self.observation_ids,
            "screenshot_ids": self.screenshot_ids,
            "readings": self.readings,
            "notes": self.notes,
        }


class Facts:
    """Read-only view of resolved fields used by setup rules."""

    def __init__(self, resolved: dict[tuple[str, str], Resolved]):
        self._r = resolved

    def get(self, field_name: str, scope: str) -> Resolved:
        return self._r.get((field_name, scope)) or Resolved(field_name, scope)

    def value(self, field_name: str, scope: str):
        return self.get(field_name, scope).value

    def refs(self, keys) -> tuple[list[int], list[str]]:
        obs, shots = set(), set()
        for f, s in keys:
            r = self.get(f, s)
            obs.update(r.observation_ids)
            shots.update(r.screenshot_ids)
        return sorted(obs), sorted(shots)

    def items(self):
        return sorted(self._r.items())


def evidence(kind: EvidenceKind, statement: str, facts: Facts | None = None, keys=(), group: str | None = None,
             stance: str | None = None) -> dict:
    obs, shots = facts.refs(keys) if facts is not None else ([], [])
    return {
        "kind": kind.value,
        "statement": statement,
        "fields": [f"{f}@{s}" for f, s in keys],
        "observation_ids": obs,
        "screenshot_ids": shots,
        "source_group": group,
        "stance": stance,
    }


# --------------------------------------------------------------------------
# 1-2: screenshot usability and synchronisation
# --------------------------------------------------------------------------

def _baseline_only_ids(inp: dict) -> set[str]:
    """Screenshots used only as the EARLIER side of a heatmap comparison.
    They are older by design; their age is bounded by
    resiliency_max_gap_seconds instead of the freshness/sync policy."""
    referenced = {o["compared_with_screenshot_id"] for o in inp["observations"] if o["compared_with_screenshot_id"]}
    with_own = {o["screenshot_id"] for o in inp["observations"]}
    return referenced - with_own


def _screen_screenshots(inp: dict, cfg: dict, decision_time):
    fresh = cfg["freshness"]
    baseline_only = _baseline_only_ids(inp)
    # Only screenshots that carry observations can block a decision; an
    # unused screenshot is reported but contributes no data.
    data_bearing = {o["screenshot_id"] for o in inp["observations"]}
    policy = fresh["stale_policy"]
    closed_bar_tfs = set(fresh["require_latest_closed_bar"])
    usable: dict[str, dict] = {}
    excluded: list[dict] = []
    blocking: list[str] = []
    insufficient = False
    info: list[tuple[str, object, object]] = []  # (screenshot_id, captured, last_update)
    for shot in inp["screenshots"]:
        tf = shot["timeframe"]
        scope = scope_of(tf, cfg)
        decision_layer = scope in (SCOPE_AUCTION, SCOPE_MICRO) and shot["screenshot_id"] in data_bearing
        reasons: list[str] = []
        captured = parse_utc(shot["captured_at_utc"]) if shot["captured_at_utc"] else None
        last_update = parse_utc(shot["data_last_update_utc"]) if shot["data_last_update_utc"] else None
        if scope is None:
            reasons.append(f"TIMEFRAME_NOT_CONFIGURED: {tf}")
        if captured is None:
            reasons.append("TIMESTAMP_MISSING")
            if decision_layer:
                insufficient = True
                blocking.append(f"TIMESTAMP_MISSING: {shot['file_name']} ({tf}) has no capture time")
        elif decision_time is not None and captured > decision_time:
            # Data not yet available at decision time: excluded, never blocking.
            reasons.append("FUTURE_DATA: captured after the decision time")
        else:
            if shot["screenshot_id"] in data_bearing:
                info.append((shot["screenshot_id"], captured, last_update))
            if shot["screenshot_id"] not in baseline_only:
                stale = _staleness(shot, captured, last_update, decision_time, fresh, closed_bar_tfs)
                reasons.extend(stale)
                if stale and decision_layer and policy == "block":
                    blocking.extend(f"{r} ({shot['file_name']}, {tf})" for r in stale)
        if reasons:
            excluded.append({"screenshot_id": shot["screenshot_id"], "file_name": shot["file_name"],
                             "timeframe": tf, "reasons": reasons})
        else:
            usable[shot["screenshot_id"]] = shot

    sync_cfg = cfg["sync"]
    for scope, limit in ((SCOPE_MICRO, sync_cfg["micro_max_skew_seconds"]),
                         (SCOPE_AUCTION, sync_cfg["auction_max_skew_seconds"])):
        stamps = sorted(parse_utc(s["captured_at_utc"]) for s in usable.values()
                        if scope_of(s["timeframe"], cfg) == scope and s["screenshot_id"] in data_bearing)
        if len(stamps) >= 2:
            skew = (stamps[-1] - stamps[0]).total_seconds()
            if skew > limit:
                blocking.append(f"UNSYNCHRONISED: {scope} screenshots span {int(skew)}s > {limit}s")
    # data_as_of: capture time of the newest data-bearing screenshot whose
    # observations the engine actually used. If none is usable (e.g. all
    # stale), fall back to the newest data-bearing screenshot not after the
    # decision time, so that journaling a WAIT on old data is still measured
    # from that old data.
    used = [(c, u) for sid, c, u in info if sid in usable]
    basis = "USED_SCREENSHOTS" if used else ("DATA_BEARING_NONE_USABLE" if info else None)
    pool = used or [(c, u) for _, c, u in info]
    updates = [u for _, u in pool if u is not None]
    times = {
        "data_as_of": max(c for c, _ in pool) if pool else None,
        "data_as_of_basis": basis,
        "data_content_latest": max(updates) if updates else None,
    }
    return usable, excluded, blocking, insufficient, times


def _staleness(shot, captured, last_update, decision_time, fresh, closed_bar_tfs) -> list[str]:
    tf = shot["timeframe"]
    stale = []
    if decision_time is not None:
        age = (decision_time - captured).total_seconds()
        max_age = fresh["max_age_seconds"].get(tf)
        if max_age is not None and age > max_age:
            stale.append(f"STALE: age {int(age)}s > {max_age}s allowed for {tf}")
        if tf in closed_bar_tfs:
            last_close = floor_bar(decision_time, tf)
            if captured < last_close:
                stale.append(f"MISSING_LATEST_CLOSED_BAR: captured before the {tf} bar close at "
                             f"{fmt_utc(last_close)}")
    if last_update is not None:
        lag = (captured - last_update).total_seconds()
        if lag > fresh["max_update_lag_seconds"]:
            stale.append(f"DATA_NOT_UPDATED: chart data {int(lag)}s older than capture")
    elif fresh["require_update_evidence"] and not shot.get("live_feed_confirmed"):
        # Without either signal a frozen chart would pass every age check.
        stale.append("FRESHNESS_UNVERIFIABLE: no data_last_update_utc and no live_feed_confirmed")
    return stale


# --------------------------------------------------------------------------
# 3-4: observation filtering and field resolution
# --------------------------------------------------------------------------

def _comparison_problem(obs: dict, shots_by_id: dict, cfg: dict, decision_time) -> str | None:
    later = shots_by_id.get(obs["screenshot_id"])
    earlier = shots_by_id.get(obs["compared_with_screenshot_id"] or "")
    tag = "VISUAL_CHANGE_NOT_ASSESSABLE"
    if earlier is None:
        return f"{tag}: no earlier screenshot to compare with (single snapshot)"
    for s in (earlier, later):
        if HEATMAP not in s["indicators"]:
            return f"{tag}: {s['file_name']} is not an order-book heatmap"
        if not s["captured_at_utc"]:
            return f"{tag}: {s['file_name']} has no capture time"
    if earlier["timeframe"] != later["timeframe"]:
        return f"{tag}: compared heatmaps use different timeframes"
    if not earlier.get("view_settings") or earlier.get("view_settings") != later.get("view_settings"):
        # Heatmap colour scales are normalised per view; brightness is only
        # comparable between screenshots with identical view settings.
        return f"{tag}: view_settings missing or different between the two heatmaps"
    t0, t1 = parse_utc(earlier["captured_at_utc"]), parse_utc(later["captured_at_utc"])
    if t0 >= t1:
        return f"{tag}: compared_with must be captured EARLIER"
    if decision_time is not None and t0 > decision_time:
        return f"{tag}: earlier screenshot is after decision time"
    if (t1 - t0).total_seconds() > cfg["thresholds"]["resiliency_max_gap_seconds"]:
        return f"{tag}: gap between heatmaps exceeds resiliency_max_gap_seconds"
    return None


def _window_problem(obs: dict, shot: dict) -> str | None:
    if not obs.get("window_end_utc") or not obs.get("window_start_utc"):
        return "WINDOW_MISSING: reading has no observation window (OBS-PROTOCOL-2)"
    end = parse_utc(obs["window_end_utc"])
    expected = floor_bar(parse_utc(shot["captured_at_utc"]), shot["timeframe"])
    if end != expected:
        return (f"WINDOW_NOT_LATEST_CLOSED_BAR: window ends {fmt_utc(end)}, last closed "
                f"{shot['timeframe']} bar before capture closed {fmt_utc(expected)}")
    return None


def _resolve(inp: dict, cfg: dict, usable: dict, decision_time):
    shots_by_id = {s["screenshot_id"]: s for s in inp["screenshots"]}
    resolved: dict[tuple[str, str], Resolved] = {}
    ignored: list[dict] = []
    obs_cfg = cfg["observations"]
    primary_tf = inp.get("analysis_timeframe") or cfg["timeframes"]["micro_decision"]

    for obs in sorted(inp["observations"], key=lambda o: o["observation_id"]):
        spec = FIELDS.get(obs["field"])
        shot = usable.get(obs["screenshot_id"])
        if spec is None:
            ignored.append({"observation_id": obs["observation_id"], "reason": "UNKNOWN_FIELD"})
            continue
        if shot is None:
            ignored.append({"observation_id": obs["observation_id"], "field": obs["field"],
                            "reason": "SCREENSHOT_NOT_USABLE"})
            continue
        if not spec.enabled:
            ignored.append({"observation_id": obs["observation_id"], "field": obs["field"],
                            "reason": f"LAYER_{spec.layer}_DISABLED"})
            continue
        if not obs["verified"] and not obs_cfg["use_unverified_vision"]:
            ignored.append({"observation_id": obs["observation_id"], "field": obs["field"],
                            "reason": "UNVERIFIED_VISION_OUTPUT"})
            continue
        scope = scope_of(shot["timeframe"], cfg)
        key = (obs["field"], scope)
        r = resolved.setdefault(key, Resolved(obs["field"], scope))
        value = obs["value"]
        note = None
        if obs["readability"] == "UNCERTAIN" and not obs_cfg["use_uncertain"]:
            value, note = UNKNOWN, "UNCERTAIN reading treated as UNKNOWN by policy"
        if obs["readability"] == "UNREADABLE":
            value, note = UNKNOWN, "UNREADABLE"
        if spec.requires_window and value != UNKNOWN:
            problem = _window_problem(obs, shot)
            if problem:
                value, note = UNKNOWN, problem
        if spec.requires_comparison and value != UNKNOWN:
            problem = _comparison_problem(obs, shots_by_id, cfg, decision_time)
            if problem:
                value, note = UNKNOWN, problem
        role = "PRIMARY"
        if scope == SCOPE_MICRO and shot["timeframe"] != primary_tf:
            role = "SECONDARY"
        r.readings.append({"observation_id": obs["observation_id"], "screenshot_id": shot["screenshot_id"],
                           "timeframe": shot["timeframe"], "value": value, "role": role,
                           "captured_at_utc": shot["captured_at_utc"], "note": note})
        if note:
            r.notes.append(note)

    for key, r in resolved.items():
        r.observation_ids = sorted(rd["observation_id"] for rd in r.readings)
        r.screenshot_ids = sorted({rd["screenshot_id"] for rd in r.readings})
        known = [rd for rd in r.readings if rd["value"] != UNKNOWN]
        if not known:
            r.value = UNKNOWN
            continue
        if r.field == "last_price":
            latest = max(known, key=lambda rd: (rd["captured_at_utc"], rd["observation_id"]))
            r.value = latest["value"]
            continue
        distinct = sorted({repr(rd["value"]) for rd in known})
        if len(distinct) > 1:
            r.value = CONFLICT
            r.notes.append("readings disagree (any disagreement, also across 5M/1M, blocks): " + ", ".join(
                f"{rd['timeframe']}#{rd['observation_id']}={rd['value']}" for rd in known))
            continue
        primary = [rd for rd in known if rd["role"] == "PRIMARY"]
        secondary = [rd for rd in known if rd["role"] == "SECONDARY"]
        if r.scope == SCOPE_MICRO and r.field in GATING_MICRO_FIELDS and not primary:
            r.value = UNKNOWN
            r.notes.append(f"only {secondary[0]['timeframe']} reading; setup conditions use the decision "
                           f"timeframe {primary_tf}")
            continue
        r.value = known[0]["value"]
        if primary and secondary:
            r.notes.append(f"concordant {secondary[0]['timeframe']} reading: consistency check only, "
                           "not counted as additional evidence")
    return resolved, ignored


# --------------------------------------------------------------------------
# 5: consistency checks
# --------------------------------------------------------------------------

_AGGR_FROM_FOOTPRINT = {"BUY_DOMINANT": "BUY", "SELL_DOMINANT": "SELL", "BALANCED": "NEUTRAL"}
_AGGR_FROM_CVD = {"RISING": "BUY", "FALLING": "SELL", "FLAT": "NEUTRAL"}


def _conflict(code: str, description: str, facts: Facts, keys) -> dict:
    obs, shots = facts.refs(keys)
    return {"code": code, "description": description, "fields": [f"{f}@{s}" for f, s in keys],
            "observation_ids": obs, "screenshot_ids": shots, "blocking": True}


def _consistency(facts: Facts) -> list[dict]:
    out = []
    for (f, s), r in facts.items():
        if r.value == CONFLICT:
            out.append(_conflict("READINGS_DISAGREE", f"{f} at {s}: " + "; ".join(r.notes), facts, [(f, s)]))

    A = SCOPE_AUCTION
    pos = facts.value("price_vs_prev_value_area", A)
    vah, val = facts.value("prev_vah", A), facts.value("prev_val", A)
    price = facts.value("last_price", A)
    if isinstance(vah, float) and isinstance(val, float):
        if vah <= val:
            out.append(_conflict("VALUE_AREA_INVALID", f"prev_vah {vah} <= prev_val {val}", facts,
                                 [("prev_vah", A), ("prev_val", A)]))
        elif isinstance(price, float) and pos in ("ABOVE", "INSIDE", "BELOW"):
            expected = "ABOVE" if price > vah else "BELOW" if price < val else "INSIDE"
            if expected != pos:
                out.append(_conflict(
                    "PRICE_POSITION_MISMATCH",
                    f"last_price {price} vs VA [{val}, {vah}] implies {expected}, but recorded {pos}", facts,
                    [("last_price", A), ("prev_vah", A), ("prev_val", A), ("price_vs_prev_value_area", A)]))

    viol = facts.value("violation_side", A)
    if (pos == "ABOVE" and viol in ("NONE", "DOWN")) or (pos == "BELOW" and viol in ("NONE", "UP")):
        out.append(_conflict("POSITION_VS_VIOLATION",
                             f"price is {pos} the previous value area but violation_side={viol}", facts,
                             [("price_vs_prev_value_area", A), ("violation_side", A)]))
    ret = facts.value("returned_inside_value", A)
    bars = facts.value("closed_bars_outside_value", A)
    if ret == "YES" and isinstance(bars, int) and bars > 0:
        out.append(_conflict("RETURN_VS_BARS_OUTSIDE",
                             f"latest closed bar cannot be back inside (returned=YES) while {bars} closed "
                             "bars are counted outside", facts,
                             [("returned_inside_value", A), ("closed_bars_outside_value", A)]))
    if ret == "YES" and viol == "NONE":
        out.append(_conflict("RETURN_WITHOUT_VIOLATION", "returned inside value but no violation recorded",
                             facts, [("returned_inside_value", A), ("violation_side", A)]))

    fp = _AGGR_FROM_FOOTPRINT.get(facts.value("footprint_aggression", SCOPE_MICRO))
    cvd = _AGGR_FROM_CVD.get(facts.value("cvd_trend", SCOPE_MICRO))
    if fp and cvd and {fp, cvd} == {"BUY", "SELL"}:
        out.append(_conflict("AGGRESSION_SOURCES_DISAGREE",
                             f"footprint says {fp}, CVD says {cvd} for the same trade prints", facts,
                             [("footprint_aggression", SCOPE_MICRO), ("cvd_trend", SCOPE_MICRO)]))
    return out


# --------------------------------------------------------------------------
# 6: derived market-state components
# --------------------------------------------------------------------------

def _trade_aggression(facts: Facts) -> Resolved:
    """Footprint delta and CVD are views of the SAME trade prints. They are
    merged into one evidence group and never counted twice."""
    keys = [("footprint_aggression", SCOPE_MICRO), ("cvd_trend", SCOPE_MICRO)]
    fp_raw, cvd_raw = facts.value(*keys[0]), facts.value(*keys[1])
    fp, cvd = _AGGR_FROM_FOOTPRINT.get(fp_raw), _AGGR_FROM_CVD.get(cvd_raw)
    obs, shots = facts.refs(keys)
    r = Resolved("trade_aggression", SCOPE_DERIVED, observation_ids=obs, screenshot_ids=shots)
    if CONFLICT in (fp_raw, cvd_raw):
        r.value = CONFLICT
    elif fp is None and cvd is None:
        r.value = UNKNOWN
    elif fp is None or cvd is None:
        r.value = fp or cvd
        r.notes.append("single source (footprint or CVD only)")
    elif fp == cvd:
        r.value = fp
        r.notes.append("footprint and CVD concordant: counted as ONE evidence group (same trade prints), "
                       "not as two independent confirmations")
    elif {fp, cvd} == {"BUY", "SELL"}:
        r.value = CONFLICT
    else:
        r.value = "NEUTRAL"
        r.notes.append(f"mixed reading (footprint {fp}, CVD {cvd}) treated as no dominant aggression")
    return r


def _efficiency(aggr: str, response) -> str:
    if aggr in (UNKNOWN, CONFLICT) or response in (UNKNOWN, CONFLICT):
        return UNKNOWN
    if aggr == "NEUTRAL":
        return "NOT_APPLICABLE"
    return "EFFECTIVE" if response == "ADVANCED" else "INEFFECTIVE"


def _market_state_label(facts: Facts) -> str:
    A = SCOPE_AUCTION
    pos = facts.value("price_vs_prev_value_area", A)
    viol = facts.value("violation_side", A)
    ret = facts.value("returned_inside_value", A)
    if pos == "INSIDE":
        if viol in ("UP", "DOWN") and ret == "YES":
            return f"RETURNED_TO_VALUE_AFTER_{viol}_VIOLATION"
        if viol == "NONE":
            return "BALANCE_INSIDE_VALUE"
        return "INSIDE_VALUE"
    if pos == "ABOVE":
        return "OUTSIDE_VALUE_UP"
    if pos == "BELOW":
        return "OUTSIDE_VALUE_DOWN"
    return UNKNOWN


def _derive(facts: Facts, cfg: dict) -> tuple[dict, list[dict]]:
    A, M = SCOPE_AUCTION, SCOPE_MICRO
    ev: list[dict] = []
    aggr = _trade_aggression(facts)
    response = facts.value("price_response_to_aggression", M)
    eff = _efficiency(aggr.value, response)
    n_accept = cfg["thresholds"]["acceptance_min_closed_bars_30m"]
    bars = facts.value("closed_bars_outside_value", A)
    pos = facts.value("price_vs_prev_value_area", A)
    ret = facts.value("returned_inside_value", A)
    if pos in ("ABOVE", "BELOW") and isinstance(bars, int) and ret == "NO":
        acceptance = f"ACCEPTED_{pos}" if bars >= n_accept else f"TESTING_{pos}"
    elif ret == "YES":
        acceptance = "REJECTED_BACK_INSIDE"
    elif pos == "INSIDE":
        acceptance = "NOT_APPLICABLE_INSIDE"
    else:
        acceptance = UNKNOWN

    state = {
        "label": _market_state_label(facts),
        "auction_position_30m": pos,
        "auction_position_4h_context": facts.value("price_vs_prev_value_area", SCOPE_CONTEXT),
        "acceptance": acceptance,
        "acceptance_rule": f"ACCEPTED requires >= {n_accept} closed 30M bars outside and no close back inside "
                           "(threshold NOT calibrated)",
        "violation_side": facts.value("violation_side", A),
        "price_vs_avwap": facts.value("price_vs_avwap", A),
        "last_price": facts.value("last_price", M) if facts.value("last_price", M) != UNKNOWN
        else facts.value("last_price", A),
        "trade_aggression": aggr.value,
        "trade_aggression_notes": aggr.notes,
        "price_response_to_aggression": response,
        "aggression_efficiency": eff,
        "aggression_at_extreme": facts.value("aggression_at_extreme", M),
        "price_response_at_extreme": facts.value("price_response_at_extreme", M),
        "passive_liquidity_above": facts.value("passive_liquidity_above", M),
        "passive_liquidity_below": facts.value("passive_liquidity_below", M),
        # Qualitative two-screenshot heatmap comparison; NOT L2 Liquidity Resiliency.
        "ask_side_visual_change": facts.value("ask_side_after_consumption", M),
        "bid_side_visual_change": facts.value("bid_side_after_consumption", M),
        "visual_change_notes": sorted(set(facts.get("ask_side_after_consumption", M).notes
                                       + facts.get("bid_side_after_consumption", M).notes)),
        "oi_change": facts.value("oi_change", M),
        "liquidations": facts.value("liquidations", M),
        "absorption_signal_aux": facts.value("absorption_signal", M),
        "l2_metrics": "DISABLED: no event-level L2 data in screenshot mode (OFI, queue imbalance, "
                      "Liquidity Resiliency / replenishment are not computed)",
    }

    # OBSERVED: every resolved field with a known value
    for (f, s), r in facts.items():
        if r.value in (UNKNOWN, CONFLICT):
            continue
        ev.append(evidence(EvidenceKind.OBSERVED, f"{f} ({s}) = {r.value}", facts, [(f, s)],
                           group=FIELDS[f].group))
    # INFERRED: derived components
    if aggr.value not in (UNKNOWN,):
        ev.append(evidence(EvidenceKind.INFERRED,
                           f"trade aggression = {aggr.value}" + (f" ({'; '.join(aggr.notes)})" if aggr.notes else ""),
                           facts, [("footprint_aggression", M), ("cvd_trend", M)], group=GROUP_TRADE_AGGRESSION))
    if eff != UNKNOWN:
        ev.append(evidence(EvidenceKind.INFERRED,
                           f"aggression efficiency = {eff} (aggression {aggr.value}, price {response})",
                           facts, [("footprint_aggression", M), ("cvd_trend", M), ("price_response_to_aggression", M)],
                           group=GROUP_TRADE_AGGRESSION))
    if acceptance != UNKNOWN:
        ev.append(evidence(EvidenceKind.INFERRED, f"auction acceptance = {acceptance}", facts,
                           [("price_vs_prev_value_area", A), ("closed_bars_outside_value", A),
                            ("returned_inside_value", A)]))
    return state, ev


def _unknowns(facts: Facts, ignored: list[dict], excluded: list[dict]) -> list[dict]:
    out = []
    for (f, s), r in facts.items():
        if r.value == UNKNOWN:
            out.append(evidence(EvidenceKind.UNKNOWN, f"{f} ({s}) unknown" + (
                f": {'; '.join(sorted(set(r.notes)))}" if r.notes else ""), facts, [(f, s)]))
    for e in excluded:
        out.append({"kind": EvidenceKind.UNKNOWN.value,
                    "statement": f"screenshot {e['file_name']} ({e['timeframe']}) excluded: {'; '.join(e['reasons'])}",
                    "fields": [], "observation_ids": [], "screenshot_ids": [e["screenshot_id"]],
                    "source_group": None, "stance": None})
    return out


def assess(inp: dict, cfg: dict) -> dict:
    """Run the full deterministic pipeline and return the assessment."""
    from lar_ofi.decision import decide  # local import: decision depends on engine helpers
    from lar_ofi.setups import evaluate_setups

    decision_time = parse_utc(inp.get("decision_time_utc")) if inp.get("decision_time_utc") else None
    usable, excluded, blocking, insufficient, times = _screen_screenshots(inp, cfg, decision_time)
    resolved, ignored = _resolve(inp, cfg, usable, decision_time)
    facts = Facts(resolved)
    conflicts = _consistency(facts)
    state, derived_evidence = _derive(facts, cfg)
    if state["trade_aggression"] == CONFLICT and not any(
            c["code"] in ("AGGRESSION_SOURCES_DISAGREE", "READINGS_DISAGREE") for c in conflicts):
        conflicts.append(_conflict("AGGRESSION_CONFLICT", "trade aggression readings conflict", facts,
                                   [("footprint_aggression", SCOPE_MICRO), ("cvd_trend", SCOPE_MICRO)]))

    usable_decision_obs = [o for o in inp["observations"] if o["screenshot_id"] in usable]
    if not inp["screenshots"]:
        data_status = DataStatus.NO_DATA
        blocking.append("NO_SCREENSHOTS")
    elif decision_time is None:
        data_status = DataStatus.INSUFFICIENT_DATA
        blocking.append("NO_DECISION_TIME: no decision time and no screenshot timestamps")
    elif insufficient:
        data_status = DataStatus.INSUFFICIENT_DATA
    elif not usable_decision_obs:
        data_status = DataStatus.NO_DATA
        blocking.append("NO_USABLE_OBSERVATIONS")
    elif blocking or excluded:
        data_status = DataStatus.PARTIAL
    else:
        data_status = DataStatus.SUFFICIENT

    disabled_layers = sorted({f"{INDICATORS[i].layer}:{i}" for s in inp["screenshots"] for i in s["indicators"]
                              if i in INDICATORS and not INDICATORS[i].enabled})
    setups = evaluate_setups(facts, state, cfg, inp.get("previous_states") or {})
    result = {
        "engine_version": ENGINE_VERSION,
        "dataset_id": inp["dataset_id"],
        "instrument": inp["instrument"],
        "exchange": inp["exchange"],
        "contract_type": inp["contract_type"],
        "analysis_timeframe": inp.get("analysis_timeframe"),
        "data_source_config": inp.get("data_source_config"),
        "regime_tag": inp.get("regime_tag"),
        "decision_time_utc": inp.get("decision_time_utc"),
        "data_as_of_utc": fmt_utc(times["data_as_of"]),
        "data_as_of_basis": times["data_as_of_basis"],
        "data_content_latest_utc": fmt_utc(times["data_content_latest"]),
        "data_status": data_status.value,
        "blocking_issues": blocking,
        "dataset_issues": inp.get("dataset_issues", []),
        "excluded_screenshots": excluded,
        "ignored_observations": ignored,
        "disabled_layers_present": disabled_layers,
        "resolved_fields": [r.as_dict() for _, r in facts.items()],
        "market_state": state,
        "conflicts": conflicts,
        "observed_and_inferred": derived_evidence,
        "unknowns": _unknowns(facts, ignored, excluded),
        "setups": setups,
    }
    result.update(decide(result, facts, cfg))
    return result
