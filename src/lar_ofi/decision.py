"""Decision layer: maps setup states to LONG / SHORT / WAIT.

Rules (evaluated in order, first match wins):
  D1  any blocking data issue (no data, missing timestamp, stale or
      unsynchronised decision-layer screenshot)            -> WAIT
  D2  any blocking conflict between readings/fields        -> WAIT
  D3  no setup CONFIRMED                                   -> WAIT
  D4  confirmed setups point in different directions, or
      the other setup is CANDIDATE/CONFIRMED in the
      opposite direction                                   -> WAIT
  D5  otherwise                                            -> direction of the
                                                              CONFIRMED setup
There is no voting and no probability. Probability is always NOT_CALIBRATED.
"""

from __future__ import annotations

from lar_ofi.engine import Facts
from lar_ofi.enums import NOT_CALIBRATED, Decision, EvidenceKind, SetupState
from lar_ofi.setups import CONTINUATION, FAILED_AUCTION

_ADVANCE = {"CONFIRMED_LONG": 5, "CONFIRMED_SHORT": 5, "CANDIDATE_LONG": 4, "CANDIDATE_SHORT": 4,
            "INVALIDATED": 3, "WAIT": 2, "NONE": 1}


def _direction_of(state: str) -> str | None:
    if state.endswith("_LONG"):
        return "LONG"
    if state.endswith("_SHORT"):
        return "SHORT"
    return None


def _cond_evidence(cond: dict, kind: EvidenceKind, stance: str, facts: Facts, setup: str) -> dict:
    keys = []
    for f in cond["fields"]:
        name, scope = f.split("@")
        keys.append((name, scope))
    obs, shots = facts.refs([k for k in keys if k[1] != "DERIVED"])
    # derived fields reference the observations they were built from
    if any(k[1] == "DERIVED" for k in keys):
        o2, s2 = facts.refs([("footprint_aggression", "MICRO"), ("cvd_trend", "MICRO"),
                             ("price_response_to_aggression", "MICRO")])
        obs, shots = sorted(set(obs) | set(o2)), sorted(set(shots) | set(s2))
    return {"kind": kind.value, "statement": f"[{setup} {cond['id']}] {cond['text']} -> {cond['status']} "
                                             f"({cond['observed']})",
            "fields": cond["fields"], "observation_ids": obs, "screenshot_ids": shots,
            "source_group": None, "stance": stance}


def decide(result: dict, facts: Facts, cfg: dict) -> dict:
    setups = result["setups"]
    reasons: list[str] = []
    decision = Decision.WAIT

    blocking_conflicts = [c for c in result["conflicts"] if c["blocking"]]
    confirmed = {name: _direction_of(s["state"]) for name, s in setups.items()
                 if s["state"] in (SetupState.CONFIRMED_LONG, SetupState.CONFIRMED_SHORT)}
    live = {name: _direction_of(s["state"]) for name, s in setups.items()
            if _direction_of(s["state"]) is not None}
    setup_conflict = len(set(live.values())) > 1

    if result["blocking_issues"]:
        reasons.append("D1 data issues: " + "; ".join(result["blocking_issues"]))
    elif blocking_conflicts:
        reasons.append("D2 conflicting information: " + "; ".join(c["code"] for c in blocking_conflicts))
    elif not confirmed:
        reasons.append("D3 no setup confirmed")
    elif setup_conflict:
        reasons.append("D4 setups disagree: " + ", ".join(f"{n}={setups[n]['state']}" for n in sorted(live)))
    else:
        (name, direction), = list(confirmed.items())[:1]
        decision = Decision(direction)
        reasons.append(f"D5 {name} {setups[name]['state']}")

    # Active setup: the confirmed one, else the most advanced one.
    ranked = sorted(setups.items(), key=lambda kv: (-_ADVANCE[kv[1]["state"]], kv[0]))
    active_name, active = ranked[0]
    if active["state"] in ("NONE",):
        active_name = None

    for_ev, against_ev, hypo = [], [], []
    confirm_text, invalid_text = [], []
    if active_name is not None and active["direction"] is not None:
        variant = active["variants"][active["direction"]]
        for c in [variant["trigger"]] + variant["candidate"] + variant["confirmation"]:
            if c["status"] == "TRUE":
                for_ev.append(_cond_evidence(c, EvidenceKind.INFERRED, "FOR", facts, active_name))
            elif c["status"] == "FALSE":
                against_ev.append(_cond_evidence(c, EvidenceKind.INFERRED, "AGAINST", facts, active_name))
            if c["status"] != "TRUE" and c in variant["confirmation"] + variant["candidate"]:
                confirm_text.append(f"{c['id']}: {c['text']}")
        for c in variant["invalidation"]:
            invalid_text.append(f"{c['id']}: {c['text']}")
            if c["status"] == "TRUE":
                against_ev.append(_cond_evidence(c, EvidenceKind.INFERRED, "AGAINST", facts, active_name))
        for item in variant["context"]:
            entry = {**item, "observation_ids": [], "screenshot_ids": [], "source_group": None}
            keys = [tuple(f.split("@")) for f in item["fields"]]
            entry["observation_ids"], entry["screenshot_ids"] = facts.refs(keys)
            hypo.append(entry)
            if item["stance"] == "FOR":
                for_ev.append(entry)
            elif item["stance"] == "AGAINST":
                against_ev.append(entry)
    for c in blocking_conflicts:
        against_ev.append({"kind": EvidenceKind.INFERRED.value, "statement": f"CONFLICT {c['code']}: {c['description']}",
                           "fields": c["fields"], "observation_ids": c["observation_ids"],
                           "screenshot_ids": c["screenshot_ids"], "source_group": None, "stance": "AGAINST"})

    hypothesis_text = _scenario_text(active_name, active, decision)
    hypo.insert(0, {"kind": EvidenceKind.HYPOTHESIS.value, "statement": hypothesis_text, "fields": [],
                    "observation_ids": [], "screenshot_ids": [], "source_group": None, "stance": None})
    if not confirm_text:
        confirm_text = (["already confirmed; act only if still valid at entry time"] if decision != Decision.WAIT
                        else ["no active setup: wait for a CONTINUATION or FAILED_AUCTION trigger"])
    if not invalid_text:
        invalid_text = ["not applicable (no active setup)"]

    return {
        "decision": decision.value,
        "decision_rules_applied": reasons,
        "active_setup": active_name,
        "active_setup_state": active["state"] if active_name else "NONE",
        "has_blocking_conflict": bool(blocking_conflicts) or setup_conflict,
        "evidence_for": for_ev,
        "evidence_against": against_ev,
        "hypotheses": hypo,
        "confirmation_condition": confirm_text,
        "invalidation_condition": invalid_text,
        "horizons_minutes": list(cfg["prediction"]["horizons_minutes"]),
        "probability": NOT_CALIBRATED,
        "calibration_status": NOT_CALIBRATED,
        "thresholds_calibrated": bool(cfg["thresholds"]["calibrated"]),
    }


def _scenario_text(name: str | None, setup: dict, decision: Decision) -> str:
    if name is None:
        return "No setup trigger present: no scenario is favoured (WAIT)."
    d = setup["direction"]
    if name == CONTINUATION:
        body = (f"Auction acceptance {'above' if d == 'LONG' else 'below'} the previous value area may continue "
                f"({'up' if d == 'LONG' else 'down'}) while aggression keeps moving price and the opposite "
                "side does not rebuild.")
    elif name == FAILED_AUCTION:
        body = (f"Failed {'breakout up' if d == 'SHORT' else 'breakdown'}: aggression beyond the extreme did not "
                f"produce acceptance; rotation back into value ({'down' if d == 'SHORT' else 'up'}) is the "
                "working hypothesis.")
    else:  # pragma: no cover
        body = name
    return f"{body} Setup state: {setup['state']}. Decision: {decision.value}. Probability: {NOT_CALIBRATED}."
