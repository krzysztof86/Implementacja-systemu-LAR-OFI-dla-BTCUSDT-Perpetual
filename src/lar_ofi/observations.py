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
from lar_ofi.registry import FIELDS, INDICATORS, RegistryError, check_value, field_spec
from lar_ofi.timeutil import fmt_utc, now_utc, parse_utc


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
             entered_at: datetime | None = None) -> tuple:
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
            compared_id, source, int(bool(verified)), fmt_utc(entered_at), note, supersedes)


_INSERT = ("INSERT INTO observations(dataset_id, screenshot_id, field, value_json, readability, "
           "compared_with_screenshot_id, source, verified, entered_at_utc, note, supersedes_id) "
           "VALUES (?,?,?,?,?,?,?,?,?,?,?)")


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
                note=item.get("note", ""), supersedes=item.get("supersedes")))
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
            }
            if spec.requires_comparison:
                item["compared_with"] = None
            items.append(item)
    return items


def dataset_row(conn: sqlite3.Connection, dataset_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM datasets WHERE dataset_id = ?", (dataset_id,)).fetchone()
    if row is None:
        raise ObservationError(f"dataset {dataset_id} not found")
    return row


def build_engine_input(conn: sqlite3.Connection, dataset_id: str, as_of: datetime | None = None,
                       previous_states: dict | None = None) -> dict:
    """Snapshot of everything the engine may look at. The engine is a pure
    function of this dict and the configuration, so the dict (and its hash)
    is what the prediction journal freezes."""
    ds = dataset_row(conn, dataset_id)
    manifest = json.loads(ds["manifest_json"])
    shots = screenshots_of(conn, dataset_id)
    if as_of is None:
        stamps = [parse_utc(s["captured_at_utc"]) for s in shots if s["captured_at_utc"]]
        as_of = max(stamps) if stamps else None
    return {
        "dataset_id": dataset_id,
        "instrument": ds["instrument"],
        "exchange": ds["exchange"],
        "contract_type": ds["contract_type"],
        "analysis_timeframe": ds["analysis_timeframe"],
        "data_source_config": manifest.get("data_source_config"),
        "regime_tag": manifest.get("regime_tag"),
        "dataset_issues": json.loads(ds["issues_json"]),
        "as_of_utc": fmt_utc(as_of),
        "screenshots": shots,
        "observations": current_observations(conn, dataset_id),
        "previous_states": previous_states or {},
    }
