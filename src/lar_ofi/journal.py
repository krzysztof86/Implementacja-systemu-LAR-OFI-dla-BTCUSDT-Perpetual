"""Prediction journal.

* A prediction is written once and can never be changed or deleted (SQLite
  triggers) and is chained by SHA-256 to the previous record, so edits made
  outside SQLite are detectable with `verify_journal`.
* The resolution rule (horizons, price source, entry rule, neutral band, cost
  model) is frozen INSIDE the prediction at recording time. Later changes to
  the configuration cannot re-score old predictions.
* Recording must happen within `max_record_delay_seconds` of the as-of time,
  so an outcome that is already visible cannot be "predicted".
* Resolution uses only user-imported 1m bars with an explicit source label;
  entry is the open of the first 1m bar starting at/after the recording time.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta

from lar_ofi.config import canonical_json, config_hash, cost_model
from lar_ofi.enums import Outcome
from lar_ofi.timeutil import ceil_minute, fmt_utc, parse_utc

GENESIS = "GENESIS"


class JournalError(ValueError):
    pass


def resolution_rule(cfg: dict) -> dict:
    cm = cost_model(cfg)
    band = cfg["evaluation"].get("neutral_band_bps")
    if band is None and cm is not None:
        band, band_source = cm["round_trip_bps"], "cost_model.round_trip_bps"
    elif band is not None:
        band_source = "evaluation.neutral_band_bps"
    else:
        band_source = None
    return {
        "horizons_minutes": list(cfg["prediction"]["horizons_minutes"]),
        "price_source": cfg["evaluation"]["price_source"],
        "entry_rule": "open of the first 1m bar whose open time is >= recorded_at (ceil to minute)",
        "exit_rule": "open of the 1m bar at entry_time + horizon (= close of the preceding bar)",
        "neutral_band_bps": band,
        "neutral_band_source": band_source,
        "scoring_defined": band is not None,
        "cost_model": cm,
        "baselines": ["MOMENTUM_SAME_HORIZON", "ALWAYS_LONG"],
    }


def _record_hash(fields: dict) -> str:
    return hashlib.sha256(canonical_json(fields).encode("utf-8")).hexdigest()


def record_prediction(conn: sqlite3.Connection, report: dict, engine_input: dict, cfg: dict,
                      recorded_at: datetime) -> dict:
    as_of = parse_utc(report.get("as_of_utc")) if report.get("as_of_utc") else None
    if as_of is None:
        raise JournalError("cannot journal a prediction without an as-of time")
    if recorded_at < as_of:
        raise JournalError("recorded_at is earlier than the as-of time of the data (future data)")
    delay = (recorded_at - as_of).total_seconds()
    limit = cfg["prediction"]["max_record_delay_seconds"]
    if delay > limit:
        raise JournalError(f"LATE_RECORDING: {int(delay)}s after as-of exceeds {limit}s; the outcome window "
                           "may already be visible. Re-capture fresh screenshots.")
    if report["input_sha256"] != hashlib.sha256(canonical_json(engine_input).encode()).hexdigest():
        raise JournalError("report does not belong to this engine input (hash mismatch)")

    last = conn.execute("SELECT record_hash FROM predictions ORDER BY seq DESC LIMIT 1").fetchone()
    prev_hash = last["record_hash"] if last else GENESIS
    rule = resolution_rule(cfg)
    fields = {
        "recorded_at_utc": fmt_utc(recorded_at),
        "as_of_utc": report["as_of_utc"],
        "dataset_id": report["dataset_id"],
        "decision": report["decision"],
        "active_setup": report["active_setup"],
        "market_state": report["market_state"]["label"],
        "data_status": report["data_status"],
        "has_blocking_conflict": int(bool(report["has_blocking_conflict"])),
        "regime_tag": report.get("regime_tag"),
        "report_json": canonical_json(report),
        "input_json": canonical_json(engine_input),
        "input_sha256": report["input_sha256"],
        "config_json": canonical_json(cfg),
        "config_sha256": config_hash(cfg),
        "resolution_rule_json": canonical_json(rule),
        "prev_hash": prev_hash,
    }
    prediction_id = _record_hash({"input": fields["input_sha256"], "config": fields["config_sha256"],
                                  "recorded_at": fields["recorded_at_utc"], "prev": prev_hash})[:16]
    fields["prediction_id"] = prediction_id
    record_hash = _record_hash(fields)
    with conn:
        conn.execute(
            "INSERT INTO predictions(prediction_id, recorded_at_utc, as_of_utc, dataset_id, decision, active_setup, "
            "market_state, data_status, has_blocking_conflict, regime_tag, report_json, input_json, input_sha256, "
            "config_json, config_sha256, resolution_rule_json, prev_hash, record_hash) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (prediction_id, fields["recorded_at_utc"], fields["as_of_utc"], fields["dataset_id"], fields["decision"],
             fields["active_setup"], fields["market_state"], fields["data_status"], fields["has_blocking_conflict"],
             fields["regime_tag"], fields["report_json"], fields["input_json"], fields["input_sha256"],
             fields["config_json"], fields["config_sha256"], fields["resolution_rule_json"], prev_hash, record_hash))
    return {"prediction_id": prediction_id, "record_hash": record_hash, "resolution_rule": rule,
            "recorded_at_utc": fields["recorded_at_utc"]}


def verify_journal(conn: sqlite3.Connection) -> list[str]:
    problems = []
    prev = GENESIS
    for r in conn.execute("SELECT * FROM predictions ORDER BY seq"):
        fields = {k: r[k] for k in r.keys() if k not in ("seq", "record_hash")}
        if r["prev_hash"] != prev:
            problems.append(f"{r['prediction_id']}: chain broken (prev_hash mismatch)")
        if _record_hash(fields) != r["record_hash"]:
            problems.append(f"{r['prediction_id']}: content hash mismatch (record altered)")
        if hashlib.sha256(r["input_json"].encode()).hexdigest() != r["input_sha256"]:
            problems.append(f"{r['prediction_id']}: input hash mismatch")
        prev = r["record_hash"]
    return problems


# --------------------------------------------------------------------------
# Price bars (user supplied)
# --------------------------------------------------------------------------

def _parse_bar_time(value: str) -> datetime:
    value = value.strip()
    if value.isdigit():
        from datetime import timezone
        ms = int(value)
        return datetime.fromtimestamp(ms / 1000 if ms > 10**11 else ms, tz=timezone.utc)
    dt = parse_utc(value)
    if dt is None:
        raise JournalError("empty bar time")
    return dt


def import_price_bars(conn: sqlite3.Connection, csv_path: str, source: str, imported_at: datetime) -> dict:
    """CSV header: open_time_utc,open,high,low,close (open_time ISO-8601 with
    offset, or epoch seconds/milliseconds). Existing bars are never
    overwritten; differing duplicates are reported."""
    inserted = duplicates = 0
    mismatched: list[str] = []
    errors: list[str] = []
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        need = {"open_time_utc", "open", "high", "low", "close"}
        if reader.fieldnames is None or not need.issubset(reader.fieldnames):
            raise JournalError(f"CSV must have columns {sorted(need)}")
        for i, row in enumerate(reader, start=2):
            try:
                t = _parse_bar_time(row["open_time_utc"])
                o, h, l, c = (float(row[k]) for k in ("open", "high", "low", "close"))
            except (ValueError, JournalError) as exc:
                errors.append(f"line {i}: {exc}")
                continue
            if t.second or t.microsecond:
                errors.append(f"line {i}: open time not aligned to a minute")
                continue
            if min(o, h, l, c) <= 0 or not (l <= min(o, c) and max(o, c) <= h):
                errors.append(f"line {i}: inconsistent OHLC")
                continue
            rows.append((fmt_utc(t), o, h, l, c))
    if errors:
        return {"inserted": 0, "duplicates": 0, "mismatched": [], "errors": errors}
    with conn:
        for t, o, h, l, c in rows:
            ex = conn.execute("SELECT open, high, low, close FROM price_bars WHERE source=? AND open_time_utc=?",
                              (source, t)).fetchone()
            if ex is not None:
                duplicates += 1
                if tuple(ex) != (o, h, l, c):
                    mismatched.append(t)
                continue
            conn.execute("INSERT INTO price_bars(source, open_time_utc, open, high, low, close, imported_at_utc) "
                         "VALUES (?,?,?,?,?,?,?)", (source, t, o, h, l, c, fmt_utc(imported_at)))
            inserted += 1
    return {"inserted": inserted, "duplicates": duplicates, "mismatched": mismatched, "errors": []}


def _bar_open(conn, source: str, t: datetime) -> float | None:
    r = conn.execute("SELECT open FROM price_bars WHERE source=? AND open_time_utc=?", (source, fmt_utc(t))).fetchone()
    return r["open"] if r else None


# --------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------

def _score_direction(direction: str, ret_bps: float, band: float | None) -> tuple[str, float]:
    signed = ret_bps if direction == "LONG" else -ret_bps
    if band is None:
        return Outcome.UNSCORABLE.value, signed
    if abs(ret_bps) <= band:
        return Outcome.NEUTRAL.value, signed
    return (Outcome.HIT.value if signed > 0 else Outcome.MISS.value), signed


def _funding_crossed(funding: dict, entry: datetime, exit_: datetime) -> bool:
    day = entry.replace(hour=0, minute=0, second=0, microsecond=0)
    for d in (day, day + timedelta(days=1)):
        for hhmm in funding["times_utc"]:
            hh, mm = (int(x) for x in hhmm.split(":"))
            t = d.replace(hour=hh, minute=mm)
            if entry < t <= exit_:
                return True
    return False


def resolve_predictions(conn: sqlite3.Connection, now: datetime) -> dict:
    """Resolve every (prediction, horizon) whose exit time has passed and whose
    bars exist. Already resolved pairs are skipped (and cannot be changed)."""
    done, pending = [], []
    preds = conn.execute("SELECT * FROM predictions ORDER BY seq").fetchall()
    for p in preds:
        rule = json.loads(p["resolution_rule_json"])
        recorded = parse_utc(p["recorded_at_utc"])
        entry_t = ceil_minute(recorded)
        for h in rule["horizons_minutes"]:
            if conn.execute("SELECT 1 FROM resolutions WHERE prediction_id=? AND horizon_minutes=?",
                            (p["prediction_id"], h)).fetchone():
                continue
            exit_t = entry_t + timedelta(minutes=h)
            if now < exit_t:
                pending.append({"prediction_id": p["prediction_id"], "horizon": h, "reason": "HORIZON_NOT_ELAPSED"})
                continue
            src = rule["price_source"]
            entry_px, exit_px = _bar_open(conn, src, entry_t), _bar_open(conn, src, exit_t)
            if entry_px is None or exit_px is None:
                pending.append({"prediction_id": p["prediction_id"], "horizon": h,
                                "reason": f"MISSING_BARS ({src}: {fmt_utc(entry_t)} / {fmt_utc(exit_t)})"})
                continue
            ret = (exit_px - entry_px) / entry_px * 1e4
            band = rule["neutral_band_bps"]
            decision = p["decision"]
            signed = net = None
            funding_crossed = None
            if decision in ("LONG", "SHORT"):
                outcome, signed = _score_direction(decision, ret, band)
                cm = rule["cost_model"]
                if cm is not None:
                    net = signed - cm["round_trip_bps"]
                    if cm["funding"] is not None:
                        funding_crossed = _funding_crossed(cm["funding"], entry_t, exit_t)
                        if funding_crossed:
                            net -= cm["funding"]["cost_bps_if_crossed"]
            elif band is None:
                outcome = Outcome.UNSCORABLE.value
            elif abs(ret) <= band:
                outcome = Outcome.NO_SIGNIFICANT_MOVE.value
            else:
                outcome = Outcome.MOVE_UP.value if ret > 0 else Outcome.MOVE_DOWN.value

            # Baselines use only information available at entry time.
            baselines = {}
            past_px = _bar_open(conn, src, entry_t - timedelta(minutes=h))
            if past_px is None or past_px == entry_px:
                baselines["MOMENTUM_SAME_HORIZON"] = {"direction": None, "outcome": None,
                                                      "note": "no prior bar or zero prior move"}
            else:
                mdir = "LONG" if entry_px > past_px else "SHORT"
                mout, _ = _score_direction(mdir, ret, band)
                baselines["MOMENTUM_SAME_HORIZON"] = {"direction": mdir, "outcome": mout}
            lout, _ = _score_direction("LONG", ret, band)
            baselines["ALWAYS_LONG"] = {"direction": "LONG", "outcome": lout}

            with conn:
                conn.execute(
                    "INSERT INTO resolutions(prediction_id, horizon_minutes, resolved_at_utc, price_source, "
                    "entry_time_utc, entry_price, exit_time_utc, exit_price, return_bps, signed_return_bps, outcome, "
                    "net_return_bps, funding_crossed, baselines_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (p["prediction_id"], h, fmt_utc(now), src, fmt_utc(entry_t), entry_px, fmt_utc(exit_t), exit_px,
                     ret, signed, outcome, net, None if funding_crossed is None else int(funding_crossed),
                     canonical_json(baselines)))
            done.append({"prediction_id": p["prediction_id"], "horizon": h, "outcome": outcome,
                         "return_bps": round(ret, 3)})
    return {"resolved": done, "pending": pending}
