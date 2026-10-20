"""Setup detector: CONTINUATION (auction acceptance) and FAILED_AUCTION.

Each setup has a LONG and a SHORT variant. A variant is defined by:
  trigger       - the market situation in which the setup is relevant
  candidate     - conditions for CANDIDATE_<dir>
  invalidation  - any TRUE -> INVALIDATED
  confirmation  - all TRUE (on top of candidate) -> CONFIRMED_<dir>
  context       - reported, never gating (OI, liquidations, derived
                  absorption, higher timeframe)

Three-valued logic: a condition whose inputs are UNKNOWN/CONFLICT is
UNKNOWN. CONFIRMED needs every candidate and confirmation condition TRUE.
No voting, no weights, no scores.

State per variant (deterministic):
  trigger UNKNOWN                               -> WAIT
  trigger FALSE                                 -> NONE (INVALIDATED if the
                                                   previous state of this
                                                   setup was CANDIDATE/CONFIRMED
                                                   in the same direction)
  trigger TRUE and any invalidation TRUE        -> INVALIDATED
  trigger TRUE and all candidate TRUE           -> CONFIRMED_<dir> if all
                                                   confirmation TRUE, else
                                                   CANDIDATE_<dir>
  trigger TRUE, no candidate FALSE, some UNKNOWN -> WAIT
  otherwise                                     -> NONE
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lar_ofi.engine import SCOPE_AUCTION as A
from lar_ofi.engine import SCOPE_CONTEXT as CTX
from lar_ofi.engine import SCOPE_DERIVED as D
from lar_ofi.engine import SCOPE_MICRO as M
from lar_ofi.engine import Facts
from lar_ofi.enums import CONFLICT, UNKNOWN, SetupState, Tri

CONTINUATION = "CONTINUATION"
FAILED_AUCTION = "FAILED_AUCTION"

_RANK = {SetupState.CONFIRMED_LONG: 5, SetupState.CONFIRMED_SHORT: 5, SetupState.INVALIDATED: 4,
         SetupState.CANDIDATE_LONG: 3, SetupState.CANDIDATE_SHORT: 3, SetupState.WAIT: 2, SetupState.NONE: 1}


@dataclass
class Cond:
    id: str
    text: str
    status: Tri
    fields: list[str]
    observed: str = ""

    def as_dict(self) -> dict:
        return {"id": self.id, "text": self.text, "status": self.status.value, "fields": self.fields,
                "observed": self.observed}


@dataclass
class Variant:
    setup: str
    direction: str
    trigger: Cond
    candidate: list[Cond]
    invalidation: list[Cond]
    confirmation: list[Cond]
    context: list[dict] = field(default_factory=list)
    state: SetupState = SetupState.NONE
    reason: str = ""


def _val(facts: Facts, f: str, s: str, state: dict):
    if s == D:
        return state[f]
    return facts.value(f, s)


def _in(facts, state, cid, text, f, s, accepted) -> Cond:
    v = _val(facts, f, s, state)
    if v in (UNKNOWN, CONFLICT) or v is None:
        st = Tri.UNKNOWN
    else:
        st = Tri.TRUE if v in accepted else Tri.FALSE
    return Cond(cid, text, st, [f"{f}@{s}"], f"{f}={v}")


def _gte(facts, cid, text, f, s, n) -> Cond:
    v = facts.value(f, s)
    if not isinstance(v, int):
        return Cond(cid, text, Tri.UNKNOWN, [f"{f}@{s}"], f"{f}={v}")
    return Cond(cid, text, Tri.TRUE if v >= n else Tri.FALSE, [f"{f}@{s}"], f"{f}={v}")


def _and(cid, text, *conds: Cond) -> Cond:
    sts = [c.status for c in conds]
    st = Tri.FALSE if Tri.FALSE in sts else Tri.UNKNOWN if Tri.UNKNOWN in sts else Tri.TRUE
    return Cond(cid, text, st, [f for c in conds for f in c.fields], "; ".join(c.observed for c in conds))


def _ctx(stance: str, text: str, fields: list[str]) -> dict:
    return {"kind": "HYPOTHESIS", "stance": stance, "statement": text, "fields": fields}


# --------------------------------------------------------------------------
# Setup 1: CONTINUATION / AUCTION ACCEPTANCE
# --------------------------------------------------------------------------

def _continuation(facts: Facts, state: dict, cfg: dict, d: str) -> Variant:
    up = d == "LONG"
    side = "ABOVE" if up else "BELOW"
    aggr = "BUY" if up else "SELL"
    n = cfg["thresholds"]["acceptance_min_closed_bars_30m"]
    resil_field = "ask_side_after_consumption" if up else "bid_side_after_consumption"
    liq_field = "passive_liquidity_above" if up else "passive_liquidity_below"
    opp = "ask" if up else "bid"

    trigger = _in(facts, state, "C-T", f"30M price {side} the previous value area",
                  "price_vs_prev_value_area", A, {side})
    candidate = [
        _in(facts, state, "C-1", f"dominant trade aggression is {aggr} (footprint/CVD as ONE group)",
            "trade_aggression", D, {aggr}),
    ]
    invalidation = [
        _in(facts, state, "C-X1", "latest closed 30M bar back inside the previous value area",
            "returned_inside_value", A, {"YES"}),
        _and("C-X2", f"{aggr} aggression is not moving price (stalled/reversed = absorbed)",
             _in(facts, state, "", "", "trade_aggression", D, {aggr}),
             _in(facts, state, "", "", "aggression_efficiency", D, {"INEFFECTIVE"})),
    ]
    confirmation = [
        _and("C-2", f">= {n} closed 30M bars outside value and none back inside (acceptance; "
                     "threshold NOT calibrated)",
             _gte(facts, "", "", "closed_bars_outside_value", A, n),
             _in(facts, state, "", "", "returned_inside_value", A, {"NO"})),
        _in(facts, state, "C-3", f"{aggr} aggression is effective: price ADVANCED with it",
            "aggression_efficiency", D, {"EFFECTIVE"}),
    ]
    if cfg["thresholds"]["require_resiliency_for_confirmation"]:
        confirmation.append(_in(
            facts, state, "C-4", f"consumed {opp}-side liquidity did NOT replenish (needs >= 2 time-ordered "
                                 "heatmap screenshots)", resil_field, M, {"NOT_REPLENISHED"}))
    else:
        confirmation.append(_in(facts, state, "C-4", f"visible {opp}-side liquidity ahead is thin",
                                liq_field, M, {"THIN", "NOT_VISIBLE"}))
    confirmation.append(_in(facts, state, "C-5", "open interest not falling (move not only position closing)",
                            "oi_change", M, {"RISING", "FLAT"}))

    context = []
    liq = facts.value("liquidations", M)
    forced = "SHORTS_LIQUIDATED" if up else "LONGS_LIQUIDATED"
    if liq in (forced, "BOTH"):
        context.append(_ctx("AGAINST", f"{liq}: part of the move may be forced liquidation flow, which can "
                                       "exhaust rather than continue", ["liquidations@MICRO"]))
    oi = facts.value("oi_change", M)
    if oi == "RISING":
        context.append(_ctx("FOR", "OI rising with the move: consistent with new positions being opened",
                            ["oi_change@MICRO"]))
    absorb = facts.value("absorption_signal", M)
    against_absorb = "ASK_SIDE" if up else "BID_SIDE"
    if absorb == against_absorb:
        context.append(_ctx("AGAINST", f"derived Absorption indicator flags {absorb} absorption "
                                       "(auxiliary, algorithm unverified)", ["absorption_signal@MICRO"]))
    liq_ahead = facts.value(liq_field, M)
    if liq_ahead == "THICK":
        context.append(_ctx("AGAINST", f"thick visible {opp}-side liquidity ahead of price", [f"{liq_field}@MICRO"]))
    htf = facts.value("price_vs_prev_value_area", CTX)
    if htf in ("ABOVE", "INSIDE", "BELOW"):
        stance = "FOR" if htf == side else "NEUTRAL"
        context.append(_ctx(stance, f"4H context: price {htf} its previous value area", ["price_vs_prev_value_area@CONTEXT"]))
    return Variant(CONTINUATION, d, trigger, candidate, invalidation, confirmation, context)


# --------------------------------------------------------------------------
# Setup 2: FAILED AUCTION / FAILED BREAKOUT
# --------------------------------------------------------------------------

def _failed_auction(facts: Facts, state: dict, cfg: dict, d: str) -> Variant:
    # SHORT = failed breakout UP; LONG = failed breakdown DOWN
    short = d == "SHORT"
    viol = "UP" if short else "DOWN"
    trapped = "BUY" if short else "SELL"
    n = cfg["thresholds"]["acceptance_min_closed_bars_30m"]
    resil_field = "ask_side_after_consumption" if short else "bid_side_after_consumption"
    liq_field = "passive_liquidity_above" if short else "passive_liquidity_below"
    side = "ABOVE" if short else "BELOW"
    pside = "ask" if short else "bid"

    trigger = _in(facts, state, "F-T", f"price traded beyond the previous value area / extreme ({viol})",
                  "violation_side", A, {viol})
    candidate = [
        _in(facts, state, "F-1", f"{trapped} aggression at the extreme (footprint)",
            "aggression_at_extreme", M, {trapped}),
        _in(facts, state, "F-2", "price did not advance after that aggression (STALLED or REVERSED)",
            "price_response_at_extreme", M, {"STALLED", "REVERSED"}),
    ]
    invalidation = [
        _and("F-X1", f"acceptance outside: >= {n} closed 30M bars {side} value (threshold NOT calibrated)",
             _in(facts, state, "", "", "price_vs_prev_value_area", A, {side}),
             _gte(facts, "", "", "closed_bars_outside_value", A, n),
             _in(facts, state, "", "", "returned_inside_value", A, {"NO"})),
        _in(facts, state, "F-X2", "aggression at the extreme was effective: price ADVANCED",
            "price_response_at_extreme", M, {"ADVANCED"}),
    ]
    confirmation = [
        _and("F-3", "latest closed 30M bar back inside previous value area and price now inside",
             _in(facts, state, "", "", "returned_inside_value", A, {"YES"}),
             _in(facts, state, "", "", "price_vs_prev_value_area", A, {"INSIDE"})),
    ]
    if cfg["thresholds"]["require_resiliency_for_confirmation"]:
        confirmation.append(_in(
            facts, state, "F-4", f"{pside}-side passive liquidity at the extreme REPLENISHED after being hit "
                                 "(needs >= 2 time-ordered heatmap screenshots)", resil_field, M, {"REPLENISHED"}))
    else:
        confirmation.append(_in(facts, state, "F-4", f"thick visible {pside}-side liquidity at the extreme",
                                liq_field, M, {"THICK"}))

    context = []
    oi = facts.value("oi_change", M)
    if oi == "FALLING":
        context.append(_ctx("FOR", "OI falling: consistent with trapped positions being closed",
                            ["oi_change@MICRO"]))
    elif oi == "RISING":
        context.append(_ctx("NEUTRAL", "OI rising: ambiguous (new counter-positions or new trapped positions)",
                            ["oi_change@MICRO"]))
    liq = facts.value("liquidations", M)
    forced = "LONGS_LIQUIDATED" if short else "SHORTS_LIQUIDATED"
    if liq in (forced, "BOTH"):
        context.append(_ctx("FOR", f"{liq}: recorded liquidations of the trapped side", ["liquidations@MICRO"]))
    absorb = facts.value("absorption_signal", M)
    if absorb == ("ASK_SIDE" if short else "BID_SIDE"):
        context.append(_ctx("FOR", f"derived Absorption indicator flags {absorb} absorption "
                                   "(auxiliary only, algorithm unverified; never sufficient alone)",
                            ["absorption_signal@MICRO"]))
    return Variant(FAILED_AUCTION, d, trigger, candidate, invalidation, confirmation, context)


# --------------------------------------------------------------------------

def _state_of(v: Variant, previous: str | None) -> Variant:
    held = previous in (f"CANDIDATE_{v.direction}", f"CONFIRMED_{v.direction}")
    if v.trigger.status is Tri.UNKNOWN:
        v.state, v.reason = SetupState.WAIT, f"trigger unknown ({v.trigger.observed})"
        return v
    if v.trigger.status is Tri.FALSE:
        if held:
            v.state, v.reason = SetupState.INVALIDATED, f"trigger no longer holds after previous {previous}"
        else:
            v.state, v.reason = SetupState.NONE, "trigger not present"
        return v
    hit = [c for c in v.invalidation if c.status is Tri.TRUE]
    if hit:
        v.state, v.reason = SetupState.INVALIDATED, "; ".join(f"{c.id}: {c.text}" for c in hit)
        return v
    cand = [c.status for c in v.candidate]
    if all(s is Tri.TRUE for s in cand):
        unmet = [c for c in v.confirmation if c.status is not Tri.TRUE]
        if not unmet:
            v.state, v.reason = SetupState(f"CONFIRMED_{v.direction}"), "all candidate and confirmation conditions TRUE"
        else:
            v.state = SetupState(f"CANDIDATE_{v.direction}")
            v.reason = "awaiting: " + "; ".join(f"{c.id}={c.status.value}" for c in unmet)
        return v
    if Tri.FALSE not in cand:
        v.state, v.reason = SetupState.WAIT, "candidate inputs unknown: " + "; ".join(
            f"{c.id}" for c in v.candidate if c.status is Tri.UNKNOWN)
        return v
    v.state, v.reason = SetupState.NONE, "candidate conditions not met"
    return v


def _variant_dict(v: Variant) -> dict:
    return {
        "direction": v.direction,
        "state": v.state.value,
        "reason": v.reason,
        "trigger": v.trigger.as_dict(),
        "candidate": [c.as_dict() for c in v.candidate],
        "invalidation": [c.as_dict() for c in v.invalidation],
        "confirmation": [c.as_dict() for c in v.confirmation],
        "context": v.context,
    }


def evaluate_setups(facts: Facts, state: dict, cfg: dict, previous_states: dict) -> dict:
    out = {}
    builders = {CONTINUATION: _continuation, FAILED_AUCTION: _failed_auction}
    for name, build in builders.items():
        prev = previous_states.get(name)
        variants = [_state_of(build(facts, state, cfg, d), prev) for d in ("LONG", "SHORT")]
        top = max(variants, key=lambda v: (_RANK[v.state], v.direction == "LONG"))
        out[name] = {
            "state": top.state.value,
            "direction": top.direction if top.state not in (SetupState.NONE, SetupState.WAIT) else None,
            "reason": top.reason,
            "previous_state": prev,
            "variants": {v.direction: _variant_dict(v) for v in variants},
        }
    return out
