"""Registry of OpenMarket indicators and of the observation vocabulary.

Every observation a user (or a configured vision backend) can record must be
one of the FIELDS below, read from a screenshot that shows an indicator able
to supply it, at a timeframe the field is defined for. Anything else is
rejected at entry time.

Deliberately absent: "ofi", "queue_imbalance", "resiliency" as screenshot
fields. Those quantities require event-level L2 data (see lar_ofi.l2) and
must never be typed in from a picture.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lar_ofi.enums import UNKNOWN

TIMEFRAMES = ("4H", "30M", "5M", "1M")

# Source groups: observations that measure the SAME underlying information.
# Concordant readings inside one group count as ONE piece of evidence.
GROUP_TRADE_AGGRESSION = "TRADE_AGGRESSION"   # footprint delta + CVD = same trade prints
GROUP_AUCTION = "AUCTION_STRUCTURE"
GROUP_VISIBLE_LIQUIDITY = "VISIBLE_LIQUIDITY"
GROUP_RESILIENCY = "LIQUIDITY_RESILIENCY"
GROUP_POSITIONING = "POSITIONING_OI"
GROUP_LIQUIDATIONS = "LIQUIDATIONS"
GROUP_ABSORPTION = "ABSORPTION_DERIVED"
GROUP_PRICE = "PRICE"


@dataclass(frozen=True)
class IndicatorSpec:
    name: str
    layer: str
    timeframes: tuple[str, ...]
    derived: bool = False
    enabled: bool = True
    note: str = ""


@dataclass(frozen=True)
class FieldSpec:
    name: str
    layer: str
    kind: str  # "enum" | "number" | "int"
    timeframes: tuple[str, ...]
    indicators: tuple[str, ...]
    group: str
    description: str
    allowed: tuple[str, ...] = field(default_factory=tuple)
    requires_comparison: bool = False
    enabled: bool = True


AUCTION_INDICATORS = ("Agg. TPO", "Agg. Session Volume Profile")

INDICATORS: dict[str, IndicatorSpec] = {
    s.name: s
    for s in (
        IndicatorSpec("Agg. TPO", "A", ("4H", "30M")),
        IndicatorSpec("Agg. Session Volume Profile", "A", ("4H", "30M")),
        IndicatorSpec("Anchored VWAP", "A", ("4H", "30M")),
        IndicatorSpec("Agg. Order Book Heatmap", "B", ("5M", "1M"),
                      note="Visible resting liquidity only; no queue/cancel event detail."),
        IndicatorSpec("Agg. Volume Footprint", "B", ("5M", "1M")),
        IndicatorSpec("Agg. Open Interest", "B", ("5M", "1M")),
        IndicatorSpec("Agg. CVD", "C", ("5M", "1M"),
                      note="Same trade prints as the footprint; not independent evidence."),
        IndicatorSpec("Agg. Liquidations", "C", ("5M", "1M")),
        IndicatorSpec("Absorption", "C", ("5M", "1M"), derived=True,
                      note="Derived indicator with unverified algorithm; auxiliary only."),
        # Layer D/E: registered so screenshots are accepted, but disabled in the engine
        # until data availability and comparability are confirmed.
        IndicatorSpec("Spot CVD", "D", ("5M", "1M"), enabled=False),
        IndicatorSpec("Perpetual CVD", "D", ("5M", "1M"), enabled=False),
        IndicatorSpec("Coinbase Premium", "D", ("5M", "1M", "30M"), enabled=False),
        IndicatorSpec("ATR", "E", TIMEFRAMES, enabled=False),
        IndicatorSpec("ADX", "E", TIMEFRAMES, enabled=False),
        IndicatorSpec("GEX", "E", ("30M", "4H"), enabled=False,
                      note="Never a condition for opening a position in this version."),
    )
}

ALL_INDICATORS = tuple(INDICATORS)

_LIQ = ("THIN", "THICK", "NOT_VISIBLE")
_RESIL = ("REPLENISHED", "NOT_REPLENISHED", "NO_CONSUMPTION_SEEN")
_RESP = ("ADVANCED", "STALLED", "REVERSED")

FIELDS: dict[str, FieldSpec] = {
    f.name: f
    for f in (
        # ---- price (any screenshot) -----------------------------------
        FieldSpec("last_price", "A", "number", TIMEFRAMES, ALL_INDICATORS, GROUP_PRICE,
                  "Last traded price printed on the chart's price scale."),
        # ---- Layer A: auction context (30M decision, 4H context) -------
        FieldSpec("prev_vah", "A", "number", ("4H", "30M"), AUCTION_INDICATORS, GROUP_AUCTION,
                  "Previous session/profile Value Area High, if printed or readable."),
        FieldSpec("prev_val", "A", "number", ("4H", "30M"), AUCTION_INDICATORS, GROUP_AUCTION,
                  "Previous session/profile Value Area Low, if printed or readable."),
        FieldSpec("prev_poc", "A", "number", ("4H", "30M"), AUCTION_INDICATORS, GROUP_AUCTION,
                  "Previous session/profile Point of Control, if printed or readable."),
        FieldSpec("price_vs_prev_value_area", "A", "enum", ("4H", "30M"), AUCTION_INDICATORS,
                  GROUP_AUCTION, "Current price relative to the previous value area.",
                  allowed=("ABOVE", "INSIDE", "BELOW")),
        FieldSpec("closed_bars_outside_value", "A", "int", ("30M",), AUCTION_INDICATORS,
                  GROUP_AUCTION,
                  "Number of consecutive CLOSED bars of this timeframe whose close is outside "
                  "the previous value area on the current side (0 if inside)."),
        FieldSpec("returned_inside_value", "A", "enum", ("30M",), AUCTION_INDICATORS, GROUP_AUCTION,
                  "After trading outside the previous value area in this session, has at least "
                  "one bar of this timeframe CLOSED back inside it?", allowed=("YES", "NO")),
        FieldSpec("violation_side", "A", "enum", ("30M",), AUCTION_INDICATORS, GROUP_AUCTION,
                  "Did price trade beyond the previous VAH (UP) / VAL (DOWN) or the prior "
                  "session extreme in the current session?", allowed=("UP", "DOWN", "NONE")),
        FieldSpec("price_vs_avwap", "A", "enum", ("4H", "30M"), ("Anchored VWAP",), GROUP_AUCTION,
                  "Price relative to the anchored VWAP (anchor must be stated in screenshot notes).",
                  allowed=("ABOVE", "AT", "BELOW")),
        # ---- Layer B: microstructure (5M / 1M) ---------------------------
        FieldSpec("passive_liquidity_above", "B", "enum", ("5M", "1M"), ("Agg. Order Book Heatmap",),
                  GROUP_VISIBLE_LIQUIDITY,
                  "Visible resting ask-side liquidity just above price (relative heatmap intensity).",
                  allowed=_LIQ),
        FieldSpec("passive_liquidity_below", "B", "enum", ("5M", "1M"), ("Agg. Order Book Heatmap",),
                  GROUP_VISIBLE_LIQUIDITY,
                  "Visible resting bid-side liquidity just below price (relative heatmap intensity).",
                  allowed=_LIQ),
        FieldSpec("ask_side_after_consumption", "B", "enum", ("5M", "1M"), ("Agg. Order Book Heatmap",),
                  GROUP_RESILIENCY,
                  "Comparing an EARLIER heatmap screenshot (compared_with) with this one: after ask "
                  "liquidity was consumed by buying, did visible ask liquidity rebuild?",
                  allowed=_RESIL, requires_comparison=True),
        FieldSpec("bid_side_after_consumption", "B", "enum", ("5M", "1M"), ("Agg. Order Book Heatmap",),
                  GROUP_RESILIENCY,
                  "Comparing an EARLIER heatmap screenshot (compared_with) with this one: after bid "
                  "liquidity was consumed by selling, did visible bid liquidity rebuild?",
                  allowed=_RESIL, requires_comparison=True),
        FieldSpec("footprint_aggression", "B", "enum", ("5M", "1M"), ("Agg. Volume Footprint",),
                  GROUP_TRADE_AGGRESSION,
                  "Dominant aggressor over the most recent bars (footprint delta).",
                  allowed=("BUY_DOMINANT", "SELL_DOMINANT", "BALANCED")),
        FieldSpec("price_response_to_aggression", "B", "enum", ("5M", "1M"), ("Agg. Volume Footprint",),
                  GROUP_PRICE,
                  "Over the same bars: did price ADVANCE in the direction of the dominant aggressor, "
                  "STALL, or REVERSE against it?", allowed=_RESP),
        FieldSpec("aggression_at_extreme", "B", "enum", ("5M", "1M"), ("Agg. Volume Footprint",),
                  GROUP_TRADE_AGGRESSION,
                  "Dominant aggressor in the footprint cells at the session/breakout extreme.",
                  allowed=("BUY", "SELL", "NONE")),
        FieldSpec("price_response_at_extreme", "B", "enum", ("5M", "1M"), ("Agg. Volume Footprint",),
                  GROUP_PRICE,
                  "After the aggression at the extreme: did price ADVANCE further, STALL or REVERSE?",
                  allowed=_RESP),
        FieldSpec("oi_change", "B", "enum", ("5M", "1M"), ("Agg. Open Interest",), GROUP_POSITIONING,
                  "Direction of aggregated open interest over the same recent window.",
                  allowed=("RISING", "FALLING", "FLAT")),
        # ---- Layer C: confirmation ---------------------------------------
        FieldSpec("cvd_trend", "C", "enum", ("5M", "1M"), ("Agg. CVD",), GROUP_TRADE_AGGRESSION,
                  "Direction of aggregated CVD over the same recent window.",
                  allowed=("RISING", "FALLING", "FLAT")),
        FieldSpec("liquidations", "C", "enum", ("5M", "1M"), ("Agg. Liquidations",), GROUP_LIQUIDATIONS,
                  "Recorded liquidation prints that stand out in the recent window.",
                  allowed=("LONGS_LIQUIDATED", "SHORTS_LIQUIDATED", "BOTH", "NONE_SIGNIFICANT")),
        FieldSpec("absorption_signal", "C", "enum", ("5M", "1M"), ("Absorption",), GROUP_ABSORPTION,
                  "Output of the derived 'Absorption' indicator (algorithm unverified).",
                  allowed=("BID_SIDE", "ASK_SIDE", "NONE")),
        # ---- Layer D/E: disabled until data availability is confirmed -----
        FieldSpec("spot_cvd_trend", "D", "enum", ("5M", "1M"), ("Spot CVD",), "SPOT_FLOW",
                  "Spot CVD direction (layer D, disabled).", allowed=("RISING", "FALLING", "FLAT"),
                  enabled=False),
        FieldSpec("perp_cvd_trend", "D", "enum", ("5M", "1M"), ("Perpetual CVD",), "PERP_FLOW",
                  "Perpetual CVD direction (layer D, disabled).", allowed=("RISING", "FALLING", "FLAT"),
                  enabled=False),
        FieldSpec("coinbase_premium", "D", "enum", ("5M", "1M", "30M"), ("Coinbase Premium",),
                  "SPOT_PREMIUM", "Coinbase premium sign (layer D, disabled).",
                  allowed=("POSITIVE", "NEGATIVE", "FLAT"), enabled=False),
        FieldSpec("volatility_regime", "E", "enum", TIMEFRAMES, ("ATR", "ADX"), "REGIME",
                  "Volatility/trend regime label (layer E, disabled).",
                  allowed=("HIGH", "NORMAL", "LOW"), enabled=False),
        FieldSpec("gex_sign", "E", "enum", ("30M", "4H"), ("GEX",), "OPTIONS",
                  "Dealer gamma sign (layer E, disabled; never a position condition).",
                  allowed=("POSITIVE", "NEGATIVE"), enabled=False),
    )
}

# Names that look like L2 metrics; refused as screenshot observations.
FORBIDDEN_SCREENSHOT_FIELDS = frozenset(
    {"ofi", "true_ofi", "order_flow_imbalance", "queue_imbalance", "price_impact",
     "liquidity_replenishment", "resiliency", "liquidity_resiliency"}
)


class RegistryError(ValueError):
    pass


def check_value(spec: FieldSpec, value):
    """Validate and normalise an observation value. Returns the stored value."""
    if value is None:
        raise RegistryError(f"{spec.name}: value is required (use UNKNOWN if unreadable)")
    if isinstance(value, str) and value.upper() == UNKNOWN:
        return UNKNOWN
    if spec.kind == "enum":
        if not isinstance(value, str) or value.upper() not in spec.allowed:
            raise RegistryError(f"{spec.name}: {value!r} not in {spec.allowed + (UNKNOWN,)}")
        return value.upper()
    if spec.kind == "int":
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RegistryError(f"{spec.name}: expected a non-negative integer, got {value!r}")
        return value
    if spec.kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise RegistryError(f"{spec.name}: expected a positive number, got {value!r}")
        return float(value)
    raise RegistryError(f"unknown field kind {spec.kind}")  # pragma: no cover


def field_spec(name: str) -> FieldSpec:
    if name.lower() in FORBIDDEN_SCREENSHOT_FIELDS:
        raise RegistryError(
            f"{name!r} is an event-level L2 quantity and cannot be recorded from a screenshot "
            "(see lar_ofi.l2; MODE B is disabled until real L2 data exists)")
    try:
        return FIELDS[name]
    except KeyError:
        raise RegistryError(f"unknown observation field {name!r}") from None
