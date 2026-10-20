"""Local command-line interface. No network access, no order placement."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from lar_ofi import __version__
from lar_ofi.config import config_hash, cost_model, load_config
from lar_ofi.db import SchemaError, connect
from lar_ofi.engine import assess
from lar_ofi.evaluation import evaluate, render_evaluation_markdown
from lar_ofi.intake import ManifestError, import_dataset
from lar_ofi.journal import JournalError, import_price_bars, record_prediction, resolve_predictions, verify_journal
from lar_ofi.observations import (ObservationError, add_observation, add_observations_from_list, build_engine_input,
                                  current_observations, observation_template, screenshots_of)
from lar_ofi.report import build_report, write_report
from lar_ofi.timeutil import TimeError, now_utc, parse_utc


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def _parse_value(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _ctx(args):
    home = Path(args.data_dir or os.environ.get("LAR_OFI_HOME", "lar_ofi_data"))
    db = Path(args.db) if args.db else home / "journal.sqlite"
    cfg = load_config(args.config)
    return home, connect(db), cfg


def _assess(conn, cfg, dataset_id, decision_time, previous_dataset, home):
    previous_states = {}
    if previous_dataset:
        prev_inp = build_engine_input(conn, previous_dataset, cfg=cfg)
        prev = assess(prev_inp, cfg)
        previous_states = {k: v["state"] for k, v in prev["setups"].items()}
    inp = build_engine_input(conn, dataset_id, decision_time=decision_time, previous_states=previous_states,
                             cfg=cfg)
    result = assess(inp, cfg)
    return inp, build_report(result, inp, cfg, data_dir=home)


def _clock():
    """Wall clock; a separate function so integration tests can simulate delays."""
    return now_utc()


def cmd_init(args):
    home, conn, cfg = _ctx(args)
    _print({"data_dir": str(home.resolve()), "config_sha256": config_hash(cfg),
            "cost_model": cost_model(cfg) or "NOT CONFIGURED (no profitability claims)",
            "l2_enabled": cfg["l2"]["enabled"], "vision_backend": cfg["vision"]["backend"]})


def cmd_import(args):
    home, conn, cfg = _ctx(args)
    try:
        res = import_dataset(conn, args.manifest, cfg, home)
    except ManifestError as exc:
        _print({"status": "REJECTED", "error": str(exc)})
        return 2
    _print(res.as_dict())
    return 0


def cmd_template(args):
    home, conn, cfg = _ctx(args)
    items = observation_template(conn, args.dataset)
    if args.out:
        Path(args.out).write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
        _print({"written": args.out, "items": len(items)})
    else:
        _print(items)


def cmd_observe(args):
    home, conn, cfg = _ctx(args)
    try:
        oid = add_observation(conn, args.dataset, args.screenshot, args.field, _parse_value(args.value),
                              readability=args.readability, compared_with=args.compared_with, note=args.note or "",
                              supersedes=args.supersedes, window_start=args.window_start,
                              window_end=args.window_end)
    except ObservationError as exc:
        _print({"status": "REJECTED", "error": str(exc)})
        return 2
    _print({"status": "OK", "observation_id": oid})
    return 0


def cmd_observe_file(args):
    home, conn, cfg = _ctx(args)
    items = json.loads(Path(args.file).read_text(encoding="utf-8"))
    ids, errors = add_observations_from_list(conn, args.dataset, items)
    _print({"status": "OK" if not errors else "REJECTED", "inserted": ids, "errors": errors})
    return 0 if not errors else 2


def cmd_confirm(args):
    home, conn, cfg = _ctx(args)
    cur = {o["observation_id"]: o for o in current_observations(conn, args.dataset)}
    o = cur.get(args.observation_id)
    if o is None:
        _print({"status": "REJECTED", "error": "observation not current in this dataset"})
        return 2
    value = _parse_value(args.value) if args.value is not None else o["value"]
    oid = add_observation(conn, args.dataset, o["screenshot_id"], o["field"], value,
                          readability=args.readability or o["readability"],
                          compared_with=o["compared_with_screenshot_id"], source="manual-confirm",
                          verified=True, note=f"confirms/corrects #{o['observation_id']} ({o['source']})",
                          supersedes=o["observation_id"], window_start=o["window_start_utc"],
                          window_end=o["window_end_utc"])
    _print({"status": "OK", "observation_id": oid})
    return 0


def cmd_show(args):
    home, conn, cfg = _ctx(args)
    _print({"screenshots": screenshots_of(conn, args.dataset),
            "observations": current_observations(conn, args.dataset)})


def cmd_analyze(args):
    home, conn, cfg = _ctx(args)
    decision_time = parse_utc(args.decision_time) if args.decision_time else None
    inp, report = _assess(conn, cfg, args.dataset, decision_time, args.previous_dataset, home)
    stem = f"analysis_{args.dataset}_{(report['decision_time_utc'] or 'no-time').replace(':', '')}"
    jp, mp = write_report(report, args.out or home / "reports", stem)
    _print({"decision": report["decision"], "data_status": report["data_status"],
            "active_setup": report["active_setup"], "json": str(jp), "markdown": str(mp)})


def cmd_predict(args):
    home, conn, cfg = _ctx(args)
    # decision_time: wall clock when the engine evaluates. The lateness limit
    # is measured from data_as_of (newest screenshot used), NOT from this time,
    # and recorded_at is read separately just before the journal write.
    decision_time = _clock()
    inp, report = _assess(conn, cfg, args.dataset, decision_time, args.previous_dataset, home)
    try:
        rec = record_prediction(conn, report, inp, cfg, recorded_at=_clock())
    except JournalError as exc:
        _print({"status": "NOT_RECORDED", "error": str(exc)})
        return 2
    stem = f"prediction_{rec['prediction_id']}"
    jp, mp = write_report(report, args.out or home / "reports", stem)
    _print({"status": "RECORDED", **rec, "decision": report["decision"], "json": str(jp), "markdown": str(mp)})
    return 0


def cmd_import_bars(args):
    home, conn, cfg = _ctx(args)
    source = args.source or cfg["evaluation"]["price_source"]
    market = {"instrument": args.instrument, "exchange": args.exchange, "contract_type": args.contract_type}
    try:
        res = import_price_bars(conn, args.csv, source, market, now_utc())
    except JournalError as exc:
        _print({"status": "REJECTED", "error": str(exc)})
        return 2
    _print({"source": source, **res})
    return 0 if not res["errors"] else 2


def cmd_resolve(args):
    home, conn, cfg = _ctx(args)
    _print(resolve_predictions(conn, now_utc()))


def cmd_evaluate(args):
    home, conn, cfg = _ctx(args)
    summary = evaluate(conn, cfg, now_utc())
    out = Path(args.out or home / "reports")
    out.mkdir(parents=True, exist_ok=True)
    stem = f"evaluation_{summary['run_at_utc'].replace(':', '')}"
    (out / f"{stem}.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / f"{stem}.md").write_text(render_evaluation_markdown(summary), encoding="utf-8")
    _print({"json": str(out / f"{stem}.json"), "markdown": str(out / f"{stem}.md")})


def cmd_verify_journal(args):
    home, conn, cfg = _ctx(args)
    problems = verify_journal(conn)
    _print({"status": "OK" if not problems else "TAMPERED", "problems": problems})
    return 0 if not problems else 3


def cmd_l2_status(args):
    home, conn, cfg = _ctx(args)
    _print({"l2_enabled": cfg["l2"]["enabled"],
            "status": "DISABLED: no event-level L2 stream connected; OFI / queue imbalance / resiliency are "
                      "not computed" if not cfg["l2"]["enabled"] else
                      "ENABLED in config: metrics still require a sequence-validated stream (lar_ofi.l2.replay)"})


def cmd_vision(args):
    from lar_ofi.vision import VisionNotConfigured, run_vision
    home, conn, cfg = _ctx(args)
    try:
        ids, errors = run_vision(conn, cfg, args.dataset, str(home))
    except VisionNotConfigured as exc:
        _print({"status": "NOT_CONFIGURED", "error": str(exc)})
        return 2
    _print({"status": "OK" if not errors else "REJECTED", "inserted_unverified": ids, "errors": errors})
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lar-ofi", description="LAR-OFI analysis aid (no order execution).")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--db", help="SQLite journal path (default <data-dir>/journal.sqlite)")
    p.add_argument("--data-dir", help="data directory (default $LAR_OFI_HOME or ./lar_ofi_data)")
    p.add_argument("--config", help="user TOML config merged over the defaults")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create the database and show effective settings").set_defaults(fn=cmd_init)
    s = sub.add_parser("import", help="import a screenshot manifest"); s.add_argument("manifest")
    s.set_defaults(fn=cmd_import)
    s = sub.add_parser("template", help="observation template for a dataset"); s.add_argument("dataset")
    s.add_argument("--out"); s.set_defaults(fn=cmd_template)
    s = sub.add_parser("observe", help="record one observation")
    s.add_argument("dataset"); s.add_argument("--screenshot", required=True); s.add_argument("--field", required=True)
    s.add_argument("--value", required=True); s.add_argument("--readability", default="CLEAR")
    s.add_argument("--compared-with"); s.add_argument("--note"); s.add_argument("--supersedes", type=int)
    s.add_argument("--window-start", help="first closed bar of the observation window (UTC, bar boundary)")
    s.add_argument("--window-end", help="close of the last closed bar before capture (UTC, bar boundary)")
    s.set_defaults(fn=cmd_observe)
    s = sub.add_parser("observe-file", help="record observations from a filled template")
    s.add_argument("dataset"); s.add_argument("file"); s.set_defaults(fn=cmd_observe_file)
    s = sub.add_parser("confirm", help="confirm or correct an observation (e.g. vision output)")
    s.add_argument("dataset"); s.add_argument("observation_id", type=int); s.add_argument("--value")
    s.add_argument("--readability"); s.set_defaults(fn=cmd_confirm)
    s = sub.add_parser("show", help="show screenshots and current observations"); s.add_argument("dataset")
    s.set_defaults(fn=cmd_show)
    s = sub.add_parser("analyze", help="assess a dataset (not journaled)"); s.add_argument("dataset")
    s.add_argument("--decision-time", help="decision time UTC (default: latest screenshot capture time)")
    s.add_argument("--previous-dataset"); s.add_argument("--out"); s.set_defaults(fn=cmd_analyze)
    s = sub.add_parser("predict", help="assess at the current time and journal the prediction (immutable)")
    s.add_argument("dataset"); s.add_argument("--previous-dataset"); s.add_argument("--out")
    s.set_defaults(fn=cmd_predict)
    s = sub.add_parser("import-bars", help="import user-supplied 1m OHLC CSV for resolution")
    s.add_argument("csv"); s.add_argument("--source")
    s.add_argument("--instrument", help="e.g. BTCUSDT (required unless the CSV has a 'symbol' column)")
    s.add_argument("--exchange", help="e.g. Bybit (required unless the CSV has an 'exchange' column)")
    s.add_argument("--contract-type", help="e.g. USDT_PERPETUAL (required unless the CSV has a "
                                           "'contract_type' column)")
    s.set_defaults(fn=cmd_import_bars)
    sub.add_parser("resolve", help="resolve predictions whose horizons have elapsed").set_defaults(fn=cmd_resolve)
    s = sub.add_parser("evaluate", help="chronological accuracy report"); s.add_argument("--out")
    s.set_defaults(fn=cmd_evaluate)
    sub.add_parser("verify-journal", help="check the hash chain").set_defaults(fn=cmd_verify_journal)
    sub.add_parser("l2-status", help="MODE B status").set_defaults(fn=cmd_l2_status)
    s = sub.add_parser("vision", help="run an explicitly configured vision backend (unverified output)")
    s.add_argument("dataset"); s.set_defaults(fn=cmd_vision)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        rc = args.fn(args)
    except (ObservationError, JournalError, TimeError, ValueError, SchemaError) as exc:
        _print({"status": "ERROR", "error": str(exc)})
        return 2
    return rc or 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
