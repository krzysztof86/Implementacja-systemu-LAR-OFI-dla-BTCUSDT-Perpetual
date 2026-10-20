"""Synthetic fixtures. They exercise rules only; they are NOT market data and
are never evidence of trading performance."""

from __future__ import annotations

import json
import struct
import zlib
from datetime import datetime, timedelta, timezone

import pytest

from lar_ofi.config import load_config
from lar_ofi.db import connect
from lar_ofi.intake import import_dataset
from lar_ofi.observations import add_observations_from_list, build_engine_input

T0 = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def png_bytes(seed: int) -> bytes:
    """A valid 1x1 RGB PNG whose colour depends on `seed` (distinct hashes)."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = b"\x00" + bytes([seed % 256, (seed // 256) % 256, 7])
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


# Standard synthetic screenshot set for one analysis moment (T0).
STANDARD_SHOTS = {
    "ctx_4h.png": {"timeframe": "4H", "indicators": ["Agg. TPO"], "offset_s": -60},
    "auction_30m.png": {"timeframe": "30M",
                        "indicators": ["Agg. TPO", "Agg. Session Volume Profile", "Anchored VWAP"], "offset_s": -30},
    "heat_5m_a.png": {"timeframe": "5M", "indicators": ["Agg. Order Book Heatmap"], "offset_s": -300},
    "heat_5m_b.png": {"timeframe": "5M", "indicators": ["Agg. Order Book Heatmap"], "offset_s": -20},
    "flow_5m.png": {"timeframe": "5M", "indicators": ["Agg. Volume Footprint", "Agg. Open Interest", "Agg. CVD"],
                    "offset_s": -15},
    "conf_1m.png": {"timeframe": "1M", "indicators": ["Agg. Liquidations", "Absorption"], "offset_s": -10},
}

CONTINUATION_LONG_OBS = [
    ("auction_30m.png", "price_vs_prev_value_area", "ABOVE"),
    ("auction_30m.png", "closed_bars_outside_value", 3),
    ("auction_30m.png", "returned_inside_value", "NO"),
    ("auction_30m.png", "violation_side", "UP"),
    ("auction_30m.png", "last_price", 68000.0),
    ("auction_30m.png", "prev_vah", 67500.0),
    ("auction_30m.png", "prev_val", 66800.0),
    ("heat_5m_b.png", "passive_liquidity_above", "THIN"),
    ("heat_5m_b.png", "ask_side_after_consumption", "NOT_REPLENISHED", "heat_5m_a.png"),
    ("flow_5m.png", "footprint_aggression", "BUY_DOMINANT"),
    ("flow_5m.png", "price_response_to_aggression", "ADVANCED"),
    ("flow_5m.png", "oi_change", "RISING"),
    ("flow_5m.png", "cvd_trend", "RISING"),
    ("conf_1m.png", "liquidations", "NONE_SIGNIFICANT"),
]

FAILED_AUCTION_SHORT_OBS = [
    ("auction_30m.png", "price_vs_prev_value_area", "INSIDE"),
    ("auction_30m.png", "closed_bars_outside_value", 0),
    ("auction_30m.png", "returned_inside_value", "YES"),
    ("auction_30m.png", "violation_side", "UP"),
    ("heat_5m_b.png", "passive_liquidity_above", "THICK"),
    ("heat_5m_b.png", "ask_side_after_consumption", "REPLENISHED", "heat_5m_a.png"),
    ("flow_5m.png", "footprint_aggression", "BUY_DOMINANT"),
    ("flow_5m.png", "aggression_at_extreme", "BUY"),
    ("flow_5m.png", "price_response_at_extreme", "REVERSED"),
    ("flow_5m.png", "price_response_to_aggression", "REVERSED"),
    ("flow_5m.png", "oi_change", "FALLING"),
    ("flow_5m.png", "cvd_trend", "RISING"),
    ("conf_1m.png", "liquidations", "LONGS_LIQUIDATED"),
    ("conf_1m.png", "absorption_signal", "ASK_SIDE"),
]


def obs_items(spec, shot_ids: dict[str, str]):
    items = []
    for entry in spec:
        file_name, field, value = entry[:3]
        item = {"screenshot": shot_ids[file_name], "field": field, "value": value}
        if len(entry) > 3:
            item["compared_with"] = shot_ids[entry[3]]
        if isinstance(value, dict):  # explicit item overrides
            item = {"screenshot": shot_ids[file_name], "field": field, **value}
        items.append(item)
    return items


class Env:
    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.data_dir = tmp_path / "data"
        self.conn = connect(tmp_path / "data" / "journal.sqlite")
        self.cfg = load_config()
        self._seed = 0

    def manifest(self, shots: dict | None = None, name: str = "m", t0: datetime = T0, **header):
        shots = STANDARD_SHOTS if shots is None else shots
        d = self.tmp / name
        d.mkdir(exist_ok=True)
        entries = []
        for file_name, s in shots.items():
            if "content" in s:
                (d / file_name).write_bytes(s["content"])
            elif not (d / file_name).exists():
                self._seed += 1
                (d / file_name).write_bytes(png_bytes(self._seed + 1000 * len(name)))
            e = {"file": file_name, "timeframe": s["timeframe"], "indicators": s["indicators"],
                 "chart_instrument": s.get("chart_instrument", "BTCUSDT")}
            if s.get("offset_s") is not None:
                e["captured_at_utc"] = iso(t0 + timedelta(seconds=s["offset_s"]))
            if s.get("last_update_offset_s") is not None:
                e["data_last_update_utc"] = iso(t0 + timedelta(seconds=s["last_update_offset_s"]))
            entries.append(e)
        m = {"manifest_version": 1, "instrument": "BTCUSDT", "exchange": "Bybit",
             "contract_type": "USDT_PERPETUAL", "source_platform": "OpenMarket.xyz",
             "data_source_config": "SYNTHETIC TEST FIXTURE", "analysis_timeframe": "5M",
             "screenshots": entries}
        m.update(header)
        path = d / "manifest.json"
        path.write_text(json.dumps(m, indent=1))
        return path

    def import_(self, path, import_time=None):
        return import_dataset(self.conn, path, self.cfg, self.data_dir,
                              import_time=import_time or T0 + timedelta(minutes=1))

    def shot_ids(self, dataset_id):
        return {r["file_name"]: r["screenshot_id"] for r in
                self.conn.execute("SELECT * FROM screenshots WHERE dataset_id=?", (dataset_id,))}

    def scenario(self, obs_spec, shots=None, name="m", import_time=None, t0=T0):
        res = self.import_(self.manifest(shots, name=name, t0=t0), import_time=import_time)
        ids = self.shot_ids(res.dataset_id)
        inserted, errors = add_observations_from_list(self.conn, res.dataset_id, obs_items(obs_spec, ids))
        assert not errors, errors
        return res.dataset_id

    def engine_input(self, dataset_id, as_of=T0, previous_states=None):
        return build_engine_input(self.conn, dataset_id, as_of=as_of, previous_states=previous_states)


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    yield e
    e.conn.close()
