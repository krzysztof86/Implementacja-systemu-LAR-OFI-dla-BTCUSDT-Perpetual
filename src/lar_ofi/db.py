"""SQLite storage. Tables that carry audit history are append-only: SQLite
triggers abort any UPDATE or DELETE on them."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = "2"


class SchemaError(RuntimeError):
    pass

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS datasets (
    dataset_id TEXT PRIMARY KEY,
    manifest_json TEXT NOT NULL,
    instrument TEXT NOT NULL,
    exchange TEXT NOT NULL,
    contract_type TEXT NOT NULL,
    analysis_timeframe TEXT,
    imported_at_utc TEXT NOT NULL,
    status TEXT NOT NULL,
    issues_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS screenshots (
    screenshot_id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL REFERENCES datasets(dataset_id),
    file_name TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    indicators_json TEXT NOT NULL,
    captured_at_utc TEXT,
    data_last_update_utc TEXT,
    chart_instrument TEXT,
    view_settings TEXT,
    live_feed_confirmed INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    issues_json TEXT NOT NULL,
    UNIQUE (dataset_id, sha256)
);

CREATE TABLE IF NOT EXISTS observations (
    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id TEXT NOT NULL REFERENCES datasets(dataset_id),
    screenshot_id TEXT NOT NULL REFERENCES screenshots(screenshot_id),
    field TEXT NOT NULL,
    value_json TEXT NOT NULL,
    readability TEXT NOT NULL,
    compared_with_screenshot_id TEXT REFERENCES screenshots(screenshot_id),
    source TEXT NOT NULL,
    verified INTEGER NOT NULL,
    entered_at_utc TEXT NOT NULL,
    note TEXT,
    window_start_utc TEXT,
    window_end_utc TEXT,
    protocol_version TEXT NOT NULL,
    supersedes_id INTEGER REFERENCES observations(observation_id)
);

CREATE TABLE IF NOT EXISTS predictions (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_id TEXT NOT NULL UNIQUE,
    data_as_of_utc TEXT NOT NULL,
    decision_time_utc TEXT NOT NULL,
    recorded_at_utc TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    active_setup TEXT,
    market_state TEXT,
    data_status TEXT NOT NULL,
    has_blocking_conflict INTEGER NOT NULL,
    regime_tag TEXT,
    report_json TEXT NOT NULL,
    input_json TEXT NOT NULL,
    input_sha256 TEXT NOT NULL,
    config_json TEXT NOT NULL,
    config_sha256 TEXT NOT NULL,
    resolution_rule_json TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    record_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resolutions (
    resolution_id INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_id TEXT NOT NULL REFERENCES predictions(prediction_id),
    horizon_minutes INTEGER NOT NULL,
    resolved_at_utc TEXT NOT NULL,
    price_source TEXT NOT NULL,
    entry_time_utc TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_time_utc TEXT NOT NULL,
    exit_price REAL NOT NULL,
    return_bps REAL NOT NULL,
    signed_return_bps REAL,
    outcome TEXT NOT NULL,
    net_return_bps REAL,
    funding_crossed INTEGER,
    baselines_json TEXT NOT NULL,
    UNIQUE (prediction_id, horizon_minutes)
);

CREATE TABLE IF NOT EXISTS price_bars (
    source TEXT NOT NULL,
    instrument TEXT NOT NULL,
    exchange TEXT NOT NULL,
    contract_type TEXT NOT NULL,
    interval TEXT NOT NULL,
    open_time_utc TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    imported_at_utc TEXT NOT NULL,
    PRIMARY KEY (source, instrument, exchange, contract_type, interval, open_time_utc)
);

CREATE TABLE IF NOT EXISTS evaluation_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at_utc TEXT NOT NULL,
    params_json TEXT NOT NULL,
    summary_json TEXT NOT NULL
);
"""

APPEND_ONLY_TABLES = ("observations", "predictions", "resolutions", "evaluation_runs")


def _append_only_triggers() -> str:
    parts = []
    for table in APPEND_ONLY_TABLES:
        for op in ("UPDATE", "DELETE"):
            parts.append(
                f"CREATE TRIGGER IF NOT EXISTS {table}_no_{op.lower()} BEFORE {op} ON {table} "
                f"BEGIN SELECT RAISE(ABORT, '{table} is append-only: {op} forbidden'); END;"
            )
    # Price bars may be re-imported idempotently but never silently changed.
    parts.append(
        "CREATE TRIGGER IF NOT EXISTS price_bars_no_update BEFORE UPDATE ON price_bars "
        "BEGIN SELECT RAISE(ABORT, 'price_bars: UPDATE forbidden'); END;"
    )
    return "\n".join(parts)


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    has_meta = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='meta'").fetchone()
    if has_meta:
        row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if row is not None and row[0] != SCHEMA_VERSION:
            conn.close()
            # A v1 journal recorded predictions with as_of = recorded_at (the
            # timing flaw fixed in phase 5). It is left untouched and must not
            # be mixed with v2 records.
            raise SchemaError(
                f"{path}: journal schema v{row[0]} is not compatible with v{SCHEMA_VERSION}. "
                "Use a new --data-dir; the old journal is kept read-only as an archive.")
    conn.executescript(SCHEMA)
    conn.executescript(_append_only_triggers())
    conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
    conn.commit()
    return conn
