"""Decision report: JSON (machine) and Markdown (human, readable without the
source code)."""

from __future__ import annotations

import json
from pathlib import Path

from lar_ofi.config import canonical_json, config_hash
from lar_ofi.enums import UNKNOWN
from lar_ofi.timeutil import parse_utc, to_local_str

REPORT_VERSION = 1


def _missing_for_active(assessment: dict) -> list[str]:
    out = []
    for name, setup in sorted(assessment["setups"].items()):
        for d, v in sorted(setup["variants"].items()):
            if v["state"] in ("NONE", "INVALIDATED"):
                continue
            for c in [v["trigger"]] + v["candidate"] + v["confirmation"] + v["invalidation"]:
                if c["status"] == "UNKNOWN":
                    out.append(f"{name}/{d} {c['id']}: {c['observed']}")
    return out


def questions(a: dict) -> dict:
    ms = a["market_state"]
    return {
        "01_market_state": f"{ms['label']} (acceptance: {ms['acceptance']})",
        "02_price": (f"30M vs previous value area: {ms['auction_position_30m']}; 4H context: "
                     f"{ms['auction_position_4h_context']}; violation: {ms['violation_side']}; "
                     f"vs AVWAP: {ms['price_vs_avwap']}; last price: {ms['last_price']}"),
        "03_aggressive_trades": (f"trade aggression (footprint+CVD, one group): {ms['trade_aggression']} "
                                 f"{ms['trade_aggression_notes']}; at extreme: {ms['aggression_at_extreme']}"),
        "04_aggression_moves_price": (f"efficiency: {ms['aggression_efficiency']} (price response "
                                      f"{ms['price_response_to_aggression']}); at extreme: "
                                      f"{ms['price_response_at_extreme']}"),
        "05_visible_liquidity": (f"above: {ms['passive_liquidity_above']}; below: {ms['passive_liquidity_below']} "
                                 "(visible heatmap only; cancellations/queues not observable)"),
        "06_book_replenishment": (f"qualitative heatmap comparison (2 screenshots, not a resiliency "
                                  f"measurement): ask side {ms['ask_side_visual_change']}; bid side "
                                  f"{ms['bid_side_visual_change']}; notes: {ms['visual_change_notes'] or '-'}; "
                                  f"{ms['l2_metrics']}"),
        "07_open_interest": ms["oi_change"],
        "08_liquidations": ms["liquidations"],
        "09_most_justified_scenario": a["hypotheses"][0]["statement"],
        "10_what_invalidates_it": a["invalidation_condition"],
        "11_missing_required_data": a["blocking_issues"] + _missing_for_active(a),
    }


def build_report(assessment: dict, engine_input: dict, cfg: dict, data_dir: str | Path | None = None) -> dict:
    links = []
    for s in engine_input["screenshots"]:
        path = str(Path(data_dir) / s["stored_path"]) if data_dir else s["stored_path"]
        links.append({"screenshot_id": s["screenshot_id"], "file_name": s["file_name"], "path": path,
                      "sha256": s["sha256"], "timeframe": s["timeframe"], "indicators": s["indicators"],
                      "captured_at_utc": s["captured_at_utc"]})
    report = dict(assessment)
    report["report_version"] = REPORT_VERSION
    tz = cfg["display"]["timezone"]
    for key in ("decision_time", "data_as_of"):
        value = assessment[f"{key}_utc"]
        report[f"{key}_local"] = to_local_str(parse_utc(value) if value else None, tz)
    report["input_sha256"] = input_hash(engine_input)
    report["config_sha256"] = config_hash(cfg)
    report["evidence_links"] = links
    report["questions"] = questions(assessment)
    report["disclaimer"] = ("Analytical aid only. No order execution. Thresholds are uncalibrated project "
                            "assumptions; no probability or edge is claimed.")
    return report


def input_hash(engine_input: dict) -> str:
    import hashlib
    return hashlib.sha256(canonical_json(engine_input).encode("utf-8")).hexdigest()


def _ev_lines(items: list[dict]) -> list[str]:
    if not items:
        return ["- (brak)"]
    out = []
    for e in items:
        refs = []
        if e.get("observation_ids"):
            refs.append("obs " + ",".join(str(i) for i in e["observation_ids"]))
        if e.get("screenshot_ids"):
            refs.append("shot " + ",".join(e["screenshot_ids"]))
        ref = f" _[{'; '.join(refs)}]_" if refs else ""
        out.append(f"- **{e['kind']}** {e['statement']}{ref}")
    return out


def render_markdown(r: dict) -> str:
    L = []
    L.append(f"# LAR-OFI — raport decyzyjny: **{r['decision']}**")
    L.append("")
    L.append(f"> {r['disclaimer']}")
    L.append("")
    L.append("| Pole | Wartość |")
    L.append("|---|---|")
    rows = [
        ("Czas decyzji — decision_time (UTC)", r["decision_time_utc"]),
        ("Czas decyzji (Europe/Warsaw)", r["decision_time_local"]),
        ("Najnowsza użyta informacja — data_as_of (UTC)", r["data_as_of_utc"]),
        ("Najnowsza aktualizacja danych wykresu (UTC)", r["data_content_latest_utc"] or UNKNOWN),
        ("Instrument", f"{r['instrument']} {r['contract_type']} @ {r['exchange']}"),
        ("Interwał decyzyjny MICRO", r["analysis_timeframe"]),
        ("Zestaw danych", r["dataset_id"]),
        ("Status danych", r["data_status"]),
        ("Stan rynku", r["market_state"]["label"]),
        ("Aktywny setup", f"{r['active_setup']} ({r['active_setup_state']})"),
        ("Decyzja", r["decision"]),
        ("Horyzonty prognozy", ", ".join(f"{h} min" for h in r["horizons_minutes"])),
        ("Prawdopodobieństwo", r["probability"]),
        ("Status kalibracji", f"{r['calibration_status']} (progi skalibrowane: {r['thresholds_calibrated']})"),
        ("Źródła danych Agg.", r.get("data_source_config") or UNKNOWN),
        ("Hash wejścia / konfiguracji", f"`{r['input_sha256'][:16]}` / `{r['config_sha256'][:16]}`"),
        ("Silnik", r["engine_version"]),
    ]
    for k, v in rows:
        L.append(f"| {k} | {v} |")
    L.append("")
    L.append("## Reguły decyzji zastosowane")
    L += [f"- {x}" for x in r["decision_rules_applied"]]
    L.append("")
    L.append("## Odpowiedzi na 11 pytań prognozy")
    labels = {
        "01_market_state": "1. Jaki stan rynku obserwujemy?",
        "02_price": "2. Co pokazuje cena?",
        "03_aggressive_trades": "3. Co pokazują transakcje agresywne?",
        "04_aggression_moves_price": "4. Czy transakcje skutecznie przesuwają cenę?",
        "05_visible_liquidity": "5. Co dzieje się z widoczną płynnością?",
        "06_book_replenishment": "6. Czy mamy dane o odbudowie arkusza?",
        "07_open_interest": "7. Jak zmienia się OI?",
        "08_liquidations": "8. Czy są istotne likwidacje?",
        "09_most_justified_scenario": "9. Jaki scenariusz pozostaje najbardziej uzasadniony? (HYPOTHESIS)",
        "10_what_invalidates_it": "10. Co ten scenariusz unieważnia?",
        "11_missing_required_data": "11. Których wymaganych danych brakuje?",
    }
    for key, label in labels.items():
        val = r["questions"][key]
        L.append(f"**{label}**")
        if isinstance(val, list):
            L += [f"- {x}" for x in val] or ["- (nic)"]
        else:
            L.append(f"{val}")
        L.append("")
    L.append("## Setupy")
    for name, s in sorted(r["setups"].items()):
        L.append(f"### {name}: `{s['state']}`")
        L.append(f"Powód: {s['reason']}")
        L.append("")
        for d, v in sorted(s["variants"].items()):
            L.append(f"<details><summary>{name} {d}: {v['state']}</summary>")
            L.append("")
            L.append("| Grupa | Id | Warunek | Status | Odczyt |")
            L.append("|---|---|---|---|---|")
            for grp, conds in (("trigger", [v["trigger"]]), ("candidate", v["candidate"]),
                               ("confirmation", v["confirmation"]), ("invalidation", v["invalidation"])):
                for c in conds:
                    L.append(f"| {grp} | {c['id']} | {c['text']} | {c['status']} | {c['observed']} |")
            L.append("")
            L.append("</details>")
            L.append("")
    L.append("## Dowody ZA")
    L += _ev_lines(r["evidence_for"])
    L.append("")
    L.append("## Dowody PRZECIW")
    L += _ev_lines(r["evidence_against"])
    L.append("")
    L.append("## Obserwacje (OBSERVED) i wnioski (INFERRED)")
    L += _ev_lines(r["observed_and_inferred"])
    L.append("")
    L.append("## Hipotezy (HYPOTHESIS)")
    L += _ev_lines(r["hypotheses"])
    L.append("")
    L.append("## Niewiadome (UNKNOWN)")
    L += _ev_lines(r["unknowns"])
    L.append("")
    L.append("## Warunek potwierdzenia")
    L += [f"- {x}" for x in r["confirmation_condition"]]
    L.append("")
    L.append("## Warunek zanegowania")
    L += [f"- {x}" for x in r["invalidation_condition"]]
    L.append("")
    if r["conflicts"]:
        L.append("## Konflikty")
        L += [f"- **{c['code']}**: {c['description']}" for c in r["conflicts"]]
        L.append("")
    if r["excluded_screenshots"] or r["ignored_observations"] or r["disabled_layers_present"]:
        L.append("## Dane wykluczone")
        L += [f"- screenshot `{e['file_name']}` ({e['timeframe']}): {'; '.join(e['reasons'])}"
              for e in r["excluded_screenshots"]]
        L += [f"- obserwacja #{e['observation_id']} {e.get('field', '')}: {e['reason']}" for e in r["ignored_observations"]]
        L += [f"- wyłączona warstwa: {x}" for x in r["disabled_layers_present"]]
        L.append("")
    L.append("## Materiał dowodowy")
    L.append("| Screenshot | Interwał | Wskaźniki | Czas (UTC) | SHA-256 | Plik |")
    L.append("|---|---|---|---|---|---|")
    for s in r["evidence_links"]:
        L.append(f"| `{s['screenshot_id']}` {s['file_name']} | {s['timeframe']} | {', '.join(s['indicators'])} | "
                 f"{s['captured_at_utc'] or 'BRAK'} | `{s['sha256'][:16]}…` | [{s['path']}]({s['path']}) |")
    L.append("")
    return "\n".join(L)


def write_report(report: dict, out_dir: str | Path, stem: str) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    jp, mp = out_dir / f"{stem}.json", out_dir / f"{stem}.md"
    jp.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    mp.write_text(render_markdown(report), encoding="utf-8")
    return jp, mp
