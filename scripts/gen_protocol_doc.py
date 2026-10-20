"""Render PROTOKOL_OBSERWACJI.md from lar_ofi.registry.PROTOCOL (single source
of truth). Usage: python scripts/gen_protocol_doc.py > PROTOKOL_OBSERWACJI.md"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lar_ofi.registry import FIELDS, PROTOCOL_VERSION  # noqa: E402

INTRO = f"""# PROTOKÓŁ OBSERWACJI — {PROTOCOL_VERSION}

Dokument generowany z `src/lar_ofi/registry.py` (`scripts/gen_protocol_doc.py`); test
`tests/test_faza5.py::test_p1_protocol_document_is_generated_from_registry` pilnuje zgodności.

Zasady ogólne:

1. **Brak wymyślonych progów liczbowych.** Klasyfikacje opierają się na znakach wydrukowanych wartości,
   położeniu zamknięć względem narysowanych poziomów i ekstremów świec albo na porównaniu w obrębie
   jednego obrazu.
2. **Gdy rozróżnienie nie jest pewne — `UNKNOWN`.** Każde pole ma listę sytuacji, w których obowiązkowo
   wpisuje się `UNKNOWN` (lub `readability: UNREADABLE`). Nie wolno „zgadywać” wartości neutralnej
   (np. FLAT, BALANCED) zamiast `UNKNOWN`.
3. **Okno obserwacji** (pola oznaczone „okno: tak”): kolejne ZAMKNIĘTE świece interwału screenshotu,
   kończące się na ostatniej świecy zamkniętej przed wykonaniem screenshotu. Zapisuje się
   `window_start_utc` i `window_end_utc` (granice świec, UTC). Okno kończące się wcześniej → silnik
   traktuje odczyt jako `UNKNOWN` (`WINDOW_NOT_LATEST_CLOSED_BAR`). Długość okna wybiera obserwator i
   jest ona jawnie zapisana — dzięki temu drugi obserwator może powtórzyć odczyt na tym samym obrazie.
4. **Porównanie dwóch heatmap** wymaga identycznych `view_settings` obu screenshotów (skala barw jest
   normalizowana per widok). Jest to **jakościowa ocena zmiany widocznej płynności**, a nie pomiar
   Liquidity Resiliency; ten wymaga strumienia zdarzeń L2 (MODE B, `lar_ofi.l2`).
5. Typy pomiaru: `READ_LABEL` (odczyt wydrukowanej liczby), `VISUAL_POSITION` (położenie względem
   narysowanego poziomu), `SIGN_RULE` (znaki wydrukowanych wartości), `BAR_EXTREME_RULE` (zamknięcie
   względem ekstremów świec), `AXIS_COMPARISON` (wartość na końcu vs początku okna),
   `QUALITATIVE_VISUAL` (jasność/wyróżnienie na obrazie — najmniej powtarzalne),
   `DERIVED_INDICATOR` (wyjście algorytmu zewnętrznego o nieznanej metodzie).

## Pola wymagające rzeczywistych danych ilościowych

Na screenshotach poniższe pola są wyłącznie **jakościowymi przybliżeniami**; wiarygodny pomiar wymaga
wskazanych danych:

| Pole | Typ pomiaru | Potrzebne dane ilościowe |
|---|---|---|
"""


def render() -> str:
    lines = [INTRO.rstrip("\n")]
    for name, spec in FIELDS.items():
        q = spec.protocol.get("quantitative_data")
        if spec.enabled and q:
            lines.append(f"| `{name}` | {spec.protocol['measurement']} | {q} |")
    lines += ["", "## Procedury dla poszczególnych pól", ""]
    for name, spec in FIELDS.items():
        if not spec.enabled:
            continue
        p = spec.protocol
        allowed = ", ".join(spec.allowed) if spec.kind == "enum" else spec.kind
        lines += [
            f"### `{name}`",
            "",
            f"* Warstwa {spec.layer}; interwały {', '.join(spec.timeframes)}; wartości: {allowed}, UNKNOWN",
            f"* Typ pomiaru: `{p['measurement']}`; okno: {'tak' if p.get('window') else 'nie'}"
            + ("; wymaga dwóch screenshotów (`compared_with`)" if spec.requires_comparison else ""),
            f"* Procedura: {p['procedure']}",
            f"* Wpisz `UNKNOWN`, gdy: {p['unknown_when']}",
        ]
        if p.get("quantitative_data"):
            lines.append(f"* Wiarygodny pomiar wymaga: {p['quantitative_data']}")
        lines.append("")
    lines += ["Pola warstw D/E są zarejestrowane, lecz wyłączone; nie mają procedury, bo silnik ich nie używa.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    sys.stdout.write(render())
