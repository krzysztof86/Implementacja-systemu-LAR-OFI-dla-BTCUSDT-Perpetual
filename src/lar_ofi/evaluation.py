"""Chronological evaluation of journaled predictions.

* No random splits: an optional `evaluation.test_start_utc` splits the
  journal into a DEVELOPMENT segment and a TEST segment by recording time.
* Every evaluation run is appended to `evaluation_runs` and the report shows
  how many runs preceded it (multiple looks are disclosed, not hidden).
* Profitability is reported ONLY when every scored directional prediction
  carries an explicit, user-supplied cost model frozen at recording time.
* No statistical claim below `min_sample_for_any_claim` scored predictions.
* Phase 5: four results are kept apart — directional accuracy, coverage,
  after-cost result, independent-sample result. Predictions whose horizon
  windows overlap are dependent; claims use a chronologically thinned
  NON-OVERLAPPING subsample. The system is compared with each baseline on
  the SAME timestamps with an exact McNemar test (paired), Bonferroni-
  corrected; a Wilson interval is descriptive only and never compared with
  a baseline's point estimate. A claim can only come from the TEST segment.
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
            "decision_time": p["decision_time_utc"],
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


def mcnemar_exact_p(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value from the discordant pair counts."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def non_overlapping(scored: list[dict], h: int) -> list[dict]:
    """Chronological greedy thinning: keep a prediction only if its simulated
    window [entry, exit) starts at or after the exit of the last kept one."""
    kept, last_exit = [], None
    for r in sorted(scored, key=lambda r: (r["res"][h]["entry_time_utc"], r["prediction_id"])):
        entry, exit_ = r["res"][h]["entry_time_utc"], r["res"][h]["exit_time_utc"]
        if last_exit is None or entry >= last_exit:
            kept.append(r)
            last_exit = exit_
    return kept


def _n_overlapping(scored: list[dict], h: int) -> int:
    spans = sorted((r["res"][h]["entry_time_utc"], r["res"][h]["exit_time_utc"]) for r in scored)
    flagged = set()
    for i in range(1, len(spans)):
        if spans[i][0] < spans[i - 1][1]:
            flagged.update({i - 1, i})
    return len(flagged)


def _paired(rows: list[dict], h: int, name: str) -> dict:
    """System vs baseline on the same predictions: only pairs where both have a
    decided outcome (HIT/MISS)."""
    both_hit = sys_only = base_only = both_miss = 0
    for r in rows:
        so = r["res"][h]["outcome"]
        bo = json.loads(r["res"][h]["baselines_json"]).get(name, {}).get("outcome")
        if so not in ("HIT", "MISS") or bo not in ("HIT", "MISS"):
            continue
        if so == "HIT" and bo == "HIT":
            both_hit += 1
        elif so == "HIT":
            sys_only += 1
        elif bo == "HIT":
            base_only += 1
        else:
            both_miss += 1
    n = both_hit + sys_only + base_only + both_miss
    return {
        "n_pairs": n,
        "both_hit": both_hit, "system_only_hit": sys_only, "baseline_only_hit": base_only, "both_miss": both_miss,
        "system_hit_rate": round((both_hit + sys_only) / n, 4) if n else None,
        "baseline_hit_rate": round((both_hit + base_only) / n, 4) if n else None,
        "mcnemar_exact_p": round(mcnemar_exact_p(sys_only, base_only), 6),
    }


def _after_costs(rows: list[dict], h: int) -> dict:
    if not rows or not all(r["rule"]["cost_model"] is not None for r in rows):
        return {"status": "NO_COST_MODEL",
                "notes": "No complete user-supplied cost model on every scored prediction: NO profitability "
                         "claim is made. Directional hit rate is not profitability."}
    ordered = sorted(rows, key=lambda r: r["res"][h]["entry_time_utc"])
    nets = [r["res"][h]["net_return_bps"] for r in ordered]
    return {
        "status": "COST_MODEL_PRESENT",
        "n_trades": len(nets),
        "mean_net_bps": round(sum(nets) / len(nets), 3),
        "sum_net_bps": round(sum(nets), 3),
        "max_drawdown_bps": round(max_drawdown(nets), 3),
        "funding_not_modelled_trades": sum(1 for r in ordered if r["rule"]["cost_model"]["funding"] is None),
        "notes": "Simulated: 1 unit per call, additive bps, entry/exit at 1m bar opens, maker fill risk not "
                 "modelled. Not a backtest of real fills.",
    }


BASELINES = ("MOMENTUM_SAME_HORIZON", "ALWAYS_LONG")


def _segment_summary(rows: list[dict], horizons: list[int], min_n: int, independent: bool, alpha: float) -> dict:
    total = len(rows)
    dec = Counter(r["decision"] for r in rows)
    directional = [r for r in rows if r["decision"] in ("LONG", "SHORT")]
    n_comparisons = len(BASELINES) * len(horizons)
    out = {
        "independent_segment": independent,
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
        thinned = non_overlapping(scored, h)
        all_stats = _hit_stats([r["res"][h]["outcome"] for r in scored])
        all_stats["unresolved"] = len(directional) - len(scored)
        thin_stats = _hit_stats([r["res"][h]["outcome"] for r in thinned])
        waits = [r for r in rows if r["decision"] == "WAIT" and h in r["res"]]
        comparisons = {name: {"non_overlapping": _paired(thinned, h, name),
                              "all_scored_descriptive": _paired(scored, h, name)} for name in BASELINES}

        n_dec = thin_stats["hit"] + thin_stats["miss"]
        threshold = alpha / n_comparisons
        if not independent:
            claim = ("IN_SAMPLE_DESCRIPTIVE_ONLY: this segment is not an independent test (set "
                     "evaluation.test_start_utc before collecting outcomes)")
        elif n_dec < min_n:
            claim = f"INSUFFICIENT_SAMPLE: {n_dec} decided non-overlapping calls < {min_n}; no statistical claim"
        elif all(c["non_overlapping"]["system_only_hit"] > c["non_overlapping"]["baseline_only_hit"]
                 and c["non_overlapping"]["mcnemar_exact_p"] < threshold for c in comparisons.values()):
            claim = (f"PRELIMINARY_ONLY: directional accuracy better than every baseline on paired, "
                     f"non-overlapping TEST predictions (McNemar exact p < {threshold:.4g}, Bonferroni over "
                     f"{n_comparisons} comparisons). Serial dependence beyond the horizon is not modelled; "
                     "this is not evidence of after-cost profitability")
        else:
            claim = "NO_EVIDENCE_OF_EDGE over the baselines on this segment"
        out["horizons"][str(h)] = {
            "directional_accuracy": {
                "all_scored_descriptive": all_stats,
                "non_overlapping": thin_stats,
                "note": "Wilson intervals are descriptive; they are not compared with baseline point estimates.",
            },
            "overlap": {
                "n_scored": len(scored), "n_non_overlapping": len(thinned),
                "n_in_overlapping_windows": _n_overlapping(scored, h),
                "note": "Predictions with intersecting [entry, exit) windows share price paths and are not "
                        "independent; claims use the non-overlapping subsample. The 5 and 15 minute "
                        "horizons of one prediction are never pooled.",
            },
            "baseline_comparison": comparisons,
            "after_costs": {"non_overlapping": _after_costs(thinned, h),
                            "all_scored_descriptive": _after_costs(scored, h)},
            "independent_sample": ({"status": "TEST_SEGMENT_NON_OVERLAPPING", "accuracy": thin_stats}
                                   if independent else {"status": "NOT_AN_INDEPENDENT_SAMPLE"}),
            "breakdowns_descriptive": {
                "by_setup": {k: _hit_stats([r["res"][h]["outcome"] for r in scored if r["active_setup"] == k])
                             for k in sorted({r["active_setup"] for r in scored})},
                "by_market_state": {k: _hit_stats([r["res"][h]["outcome"] for r in scored
                                                   if r["market_state"] == k])
                                    for k in sorted({r["market_state"] for r in scored})},
                "by_regime_tag": {k: _hit_stats([r["res"][h]["outcome"] for r in scored if r["regime_tag"] == k])
                                  for k in sorted({r["regime_tag"] for r in scored})},
            },
            "wait_outcomes": dict(Counter(r["res"][h]["outcome"] for r in waits)),
            "claim": claim,
        }
    return out


def evaluate(conn: sqlite3.Connection, cfg: dict, run_at: datetime) -> dict:
    rows = _load(conn)
    horizons = sorted({h for r in rows for h in r["rule"]["horizons_minutes"]}) or \
        list(cfg["prediction"]["horizons_minutes"])
    min_n = cfg["evaluation"]["min_sample_for_any_claim"]
    alpha = cfg["evaluation"]["alpha"]
    split = cfg["evaluation"].get("test_start_utc")
    prior_runs = conn.execute("SELECT COUNT(*) FROM evaluation_runs").fetchone()[0]
    summary = {
        "run_at_utc": fmt_utc(run_at),
        "prior_evaluation_runs": prior_runs,
        "min_sample_for_any_claim": min_n,
        "alpha": alpha,
        "test_start_utc": split,
        "segments": {},
        "warnings": [],
        "synthetic_data_warning": "Results computed on synthetic fixtures are NOT evidence of trading performance.",
    }
    if split:
        t = parse_utc(split)
        dev = [r for r in rows if parse_utc(r["recorded_at"]) < t]
        test = [r for r in rows if parse_utc(r["recorded_at"]) >= t]
        summary["segments"]["DEVELOPMENT"] = _segment_summary(dev, horizons, min_n, False, alpha)
        test_seg = _segment_summary(test, horizons, min_n, True, alpha)
        if len(test_seg["config_hashes"]) > 1:
            summary["warnings"].append("CONFIG_CHANGED_DURING_TEST: thresholds/config changed inside the test "
                                       "segment; it is no longer an independent test")
            test_seg = _segment_summary(test, horizons, min_n, False, alpha)
        summary["segments"]["TEST"] = test_seg
    else:
        summary["segments"]["ALL"] = _segment_summary(rows, horizons, min_n, False, alpha)
        summary["warnings"].append("NO_CHRONOLOGICAL_SPLIT: set evaluation.test_start_utc before looking at "
                                   "results to obtain an out-of-sample segment")
    if prior_runs:
        summary["warnings"].append(f"{prior_runs} earlier evaluation run(s) exist; report all of them, "
                                   "not the best one")
    with conn:
        conn.execute("INSERT INTO evaluation_runs(run_at_utc, params_json, summary_json) VALUES (?,?,?)",
                     (fmt_utc(run_at), canonical_json({"horizons": horizons, "min_n": min_n, "split": split,
                                                       "alpha": alpha}),
                      canonical_json(summary)))
    return summary


def _stats_row(label: str, b: dict) -> str:
    return (f"| {label} | {b['n']} | {b['hit']} | {b['miss']} | {b['neutral']} | {b['unscorable']} | "
            f"{b['hit_rate_excl_neutral']} | {b['wilson95_excl_neutral']} |")


def render_evaluation_markdown(s: dict) -> str:
    L = ["# LAR-OFI — raport ewaluacji prognoz", "",
         f"Uruchomienie: {s['run_at_utc']} UTC. Wcześniejszych uruchomień: {s['prior_evaluation_runs']}.", "",
         f"> {s['synthetic_data_warning']}", ""]
    if s["warnings"]:
        L.append("## Ostrzeżenia")
        L += [f"- {w}" for w in s["warnings"]]
        L.append("")
    for name, seg in s["segments"].items():
        L.append(f"## Segment {name} ({'niezależny test' if seg['independent_segment'] else 'nie jest niezależną próbą'})")
        L.append("### Coverage")
        L.append(f"- Liczba ocen: {seg['n_assessments']}; LONG / SHORT / WAIT: {seg['decisions']['LONG']} / "
                 f"{seg['decisions']['SHORT']} / {seg['decisions']['WAIT']}; coverage: {seg['coverage']}")
        L.append(f"- Częstość konfliktów: {seg['conflict_rate']}; status danych: {seg['data_status']}")
        L.append(f"- Powody WAIT (D1–D4): {seg['wait_reasons']}; najczęściej brakujące: {seg['most_missing_inputs']}")
        L.append(f"- Hashe konfiguracji: {seg['config_hashes']}")
        L.append("")
        for h, hs in seg["horizons"].items():
            da, ov = hs["directional_accuracy"], hs["overlap"]
            L.append(f"### Horyzont {h} min")
            L.append(f"- **Wniosek:** {hs['claim']}")
            L.append(f"- Nakładanie: {ov['n_scored']} rozliczonych, {ov['n_non_overlapping']} bez nakładania, "
                     f"{ov['n_in_overlapping_windows']} w nakładających się oknach")
            L.append("")
            L.append("**Trafność kierunkowa**")
            L.append("")
            L.append("| Próba | n | HIT | MISS | NEUTRAL | UNSCORABLE | trafność (bez neutral) | Wilson 95% (opisowo) |")
            L.append("|---|---|---|---|---|---|---|---|")
            L.append(_stats_row("bez nakładania", da["non_overlapping"]))
            L.append(_stats_row("wszystkie (opisowo)", da["all_scored_descriptive"]))
            for group, items in hs["breakdowns_descriptive"].items():
                for k, b in items.items():
                    L.append(_stats_row(f"{group}: {k} (opisowo)", b))
            L.append("")
            L.append("**Porównanie parowane z baseline'ami (próba bez nakładania)**")
            L.append("")
            L.append("| Baseline | par | oba HIT | tylko system | tylko baseline | oba MISS | McNemar p |")
            L.append("|---|---|---|---|---|---|---|")
            for bn, c in hs["baseline_comparison"].items():
                n = c["non_overlapping"]
                L.append(f"| {bn} | {n['n_pairs']} | {n['both_hit']} | {n['system_only_hit']} | "
                         f"{n['baseline_only_hit']} | {n['both_miss']} | {n['mcnemar_exact_p']} |")
            L.append("")
            L.append(f"**Wynik po kosztach (bez nakładania):** {hs['after_costs']['non_overlapping']}")
            L.append("")
            L.append(f"**Wynik niezależnej próby:** {hs['independent_sample']}")
            L.append("")
            L.append(f"- Nierozliczone prognozy kierunkowe: {da['all_scored_descriptive']['unresolved']}; "
                     f"wyniki po WAIT: {hs['wait_outcomes']}")
            L.append("")
    return "\n".join(L)
