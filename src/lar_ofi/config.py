"""Configuration loading. Defaults ship inside the package; a user TOML file
is deep-merged on top. The canonical hash of the effective configuration is
stored with every prediction so that threshold changes are auditable."""

from __future__ import annotations

import copy
import hashlib
import json
import tomllib
from importlib import resources
from pathlib import Path
from typing import Any

COST_KEYS_TAKER = ("taker_fee_bps", "spread_bps", "slippage_bps")


class ConfigError(ValueError):
    pass


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def default_config() -> dict[str, Any]:
    text = resources.files("lar_ofi").joinpath("default_config.toml").read_text("utf-8")
    return tomllib.loads(text)


def load_config(path: str | Path | None = None, overrides: dict | None = None) -> dict[str, Any]:
    cfg = default_config()
    if path is not None:
        with open(path, "rb") as fh:
            cfg = _deep_merge(cfg, tomllib.load(fh))
    if overrides:
        cfg = _deep_merge(cfg, overrides)
    validate_config(cfg)
    return cfg


def validate_config(cfg: dict) -> None:
    if cfg["thresholds"].get("calibrated") not in (False, True):
        raise ConfigError("thresholds.calibrated must be a boolean")
    if cfg["thresholds"]["acceptance_min_closed_bars_30m"] < 1:
        raise ConfigError("acceptance_min_closed_bars_30m must be >= 1")
    tfs = cfg["timeframes"]
    if tfs["micro_decision"] not in tfs["micro"]:
        raise ConfigError("timeframes.micro_decision must be one of timeframes.micro")
    if not set(cfg["freshness"]["require_latest_closed_bar"]) <= {"1M", "5M", "30M", "4H"}:
        raise ConfigError("freshness.require_latest_closed_bar accepts 1M, 5M, 30M, 4H")
    if not 0 < cfg["evaluation"]["alpha"] < 1:
        raise ConfigError("evaluation.alpha must be in (0, 1)")
    if cfg["freshness"]["stale_policy"] not in ("block", "exclude"):
        raise ConfigError("freshness.stale_policy must be 'block' or 'exclude'")
    for h in cfg["prediction"]["horizons_minutes"]:
        if not isinstance(h, int) or h <= 0:
            raise ConfigError("prediction.horizons_minutes must be positive integers")
    costs = cfg.get("costs", {})
    for key in ("taker_fee_bps", "maker_fee_bps", "spread_bps", "slippage_bps", "funding_cost_bps_if_crossed"):
        if key in costs and (not isinstance(costs[key], (int, float)) or costs[key] < 0):
            raise ConfigError(f"costs.{key} must be a non-negative number")
    for key in ("entry_type", "exit_type"):
        if costs.get(key, "TAKER") not in ("TAKER", "MAKER"):
            raise ConfigError(f"costs.{key} must be TAKER or MAKER")
    band = cfg["evaluation"].get("neutral_band_bps")
    if band is not None and (not isinstance(band, (int, float)) or band < 0):
        raise ConfigError("evaluation.neutral_band_bps must be a non-negative number")


def config_hash(cfg: dict) -> str:
    return hashlib.sha256(canonical_json(cfg).encode("utf-8")).hexdigest()


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def cost_model(cfg: dict) -> dict | None:
    """Return the explicit round-trip cost model, or None if the user has not
    supplied every parameter it needs. Never falls back to assumed fees."""
    costs = cfg.get("costs", {})
    fee_keys = {"TAKER": "taker_fee_bps", "MAKER": "maker_fee_bps"}
    entry_fee_key = fee_keys[costs.get("entry_type", "TAKER")]
    exit_fee_key = fee_keys[costs.get("exit_type", "TAKER")]
    needed = {entry_fee_key, exit_fee_key, "spread_bps", "slippage_bps"}
    if any(k not in costs for k in needed):
        return None
    # Spread: a taker crosses half the spread on entry and half on exit.
    # Slippage is charged per taker leg. Maker legs pay neither (fill risk is
    # NOT modelled; this is stated in every evaluation report).
    taker_legs = [costs.get("entry_type", "TAKER"), costs.get("exit_type", "TAKER")].count("TAKER")
    round_trip = (
        costs[entry_fee_key]
        + costs[exit_fee_key]
        + costs["spread_bps"] * taker_legs / 2.0
        + costs["slippage_bps"] * taker_legs
    )
    funding = None
    if "funding_cost_bps_if_crossed" in costs and "funding_times_utc" in costs:
        funding = {
            "cost_bps_if_crossed": costs["funding_cost_bps_if_crossed"],
            "times_utc": list(costs["funding_times_utc"]),
        }
    return {
        "entry_type": costs.get("entry_type", "TAKER"),
        "exit_type": costs.get("exit_type", "TAKER"),
        "entry_fee_bps": costs[entry_fee_key],
        "exit_fee_bps": costs[exit_fee_key],
        "spread_bps": costs["spread_bps"],
        "slippage_bps": costs["slippage_bps"],
        "round_trip_bps": round_trip,
        "funding": funding,
        "maker_fill_risk_modelled": False,
    }
