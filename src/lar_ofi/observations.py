"""Observation extractor: manual entry, corrections and the engine input
builder.

Observations are append-only. A correction is a new row whose
`supersedes_id` points to the corrected row; history is never lost. Every
observation is tied to exactly one screenshot (plus, for comparison fields,
the earlier screenshot it was compared with).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from lar_ofi.enums import UNKNOWN, Readability
from lar_ofi.registry import FIELDS, INDICATORS, PROTOCOL_VERSION, RegistryError, check_value, field_spec
from lar_ofi.timeutil import TIMEFRAME_SECONDS, TimeError, floor_bar, fmt_utc, now_utc, parse_utc


class ObservationError(ValueError):
    pass


def _screenshot(conn: sqlite3.Connection, dataset_id: str, ref: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM screenshots WHERE dataset_id = ? AND (screenshot_id = ? OR file_name = ?)",
        (dataset_id, ref, ref)).fetchall()
    if not row:
        raise ObservationError(f"screenshot {ref!r} not found in dataset {dataset_id}")
    if len(row) > 1:
        raise ObservationError(f"screenshot reference {ref!r} is ambiguous; use the screenshot_id")
    return row[0]


def _prepare(conn: sqlite3.Connection, dataset_id: str, screenshot: str, field_name: str, value,
             readability: str = "CLEAR", compared_with: str | None = None, source: str = "manual",
             verified: bool = True, note: str = "", supersedes: int | None = None,
             entered_at: datetime | None = None, window_start: str | None = None,
             window_end: str | None = None) -> tuple:
    """Validate one observation and return the row to insert."""
    try:
        spec = field_spec(field_name)
    except RegistryError as exc:
        raise ObservationError(str(exc)) from exc
    shot = _screenshot(conn, dataset_id, screenshot)
    try:
        readability = Readability(str(readability).upper())
    except ValueError:
        raise ObservationError(f"readability must be one of {[r.value for r in Readability]}") from None

    indicators = json.loads(shot["indicators_json"])
    if not any(ind in spec.indicators for ind in indicators):
        raise ObservationError(
            f"{field_name}: screenshot {shot['file_name']} shows {indicators}, none of which supplies "
            f"this field (needs one of {list(spec.indicators)})")
    if shot["timeframe"] not in spec.timeframes:
        raise ObservationError(
            f"{field_name}: defined for {spec.timeframes}, screenshot is {shot['timeframe']}")

    if readability is Readability.UNREADABLE:
        stored_value = UNKNOWN  # never keep a guessed value for an unreadable reading
    else:
        try:
            stored_value = check_value(spec, value)
        except RegistryError as exc:
            raise ObservationError(str(exc)) from exc

    w_start = w_end = None
    if spec.requires_window and stored_value != UNKNOWN:
        w_start, w_end = _check_window(field_name, shot, window_start, window_end)
    elif window_start or window_end:
        raise ObservationError(f"{field_name}: window given but the field has no observation window "
                               "(or the value is UNKNOWN)")

    compared_id = None
    if spec.requires_comparison:
        if not compared_with:
            raise ObservationError(
                f"{field_name} compares two heatmap screenshots in time; 'compared_with' "
                "(the EARLIER screenshot) is required. A single snapshot cannot show replenishment.")
        other = _screenshot(conn, dataset_id, compared_with)
        if other["screenshot_id"] == shot["screenshot_id"]:
            raise ObservationError("compared_with must be a different screenshot")
        compared_id = other["screenshot_id"]
    elif compared_with:
        raise ObservationError(f"{field_name} is not a comparison field; do not pass compared_with")

    if supersedes is not None:
        prev = conn.execute("SELECT * FROM observations WHERE observation_id = ?", (supersedes,)).fetchone()
        if prev is None or prev["dataset_id"] != dataset_id:
            raise ObservationError(f"observation {supersedes} not found in dataset {dataset_id}")
        if prev["field"] != field_name or prev["screenshot_id"] != shot["screenshot_id"]:
            raise ObservationError("a correction must keep the same field and screenshot")

    entered_at = entered_at or now_utc()
    return (dataset_id, shot["screenshot_id"], field_name, json.dumps(stored_value), readability.value,
            compared_id, source, int(bool(verified)), fmt_utc(entered_at), note, fmt_utc(w_start),
            fmt_utc(w_end), PROTOCOL_VERSION, supersedes)


def _check_window(field_name: str, shot, window_start, window_end):
    """OBS-PROTOCOL-2: window-based readings name the closed bars they were
    read from, so another observer can repeat the reading on the same image."""
    if not window_start or not window_end:
        raise ObservationError(
            f"{field_name}: window_start_utc and window_end_utc are required (closed bars of the "
            f"screenshot's timeframe the reading was taken from)")
    try:
        start, end = parse_utc(window_start), parse_utc(window_end)
    except TimeError as exc:
        raise ObservationError(f"{field_name}: {exc}") from exc
    tf = shot["timeframe"]
    if start >= end:
        raise ObservationError(f"{field_name}: window_start_utc must precede window_end_utc")
    for t, name in ((start, "window_start_utc"), (end, "window_end_utc")):
        if floor_bar(t, tf) != t:
            raise ObservationError(f"{field_name}: {name} must lie on a {tf} bar boundary "
                                   f"({TIMEFRAME_SECONDS[tf]} s, UTC-aligned)")
    captured = parse_utc(shot["captured_at_utc"]) if shot["captured_at_utc"] else None
    if captured is not None and end > captured:
        raise ObservationError(f"{field_name}: window ends after the screenshot was captured")
    return start, end


_INSERT = ("INSERT INTO observations(dataset_id, screenshot_id, field, value_json, readability, "
           "compared_with_screenshot_id, source, verified, entered_at_utc, note, window_start_utc, "
           "window_end_utc, protocol_version, supersedes_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)")


def add_observation(conn: sqlite3.Connection, dataset_id: str, screenshot: str, field_name: str, value,
                    **kwargs) -> int:
    row = _prepare(conn, dataset_id, screenshot, field_name, value, **kwargs)
    with conn:
        cur = conn.execute(_INSERT, row)
    return int(cur.lastrowid)


def add_observations_from_list(conn: sqlite3.Connection, dataset_id: str, items: list[dict],
                               source: str = "manual") -> tuple[list[int], list[str]]:
    """Bulk entry, all-or-nothing. Items whose value is null are skipped
    (template placeholders) unless marked UNREADABLE. Returns (ids, errors)."""
    errors: list[str] = []
    rows = []
    for i, item in enumerate(items):
        if item.get("value") is None and str(item.get("readability", "CLEAR")).upper() != "UNREADABLE":
            continue
        try:
            rows.append(_prepare(
                conn, dataset_id, item["screenshot"], item["field"], item.get("value"),
                readability=item.get("readability", "CLEAR"), compared_with=item.get("compared_with"),
                source=item.get("source", source), verified=item.get("verified", True),
                note=item.get("note", ""), supersedes=item.get("supersedes"),
                window_start=item.get("window_start_utc"), window_end=item.get("window_end_utc")))
        except (ObservationError, KeyError) as exc:
            errors.append(f"item {i} ({item.get('field')}): {exc}")
    if errors:
        return [], errors
    ids = []
    with conn:
        for row in rows:
            ids.append(int(conn.execute(_INSERT, row).lastrowid))
    return ids, []


def current_observations(conn: sqlite3.Connection, dataset_id: str) -> list[dict]:
    rows = conn.execute("SELECT * FROM observations WHERE dataset_id = ? ORDER BY observation_id",
                        (dataset_id,)).fetchall()
    superseded = {r["supersedes_id"] for r in rows if r["supersedes_id"] is not None}
    out = []
    for r in rows:
        if r["observation_id"] in superseded:
            continue
        out.append({
            "observation_id": r["observation_id"],
            "screenshot_id": r["screenshot_id"],
            "field": r["field"],
            "value": json.loads(r["value_json"]),
            "readability": r["readability"],
            "compared_with_screenshot_id": r["compared_with_screenshot_id"],
            "source": r["source"],
            "verified": bool(r["verified"]),
            "entered_at_utc": r["entered_at_utc"],
            "note": r["note"] or "",
            "window_start_utc": r["window_start_utc"],
            "window_end_utc": r["window_end_utc"],
            "protocol_version": r["protocol_version"],
            "supersedes_id": r["supersedes_id"],
        })
    return out


def observation_history(conn: sqlite3.Connection, dataset_id: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM observations WHERE dataset_id = ? ORDER BY observation_id", (dataset_id,))]


def screenshots_of(conn: sqlite3.Connection, dataset_id: str) -> list[dict]:
    out = []
    for r in conn.execute("SELECT * FROM screenshots WHERE dataset_id = ? ORDER BY file_name", (dataset_id,)):
        out.append({
            "screenshot_id": r["screenshot_id"],
            "file_name": r["file_name"],
            "stored_path": r["stored_path"],
            "sha256": r["sha256"],
            "timeframe": r["timeframe"],
            "indicators": json.loads(r["indicators_json"]),
            "captured_at_utc": r["captured_at_utc"],
            "data_last_update_utc": r["data_last_update_utc"],
            "chart_instrument": r["chart_instrument"],
            "view_settings": r["view_settings"],
            "live_feed_confirmed": bool(r["live_feed_confirmed"]),
            "notes": r["notes"] or "",
            "issues": json.loads(r["issues_json"]),
        })
    return out


def observation_template(conn: sqlite3.Connection, dataset_id: str) -> list[dict]:
    """One placeholder per (screenshot, applicable enabled field). The user
    fills `value` (or sets readability UNREADABLE) and imports the file."""
    items = []
    for shot in screenshots_of(conn, dataset_id):
        for spec in FIELDS.values():
            if not spec.enabled or shot["timeframe"] not in spec.timeframes:
                continue
            if not any(i in spec.indicators for i in shot["indicators"]):
                continue
            if spec.name == "last_price" and not any(INDICATORS[i].enabled for i in shot["indicators"]
                                                      if i in INDICATORS):
                continue
            item = {
                "screenshot": shot["screenshot_id"],
                "file_name": shot["file_name"],
                "timeframe": shot["timeframe"],
                "field": spec.name,
                "value": None,
                "readability": "CLEAR",
                "allowed": list(spec.allowed) + [UNKNOWN] if spec.kind == "enum" else spec.kind,
                "help": spec.description,
                "protocol": PROTOCOL_VERSION,
                "measurement": spec.protocol.get("measurement"),
                "procedure": spec.protocol.get("procedure"),
                "record_UNKNOWN_when": spec.protocol.get("unknown_when"),
            }
            if spec.protocol.get("quantitative_data"):
                item["reliable_measurement_needs"] = spec.protocol["quantitative_data"]
            if spec.requires_window:
                item["window_start_utc"] = None
                item["window_end_utc"] = None
            if spec.requires_comparison:
                item["compared_with"] = None
            items.append(item)
    return items


def dataset_row(conn: sqlite3.Connection, dataset_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM datasets WHERE dataset_id = ?", (dataset_id,)).fetchone()
    if row is None:
        raise ObservationError(f"dataset {dataset_id} not found")
    return row


def build_engine_input(conn: sqlite3.Connection, dataset_id: str, decision_time: datetime | None = None,
                       previous_states: dict | None = None, cfg: dict | None = None) -> dict:
    """Snapshot of everything the engine may look at. The engine is a pure
    function of this dict and the configuration, so the dict (and its hash)
    is what the prediction journal freezes."""
    ds = dataset_row(conn, dataset_id)
    manifest = json.loads(ds["manifest_json"])
    shots = screenshots_of(conn, dataset_id)
    if decision_time is None:
        # `analyze` without an explicit time: evaluate at the latest capture.
        stamps = [parse_utc(s["captured_at_utc"]) for s in shots if s["captured_at_utc"]]
        decision_time = max(stamps) if stamps else None
    micro_decision = manifest.get("analysis_timeframe") or (
        cfg["timeframes"]["micro_decision"] if cfg else "5M")
    return {
        "dataset_id": dataset_id,
        "instrument": ds["instrument"],
        "exchange": ds["exchange"],
        "contract_type": ds["contract_type"],
        "analysis_timeframe": micro_decision,
        "data_source_config": manifest.get("data_source_config"),
        "regime_tag": manifest.get("regime_tag"),
        "dataset_issues": json.loads(ds["issues_json"]),
        "decision_time_utc": fmt_utc(decision_time),
        "screenshots": shots,
        "observations": current_observations(conn, dataset_id),
        "previous_states": previous_states or {},
    }
