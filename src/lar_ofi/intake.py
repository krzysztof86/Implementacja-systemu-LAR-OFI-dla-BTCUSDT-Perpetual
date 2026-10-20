"""Data intake: manifest validation and screenshot import.

A manifest describes ONE analysis moment: a set of OpenMarket screenshots of
the same instrument, each with timeframe, indicators and capture time.
Importing the same manifest + files twice yields the same dataset_id and
inserts nothing the second time.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from lar_ofi.config import canonical_json
from lar_ofi.registry import INDICATORS, TIMEFRAMES
from lar_ofi.timeutil import TimeError, fmt_utc, now_utc, parse_utc

MANIFEST_VERSION = 1
MAX_INDICATORS_PER_WORKSPACE = 3  # account limit stated by the user
REQUIRED_KEYS = ("manifest_version", "instrument", "exchange", "contract_type", "screenshots")

_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
)


class ManifestError(ValueError):
    """The dataset as a whole is rejected."""


@dataclass
class ImportResult:
    dataset_id: str | None
    created: bool
    status: str
    dataset_issues: list[str] = field(default_factory=list)
    accepted: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "dataset_id": self.dataset_id,
            "created": self.created,
            "status": self.status,
            "dataset_issues": self.dataset_issues,
            "accepted": self.accepted,
            "rejected": self.rejected,
        }


def sniff_image(data: bytes) -> str | None:
    for magic, ext in _MAGIC:
        if data.startswith(magic):
            return ext
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_manifest(path: str | Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"manifest is not valid JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ManifestError("manifest must be a JSON object")
    return manifest


def validate_manifest_header(manifest: dict, cfg: dict) -> list[str]:
    """Dataset-level checks. Raises ManifestError on fatal problems; returns
    non-fatal dataset issues."""
    missing = [k for k in REQUIRED_KEYS if k not in manifest]
    if missing:
        raise ManifestError(f"manifest is missing required keys: {missing}")
    if manifest["manifest_version"] != MANIFEST_VERSION:
        raise ManifestError(f"unsupported manifest_version {manifest['manifest_version']!r}")
    inst = cfg["instrument"]
    checks = (
        ("instrument", inst["symbol"]),
        ("exchange", inst["exchange"]),
        ("contract_type", inst["contract_type"]),
    )
    for key, expected in checks:
        got = str(manifest[key]).strip()
        if got.upper() != expected.upper():
            raise ManifestError(
                f"WRONG_{key.upper()}: manifest says {got!r}, this system only analyses {expected!r}")
    if not isinstance(manifest["screenshots"], list):
        raise ManifestError("'screenshots' must be a list")
    issues = []
    tf = manifest.get("analysis_timeframe")
    if tf is not None and tf not in TIMEFRAMES:
        raise ManifestError(f"analysis_timeframe {tf!r} not in {TIMEFRAMES}")
    platform = str(manifest.get("source_platform") or "")
    if "openmarket" not in platform.lower():
        issues.append(f"SOURCE_PLATFORM_UNVERIFIED: {platform or 'not stated'} (expected OpenMarket.xyz)")
    if not manifest.get("data_source_config"):
        issues.append("DATA_SOURCE_CONFIG_UNKNOWN: aggregated ('Agg.') indicator venues not stated")
    if len(manifest["screenshots"]) == 0:
        issues.append("NO_SCREENSHOTS")
    return issues


def _check_screenshot(entry: dict, base_dir: Path, cfg: dict, import_time: datetime) -> tuple[dict, list[str], list[str], bytes | None]:
    """Returns (record, fatal_issues, flags, file_bytes)."""
    fatal: list[str] = []
    flags: list[str] = []
    rec: dict = {"file_name": entry.get("file")}
    if not isinstance(entry, dict) or not entry.get("file"):
        return rec, ["MISSING_FILE_FIELD"], flags, None

    tf = entry.get("timeframe")
    if tf not in TIMEFRAMES:
        fatal.append(f"INVALID_TIMEFRAME: {tf!r} not in {TIMEFRAMES}")
    rec["timeframe"] = tf

    indicators = entry.get("indicators")
    if not isinstance(indicators, list) or not indicators:
        fatal.append("NO_INDICATORS_DECLARED")
        indicators = []
    for name in indicators:
        spec = INDICATORS.get(name)
        if spec is None:
            fatal.append(f"UNKNOWN_INDICATOR: {name!r}")
            continue
        if tf in TIMEFRAMES and tf not in spec.timeframes:
            flags.append(f"INDICATOR_TIMEFRAME_UNUSUAL: {name} on {tf} (defined for {spec.timeframes})")
        if not spec.enabled:
            flags.append(f"DISABLED_LAYER_INDICATOR: {name} (layer {spec.layer}) is ignored by the engine")
    if len(indicators) > MAX_INDICATORS_PER_WORKSPACE:
        flags.append(f"MORE_THAN_{MAX_INDICATORS_PER_WORKSPACE}_INDICATORS: exceeds workspace limit, check source")
    rec["indicators"] = indicators

    chart_inst = entry.get("chart_instrument")
    if chart_inst is None:
        flags.append("CHART_INSTRUMENT_NOT_STATED")
    elif str(chart_inst).strip().upper() != cfg["instrument"]["symbol"].upper():
        fatal.append(f"WRONG_INSTRUMENT: screenshot shows {chart_inst!r}, expected {cfg['instrument']['symbol']!r}")
    rec["chart_instrument"] = chart_inst

    captured = last_update = None
    try:
        captured = parse_utc(entry.get("captured_at_utc"))
    except TimeError as exc:
        fatal.append(f"TIMESTAMP_INVALID: {exc}")
    try:
        last_update = parse_utc(entry.get("data_last_update_utc"))
    except TimeError as exc:
        fatal.append(f"LAST_UPDATE_INVALID: {exc}")
    if captured is None and not any(i.startswith("TIMESTAMP_INVALID") for i in fatal):
        flags.append("TIMESTAMP_MISSING")
    if captured is not None and captured > import_time:
        fatal.append("CAPTURED_IN_FUTURE: capture time is later than import time")
    if last_update is None:
        flags.append("LAST_UPDATE_UNKNOWN")
    if captured is not None and last_update is not None and last_update > captured:
        fatal.append("LAST_UPDATE_AFTER_CAPTURE: data cannot be newer than the screenshot")
    rec["captured_at_utc"] = fmt_utc(captured)
    rec["data_last_update_utc"] = fmt_utc(last_update)
    rec["notes"] = entry.get("notes", "")

    path = (base_dir / entry["file"]).resolve()
    data = None
    if not path.is_file():
        fatal.append(f"FILE_NOT_FOUND: {entry['file']}")
    else:
        data = path.read_bytes()
        if len(data) == 0:
            fatal.append("EMPTY_FILE")
            data = None
        else:
            ext = sniff_image(data)
            if ext is None:
                fatal.append("NOT_AN_IMAGE: only PNG, JPEG and WEBP are accepted")
                data = None
            else:
                rec["sha256"] = sha256_bytes(data)
                rec["ext"] = ext
    return rec, fatal, flags, data


def compute_dataset_id(manifest: dict, file_hashes: list[str | None]) -> str:
    body = {"manifest": manifest, "file_sha256": file_hashes}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()[:16]


def import_dataset(conn: sqlite3.Connection, manifest_path: str | Path, cfg: dict,
                   data_dir: str | Path, import_time: datetime | None = None) -> ImportResult:
    manifest_path = Path(manifest_path)
    data_dir = Path(data_dir)
    import_time = import_time or now_utc()
    manifest = load_manifest(manifest_path)
    dataset_issues = validate_manifest_header(manifest, cfg)
    base_dir = manifest_path.parent

    checked = [_check_screenshot(e, base_dir, cfg, import_time) for e in manifest["screenshots"]]
    dataset_id = compute_dataset_id(manifest, [rec.get("sha256") for rec, *_ in checked])

    existing = conn.execute("SELECT status, issues_json FROM datasets WHERE dataset_id = ?",
                            (dataset_id,)).fetchone()
    if existing is not None:
        accepted = [dict(r) for r in conn.execute(
            "SELECT screenshot_id, file_name, timeframe, issues_json FROM screenshots WHERE dataset_id = ?",
            (dataset_id,))]
        return ImportResult(dataset_id, False, existing["status"],
                            json.loads(existing["issues_json"]) + ["ALREADY_IMPORTED: no rows added"],
                            accepted, [])

    seen_hashes: set[str] = set()
    accepted: list[dict] = []
    rejected: list[dict] = []
    to_store: list[tuple[dict, list[str], bytes]] = []
    for rec, fatal, flags, data in checked:
        sha = rec.get("sha256")
        if sha is not None and sha in seen_hashes:
            fatal = fatal + ["DUPLICATE_FILE_IN_DATASET"]
        if fatal:
            rejected.append({"file_name": rec.get("file_name"), "issues": fatal + flags})
            continue
        seen_hashes.add(sha)
        other = conn.execute("SELECT dataset_id FROM screenshots WHERE sha256 = ? LIMIT 1", (sha,)).fetchone()
        if other is not None:
            flags = flags + [f"REUSED_FROM_DATASET: {other['dataset_id']}"]
        to_store.append((rec, flags, data))

    if manifest["screenshots"] and not to_store:
        status = "NO_USABLE_SCREENSHOTS"
    elif not manifest["screenshots"]:
        status = "NO_SCREENSHOTS"
    elif rejected or dataset_issues or any(flags for _, flags, _ in to_store):
        status = "IMPORTED_WITH_ISSUES"
    else:
        status = "IMPORTED"

    shots_dir = data_dir / "screenshots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    with conn:
        conn.execute(
            "INSERT INTO datasets(dataset_id, manifest_json, instrument, exchange, contract_type, "
            "analysis_timeframe, imported_at_utc, status, issues_json) VALUES (?,?,?,?,?,?,?,?,?)",
            (dataset_id, canonical_json(manifest), manifest["instrument"], manifest["exchange"],
             manifest["contract_type"], manifest.get("analysis_timeframe"), fmt_utc(import_time), status,
             json.dumps(dataset_issues + [f"REJECTED_SCREENSHOT: {r['file_name']}: {r['issues']}" for r in rejected])),
        )
        for rec, flags, data in to_store:
            stored_name = rec["sha256"] + rec["ext"]
            target = shots_dir / stored_name
            if not target.exists():
                target.write_bytes(data)
            screenshot_id = hashlib.sha256((dataset_id + rec["sha256"]).encode()).hexdigest()[:16]
            conn.execute(
                "INSERT INTO screenshots(screenshot_id, dataset_id, file_name, stored_path, sha256, timeframe, "
                "indicators_json, captured_at_utc, data_last_update_utc, chart_instrument, notes, issues_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (screenshot_id, dataset_id, rec["file_name"], f"screenshots/{stored_name}", rec["sha256"],
                 rec["timeframe"], json.dumps(rec["indicators"]), rec["captured_at_utc"],
                 rec["data_last_update_utc"], rec["chart_instrument"], rec["notes"], json.dumps(flags)),
            )
            accepted.append({"screenshot_id": screenshot_id, "file_name": rec["file_name"],
                             "timeframe": rec["timeframe"], "issues": flags})
    return ImportResult(dataset_id, True, status, dataset_issues, accepted, rejected)
