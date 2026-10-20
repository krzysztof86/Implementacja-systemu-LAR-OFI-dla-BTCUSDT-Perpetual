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
# Qualitative comparison of two heatmap screenshots. This is NOT the
# Liquidity Resiliency of the L2 literature (see lar_ofi.l2).
GROUP_VISUAL_LIQUIDITY_CHANGE = "VISUAL_LIQUIDITY_CHANGE"
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

    @property
    def protocol(self) -> dict:
        return PROTOCOL.get(self.name, {})

    @property
    def requires_window(self) -> bool:
        return self.protocol.get("window", False)


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
                  GROUP_VISUAL_LIQUIDITY_CHANGE,
                  "Comparing an EARLIER heatmap screenshot (compared_with) with this one: after ask "
                  "liquidity was consumed by buying, did visible ask liquidity rebuild?",
                  allowed=_RESIL, requires_comparison=True),
        FieldSpec("bid_side_after_consumption", "B", "enum", ("5M", "1M"), ("Agg. Order Book Heatmap",),
                  GROUP_VISUAL_LIQUIDITY_CHANGE,
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


# --------------------------------------------------------------------------
# Observation protocol (OBS-PROTOCOL-2, phase 5)
# --------------------------------------------------------------------------
# Every categorical reading follows a written procedure with NO invented
# numeric thresholds. Where the distinction is not reliably visible the
# observer must record UNKNOWN. `window=True` fields additionally require the
# observation window (window_start_utc, window_end_utc): consecutive CLOSED
# bars of the screenshot's timeframe, ending at the last bar closed before the
# capture time. `quantitative_data` names the data a reliable measurement
# would need; such fields are qualitative proxies in screenshot mode.

PROTOCOL_VERSION = "OBS-PROTOCOL-2"

MEASUREMENT_READ_LABEL = "READ_LABEL"              # number/text printed on the chart
MEASUREMENT_VISUAL_POSITION = "VISUAL_POSITION"    # price vs a drawn level
MEASUREMENT_SIGN_RULE = "SIGN_RULE"                # signs of printed values
MEASUREMENT_BAR_EXTREME_RULE = "BAR_EXTREME_RULE"  # closes vs bar highs/lows
MEASUREMENT_AXIS_COMPARISON = "AXIS_COMPARISON"    # start vs end value on an axis
MEASUREMENT_QUALITATIVE = "QUALITATIVE_VISUAL"     # colour intensity / visual salience
MEASUREMENT_DERIVED = "DERIVED_INDICATOR"          # third-party algorithm output

_POSITION_UNKNOWN = "poziom nie jest narysowany/opisany albo cena jest na linii i nie da się rozstrzygnąć strony"

PROTOCOL: dict[str, dict] = {
    "last_price": {"measurement": MEASUREMENT_READ_LABEL, "window": False,
                   "procedure": "Odczytaj etykietę bieżącej ceny na osi cen.",
                   "unknown_when": "etykieta niewidoczna lub ucięta"},
    "prev_vah": {"measurement": MEASUREMENT_READ_LABEL, "window": False,
                 "procedure": "Odczytaj liczbę z etykiety VAH poprzedniej sesji/profilu.",
                 "unknown_when": "brak etykiety liczbowej (nie szacuj z położenia na osi)"},
    "prev_val": {"measurement": MEASUREMENT_READ_LABEL, "window": False,
                 "procedure": "Odczytaj liczbę z etykiety VAL poprzedniej sesji/profilu.",
                 "unknown_when": "brak etykiety liczbowej (nie szacuj z położenia na osi)"},
    "prev_poc": {"measurement": MEASUREMENT_READ_LABEL, "window": False,
                 "procedure": "Odczytaj liczbę z etykiety POC poprzedniej sesji/profilu.",
                 "unknown_when": "brak etykiety liczbowej"},
    "price_vs_prev_value_area": {
        "measurement": MEASUREMENT_VISUAL_POSITION, "window": False,
        "procedure": "ABOVE: etykieta bieżącej ceny wyżej niż linia VAH poprzedniego profilu; BELOW: niżej "
                     "niż VAL; INSIDE: pomiędzy.",
        "unknown_when": _POSITION_UNKNOWN},
    "closed_bars_outside_value": {
        "measurement": MEASUREMENT_VISUAL_POSITION, "window": False,
        "procedure": "Licząc wstecz od ostatniej ZAMKNIĘTEJ świecy 30M: liczba kolejnych świec, których "
                     "zamknięcie (korpus) leży po tej samej stronie poza poprzednim VA co bieżąca cena. "
                     "0, jeśli ostatnia zamknięta świeca zamknęła się w VA.",
        "unknown_when": "zamknięcie którejś z liczonych świec leży na linii VAH/VAL"},
    "returned_inside_value": {
        "measurement": MEASUREMENT_VISUAL_POSITION, "window": False,
        "procedure": "YES: w tej sesji handlowano poza poprzednim VA ORAZ ostatnia zamknięta świeca 30M "
                     "zamknęła się wewnątrz VA. NO w pozostałych przypadkach po wyjściu poza VA.",
        "unknown_when": _POSITION_UNKNOWN},
    "violation_side": {
        "measurement": MEASUREMENT_VISUAL_POSITION, "window": False,
        "procedure": "UP: w bieżącej sesji jakikolwiek knot/świeca powyżej VAH lub poprzedniego maksimum; "
                     "DOWN: poniżej VAL/minimum; NONE: brak. Gdy naruszone obie strony — strona naruszona "
                     "później.",
        "unknown_when": "początek sesji nie jest widoczny na screenshocie"},
    "price_vs_avwap": {"measurement": MEASUREMENT_VISUAL_POSITION, "window": False,
                       "procedure": "Etykieta ceny względem linii AVWAP (punkt zakotwiczenia w notatce).",
                       "unknown_when": _POSITION_UNKNOWN},
    "passive_liquidity_above": {
        "measurement": MEASUREMENT_QUALITATIVE, "window": False,
        "procedure": "W pasie cen widocznym nad bieżącą ceną: THICK, jeśli istnieje wyraźnie jaśniejszy pas "
                     "(poziom) niż tło tego samego screenshotu; THIN, jeśli wszystkie poziomy mają barwę tła; "
                     "NOT_VISIBLE, jeśli brak jakiejkolwiek płynności. Porównanie TYLKO w obrębie jednego "
                     "screenshotu (skala barw jest normalizowana per widok).",
        "unknown_when": "nie da się wskazać pasa jaśniejszego od tła bez wahania; skala barw nasycona",
        "quantitative_data": "rzeczywista głębokość (ilości) na poziomach arkusza z L2"},
    "passive_liquidity_below": {
        "measurement": MEASUREMENT_QUALITATIVE, "window": False,
        "procedure": "Jak passive_liquidity_above, dla pasa pod bieżącą ceną.",
        "unknown_when": "jak wyżej",
        "quantitative_data": "rzeczywista głębokość (ilości) na poziomach arkusza z L2"},
    "ask_side_after_consumption": {
        "measurement": MEASUREMENT_QUALITATIVE, "window": False,
        "procedure": "Porównaj TEN SAM poziom cenowy (ten sam wiersz osi cen) na wcześniejszym (compared_with) "
                     "i późniejszym screenshocie heatmapy o IDENTYCZNYCH ustawieniach widoku (view_settings). "
                     "NO_CONSUMPTION_SEEN: cena nie dotarła do pasa. Po dotarciu ceny i zniknięciu pasa: "
                     "REPLENISHED, jeśli na późniejszym screenshocie pas na tym poziomie jest ponownie co "
                     "najmniej tak jasny jak na wcześniejszym; NOT_REPLENISHED, jeśli poziom pozostaje barwy "
                     "tła do prawej krawędzi. To ocena wizualna, NIE pomiar Liquidity Resiliency.",
        "unknown_when": "różne view_settings, zmiana skali barw, poziom poza widokiem, pas częściowo jasny",
        "quantitative_data": "strumień zdarzeń L2 (dodania/anulowania/transakcje) — MODE B"},
    "bid_side_after_consumption": {
        "measurement": MEASUREMENT_QUALITATIVE, "window": False,
        "procedure": "Jak ask_side_after_consumption, dla pasa bid pod ceną.",
        "unknown_when": "jak wyżej",
        "quantitative_data": "strumień zdarzeń L2 (dodania/anulowania/transakcje) — MODE B"},
    "footprint_aggression": {
        "measurement": MEASUREMENT_SIGN_RULE, "window": True,
        "procedure": "W oknie obserwacji odczytaj znak delty KAŻDEJ zamkniętej świecy footprint. "
                     "BUY_DOMINANT: wszystkie dodatnie; SELL_DOMINANT: wszystkie ujemne; BALANCED: znaki "
                     "mieszane lub zerowe. Wielkość delty nie jest oceniana.",
        "unknown_when": "znak delty którejkolwiek świecy w oknie nieczytelny",
        "quantitative_data": "transakcje z flagą agresora (wielkość przewagi)"},
    "price_response_to_aggression": {
        "measurement": MEASUREMENT_BAR_EXTREME_RULE, "window": True,
        "procedure": "Okno = świece agresji + co najmniej jedna późniejsza zamknięta świeca. Zakres agresji = "
                     "od najniższego minimum do najwyższego maksimum świec agresji. Dla ostatniej zamkniętej "
                     "świecy: ADVANCED, jeśli zamknięcie leży poza zakresem w kierunku agresora; REVERSED, "
                     "jeśli poza zakresem po przeciwnej stronie; STALLED, jeśli wewnątrz zakresu.",
        "unknown_when": "brak zamkniętej świecy po świecach agresji; zamknięcie na krawędzi zakresu"},
    "aggression_at_extreme": {
        "measurement": MEASUREMENT_SIGN_RULE, "window": True,
        "procedure": "Komórki footprint na poziomie ekstremum (maksimum dla naruszenia UP, minimum dla DOWN): "
                     "BUY, jeśli wolumen ask (kupno agresywne) jest wydrukowany jako większy od bid; SELL "
                     "odwrotnie; NONE, jeśli komórki nie pokazują przewagi.",
        "unknown_when": "liczby w komórkach ekstremum nieczytelne",
        "quantitative_data": "transakcje z flagą agresora na poziomie ceny"},
    "price_response_at_extreme": {
        "measurement": MEASUREMENT_BAR_EXTREME_RULE, "window": True,
        "procedure": "Jak price_response_to_aggression, gdzie świece agresji = świece tworzące ekstremum.",
        "unknown_when": "brak zamkniętej świecy po świecach ekstremum"},
    "oi_change": {
        "measurement": MEASUREMENT_AXIS_COMPARISON, "window": True,
        "procedure": "Porównaj wartość OI na końcu okna z wartością na początku okna. FLAT tylko gdy etykiety "
                     "osi/tooltip pokazują tę samą wartość.",
        "unknown_when": "różnicy nie da się rozstrzygnąć na osi (nie zgaduj FLAT)",
        "quantitative_data": "szereg czasowy OI (wielkość zmiany)"},
    "cvd_trend": {
        "measurement": MEASUREMENT_AXIS_COMPARISON, "window": True,
        "procedure": "Porównaj wartość CVD na końcu i na początku okna; FLAT tylko przy tej samej wartości.",
        "unknown_when": "różnicy nie da się rozstrzygnąć na osi (nie zgaduj FLAT)",
        "quantitative_data": "transakcje z flagą agresora"},
    "liquidations": {
        "measurement": MEASUREMENT_QUALITATIVE, "window": True,
        "procedure": "LONGS/SHORTS_LIQUIDATED: w oknie widać słupek likwidacji wyraźnie wyższy niż wszystkie "
                     "inne słupki widoczne na tym samym screenshocie; BOTH: po obu stronach; "
                     "NONE_SIGNIFICANT: brak takiego słupka.",
        "unknown_when": "skala słupków nie pozwala odróżnić wyróżniającego się słupka",
        "quantitative_data": "szereg wolumenu likwidacji (rozkład historyczny)"},
    "absorption_signal": {"measurement": MEASUREMENT_DERIVED, "window": True,
                          "procedure": "Przepisz sygnał wskaźnika Absorption z okna (algorytm nieznany).",
                          "unknown_when": "brak legendy znaczenia sygnału"},
}
