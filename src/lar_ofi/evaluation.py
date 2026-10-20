"""Chronological evaluation of journaled predictions.

* No random splits: an optional `evaluation.test_start_utc` splits the
  journal into a DEVELOPMENT segment and a TEST segment by recording time.
* Every evaluation run is appended to `evaluation_runs` and the report shows
  how many runs preceded it (multiple looks are disclosed, not hidden).
* Profitability is reported ONLY when every scored directional prediction
  carries an explicit, user-supplied cost model frozen at recording time.
* No statistical claim below `min_sample_for_any_claim` scored predictions.
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime

from lar_ofi.config import canonical_json
from lar_ofi.timeutil import fmt_utc, parse_utc

Z95 = 1.959963984540054


def wilson(k: int, n: int) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    denom = 1 + Z95**2 / n
    centre = (p + Z95**2 / (2 * n)) / denom
    half = Z95 * math.sqrt(p * (1 - p) / n + Z95**2 / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def max_drawdown(values: list[float]) -> float:
    """Largest peak-to-trough decline of the running sum (same units)."""
    peak = cum = 0.0
    mdd = 0.0
    for v in values:
        cum += v
        peak = max(peak, cum)
        mdd = max(mdd, peak - cum)
    return mdd


def _hit_stats(outcomes: list[str]) -> dict:
    c = Counter(outcomes)
    hits, misses, neutral = c.get("HIT", 0), c.get("MISS", 0), c.get("NEUTRAL", 0)
    decided = hits + misses
    ci = wilson(hits, decided)
    return {
        "n": len(outcomes),
        "hit": hits,
        "miss": misses,
        "neutral": neutral,
        "unscorable": c.get("UNSCORABLE", 0),
        "hit_rate_excl_neutral": round(hits / decided, 4) if decided else None,
        "hit_rate_neutral_as_fail": round(hits / (decided + neutral), 4) if decided + neutral else None,
        "wilson95_excl_neutral": [round(x, 4) for x in ci] if ci else None,
    }


def _load(conn: sqlite3.Connection) -> list[dict]:
    rows = []
    res_by = defaultdict(dict)
    for r in conn.execute("SELECT * FROM resolutions"):
        res_by[r["prediction_id"]][r["horizon_minutes"]] = dict(r)
    for p in conn.execute("SELECT * FROM predictions ORDER BY seq"):
        report = json.loads(p["report_json"])
        rule = json.loads(p["resolution_rule_json"])
        rows.append({
            "prediction_id": p["prediction_id"],
            "recorded_at": p["recorded_at_utc"],
            "decision": p["decision"],
            "active_setup": p["active_setup"] or "NONE",
            "market_state": p["market_state"] or "UNKNOWN",
            "regime_tag": p["regime_tag"] or "UNTAGGED",
            "data_status": p["data_status"],
            "conflict": bool(p["has_blocking_conflict"]),
            "config_sha256": p["config_sha256"],
            "rule": rule,
            "rules_applied": report.get("decision_rules_applied", []),
            "missing": report.get("questions", {}).get("11_missing_required_data", []),
            "res": res_by.get(p["prediction_id"], {}),
        })
    return rows


def _segment_summary(rows: list[dict], horizons: list[int], min_n: int) -> dict:
    total = len(rows)
    dec = Counter(r["decision"] for r in rows)
    directional = [r for r in rows if r["decision"] in ("LONG", "SHORT")]
    out = {
        "n_assessments": total,
        "decisions": {k: dec.get(k, 0) for k in ("LONG", "SHORT", "WAIT")},
        "coverage": round(len(directional) / total, 4) if total else None,
        "conflict_rate": round(sum(r["conflict"] for r in rows) / total, 4) if total else None,
        "data_status": dict(Counter(r["data_status"] for r in rows)),
        "wait_reasons": dict(Counter((r["rules_applied"][0][:2] if r["rules_applied"] else "?")
                                     for r in rows if r["decision"] == "WAIT")),
        "most_missing_inputs": Counter(
            m.split(": ", 1)[-1].split("=")[0] for r in rows for m in r["missing"]).most_common(10),
        "config_hashes": sorted({r["config_sha256"][:16] for r in rows}),
        "horizons": {},
    }
    for h in horizons:
        scored = [r for r in directional if h in r["res"]]
        unresolved = len(directional) - len(scored)
        system = _hit_stats([r["res"][h]["outcome"] for r in scored])
        system["unresolved"] = unresolved
        by_setup = {k: _hit_stats([r["res"][h]["outcome"] for r in scored if r["active_setup"] == k])
                    for k in sorted({r["active_setup"] for r in scored})}
        by_regime = {k: _hit_stats([r["res"][h]["outcome"] for r in scored if r["market_state"] == k])
                     for k in sorted({r["market_state"] for r in scored})}
        by_tag = {k: _hit_stats([r["res"][h]["outcome"] for r in scored if r["regime_tag"] == k])
                  for k in sorted({r["regime_tag"] for r in scored})}
        baselines = {}
        for name in ("MOMENTUM_SAME_HORIZON", "ALWAYS_LONG"):
            outs = [json.loads(r["res"][h]["baselines_json"]).get(name, {}).get("outcome") for r in scored]
            baselines[name] = _hit_stats([o for o in outs if o is not None])
            baselines[name]["note"] = "same timestamps as the system's directional calls"
        waits = [r for r in rows if r["decision"] == "WAIT" and h in r["res"]]
        wait_outcomes = dict(Counter(r["res"][h]["outcome"] for r in waits))

        cost_ok = scored and all(r["rule"]["cost_model"] is not None for r in scored)
        if cost_ok:
            ordered = sorted(scored, key=lambda r: r["res"][h]["entry_time_utc"])
            nets = [r["res"][h]["net_return_bps"] for r in ordered]
            funding_unmodelled = sum(1 for r in ordered if r["rule"]["cost_model"]["funding"] is None)
            costs = {
                "status": "COST_MODEL_PRESENT",
                "n_trades": len(nets),
                "mean_net_bps": round(sum(nets) / len(nets), 3),
                "sum_net_bps": round(sum(nets), 3),
                "max_drawdown_bps": round(max_drawdown(nets), 3),
                "funding_not_modelled_trades": funding_unmodelled,
                "notes": "Simulated: 1 unit per call, additive bps, entry/exit at 1m bar opens, overlapping "
                         "calls not netted, maker fill risk not modelled. Not a backtest of real fills.",
            }
        else:
            costs = {"status": "NO_COST_MODEL",
                     "notes": "No complete user-supplied cost model on every scored prediction: "
                              "NO profitability claim is made. Directional hit rate is not profitability."}

        n_dec = system["hit"] + system["miss"]
        best_base = max([b["hit_rate_excl_neutral"] or 0.0 for b in baselines.values()] + [0.5])
        if n_dec < min_n:
            claim = f"INSUFFICIENT_SAMPLE: {n_dec} decided calls < {min_n}; no statistical claim"
        elif system["wilson95_excl_neutral"] and system["wilson95_excl_neutral"][0] > best_base:
            claim = ("PRELIMINARY_ONLY: Wilson 95% lower bound exceeds 50% and the baselines on this sample; "
                     "requires an independent later test segment; not evidence of profitability")
        else:
            claim = "NO_EVIDENCE_OF_EDGE on this sample"
        out["horizons"][str(h)] = {
            "system": system, "by_setup": by_setup, "by_market_state": by_regime, "by_regime_tag": by_tag,
            "baselines": baselines, "wait_outcomes": wait_outcomes, "costs": costs, "claim": claim,
        }
    return out


def evaluate(conn: sqlite3.Connection, cfg: dict, run_at: datetime) -> dict:
    rows = _load(conn)
    horizons = sorted({h for r in rows for h in r["rule"]["horizons_minutes"]}) or \
        list(cfg["prediction"]["horizons_minutes"])
    min_n = cfg["evaluation"]["min_sample_for_any_claim"]
    split = cfg["evaluation"].get("test_start_utc")
    prior_runs = conn.execute("SELECT COUNT(*) FROM evaluation_runs").fetchone()[0]
    summary = {
        "run_at_utc": fmt_utc(run_at),
        "prior_evaluation_runs": prior_runs,
        "min_sample_for_any_claim": min_n,
        "test_start_utc": split,
        "segments": {},
        "warnings": [],
        "synthetic_data_warning": "Results computed on synthetic fixtures are NOT evidence of trading performance.",
    }
    if split:
        t = parse_utc(split)
        dev = [r for r in rows if parse_utc(r["recorded_at"]) < t]
        test = [r for r in rows if parse_utc(r["recorded_at"]) >= t]
        summary["segments"]["DEVELOPMENT"] = _segment_summary(dev, horizons, min_n)
        summary["segments"]["TEST"] = _segment_summary(test, horizons, min_n)
        if len(summary["segments"]["TEST"]["config_hashes"]) > 1:
            summary["warnings"].append("CONFIG_CHANGED_DURING_TEST: thresholds/config changed inside the test "
                                       "segment; it is no longer an independent test")
    else:
        summary["segments"]["ALL"] = _segment_summary(rows, horizons, min_n)
        summary["warnings"].append("NO_CHRONOLOGICAL_SPLIT: set evaluation.test_start_utc before looking at "
                                   "results to obtain an out-of-sample segment")
    if prior_runs:
        summary["warnings"].append(f"{prior_runs} earlier evaluation run(s) exist; report all of them, "
                                   "not the best one")
    with conn:
        conn.execute("INSERT INTO evaluation_runs(run_at_utc, params_json, summary_json) VALUES (?,?,?)",
                     (fmt_utc(run_at), canonical_json({"horizons": horizons, "min_n": min_n, "split": split}),
                      canonical_json(summary)))
    return summary


def render_evaluation_markdown(s: dict) -> str:
    L = ["# LAR-OFI — raport ewaluacji prognoz", "",
         f"Uruchomienie: {s['run_at_utc']} UTC. Wcześniejszych uruchomień: {s['prior_evaluation_runs']}.", "",
         f"> {s['synthetic_data_warning']}", ""]
    if s["warnings"]:
        L.append("## Ostrzeżenia")
        L += [f"- {w}" for w in s["warnings"]]
        L.append("")
    for name, seg in s["segments"].items():
        L.append(f"## Segment {name}")
        L.append(f"- Liczba ocen: {seg['n_assessments']}")
        L.append(f"- LONG / SHORT / WAIT: {seg['decisions']['LONG']} / {seg['decisions']['SHORT']} / "
                 f"{seg['decisions']['WAIT']}")
        L.append(f"- Coverage (LONG+SHORT / wszystkie): {seg['coverage']}")
        L.append(f"- Częstość konfliktów: {seg['conflict_rate']}")
        L.append(f"- Status danych: {seg['data_status']}")
        L.append(f"- Powody WAIT (reguła D1–D4): {seg['wait_reasons']}")
        L.append(f"- Najczęściej brakujące wejścia: {seg['most_missing_inputs']}")
        L.append(f"- Hashe konfiguracji: {seg['config_hashes']}")
        L.append("")
        for h, hs in seg["horizons"].items():
            sy = hs["system"]
            L.append(f"### Horyzont {h} min")
            L.append(f"- **Wniosek statystyczny:** {hs['claim']}")
            L.append("")
            L.append("| Seria | n | HIT | MISS | NEUTRAL | UNSCORABLE | trafność (bez neutral) | Wilson 95% |")
            L.append("|---|---|---|---|---|---|---|---|")
            L.append(f"| SYSTEM | {sy['n']} | {sy['hit']} | {sy['miss']} | {sy['neutral']} | {sy['unscorable']} | "
                     f"{sy['hit_rate_excl_neutral']} | {sy['wilson95_excl_neutral']} |")
            for bn, b in hs["baselines"].items():
                L.append(f"| baseline {bn} | {b['n']} | {b['hit']} | {b['miss']} | {b['neutral']} | "
                         f"{b['unscorable']} | {b['hit_rate_excl_neutral']} | {b['wilson95_excl_neutral']} |")
            for label, grp in (("setup", hs["by_setup"]), ("stan rynku", hs["by_market_state"]),
                               ("regime tag", hs["by_regime_tag"])):
                for k, b in grp.items():
                    L.append(f"| {label}: {k} | {b['n']} | {b['hit']} | {b['miss']} | {b['neutral']} | "
                             f"{b['unscorable']} | {b['hit_rate_excl_neutral']} | {b['wilson95_excl_neutral']} |")
            L.append("")
            L.append(f"- Nierozliczone prognozy kierunkowe: {sy['unresolved']}")
            L.append(f"- Wyniki po WAIT: {hs['wait_outcomes']}")
            L.append(f"- Koszty: {hs['costs']}")
            L.append("")
    return "\n".join(L)
