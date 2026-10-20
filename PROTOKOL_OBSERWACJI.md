# PROTOKÓŁ OBSERWACJI — OBS-PROTOCOL-2

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
| `passive_liquidity_above` | QUALITATIVE_VISUAL | rzeczywista głębokość (ilości) na poziomach arkusza z L2 |
| `passive_liquidity_below` | QUALITATIVE_VISUAL | rzeczywista głębokość (ilości) na poziomach arkusza z L2 |
| `ask_side_after_consumption` | QUALITATIVE_VISUAL | strumień zdarzeń L2 (dodania/anulowania/transakcje) — MODE B |
| `bid_side_after_consumption` | QUALITATIVE_VISUAL | strumień zdarzeń L2 (dodania/anulowania/transakcje) — MODE B |
| `footprint_aggression` | SIGN_RULE | transakcje z flagą agresora (wielkość przewagi) |
| `aggression_at_extreme` | SIGN_RULE | transakcje z flagą agresora na poziomie ceny |
| `oi_change` | AXIS_COMPARISON | szereg czasowy OI (wielkość zmiany) |
| `cvd_trend` | AXIS_COMPARISON | transakcje z flagą agresora |
| `liquidations` | QUALITATIVE_VISUAL | szereg wolumenu likwidacji (rozkład historyczny) |

## Procedury dla poszczególnych pól

### `last_price`

* Warstwa A; interwały 4H, 30M, 5M, 1M; wartości: number, UNKNOWN
* Typ pomiaru: `READ_LABEL`; okno: nie
* Procedura: Odczytaj etykietę bieżącej ceny na osi cen.
* Wpisz `UNKNOWN`, gdy: etykieta niewidoczna lub ucięta

### `prev_vah`

* Warstwa A; interwały 4H, 30M; wartości: number, UNKNOWN
* Typ pomiaru: `READ_LABEL`; okno: nie
* Procedura: Odczytaj liczbę z etykiety VAH poprzedniej sesji/profilu.
* Wpisz `UNKNOWN`, gdy: brak etykiety liczbowej (nie szacuj z położenia na osi)

### `prev_val`

* Warstwa A; interwały 4H, 30M; wartości: number, UNKNOWN
* Typ pomiaru: `READ_LABEL`; okno: nie
* Procedura: Odczytaj liczbę z etykiety VAL poprzedniej sesji/profilu.
* Wpisz `UNKNOWN`, gdy: brak etykiety liczbowej (nie szacuj z położenia na osi)

### `prev_poc`

* Warstwa A; interwały 4H, 30M; wartości: number, UNKNOWN
* Typ pomiaru: `READ_LABEL`; okno: nie
* Procedura: Odczytaj liczbę z etykiety POC poprzedniej sesji/profilu.
* Wpisz `UNKNOWN`, gdy: brak etykiety liczbowej

### `price_vs_prev_value_area`

* Warstwa A; interwały 4H, 30M; wartości: ABOVE, INSIDE, BELOW, UNKNOWN
* Typ pomiaru: `VISUAL_POSITION`; okno: nie
* Procedura: ABOVE: etykieta bieżącej ceny wyżej niż linia VAH poprzedniego profilu; BELOW: niżej niż VAL; INSIDE: pomiędzy.
* Wpisz `UNKNOWN`, gdy: poziom nie jest narysowany/opisany albo cena jest na linii i nie da się rozstrzygnąć strony

### `closed_bars_outside_value`

* Warstwa A; interwały 30M; wartości: int, UNKNOWN
* Typ pomiaru: `VISUAL_POSITION`; okno: nie
* Procedura: Licząc wstecz od ostatniej ZAMKNIĘTEJ świecy 30M: liczba kolejnych świec, których zamknięcie (korpus) leży po tej samej stronie poza poprzednim VA co bieżąca cena. 0, jeśli ostatnia zamknięta świeca zamknęła się w VA.
* Wpisz `UNKNOWN`, gdy: zamknięcie którejś z liczonych świec leży na linii VAH/VAL

### `returned_inside_value`

* Warstwa A; interwały 30M; wartości: YES, NO, UNKNOWN
* Typ pomiaru: `VISUAL_POSITION`; okno: nie
* Procedura: YES: w tej sesji handlowano poza poprzednim VA ORAZ ostatnia zamknięta świeca 30M zamknęła się wewnątrz VA. NO w pozostałych przypadkach po wyjściu poza VA.
* Wpisz `UNKNOWN`, gdy: poziom nie jest narysowany/opisany albo cena jest na linii i nie da się rozstrzygnąć strony

### `violation_side`

* Warstwa A; interwały 30M; wartości: UP, DOWN, NONE, UNKNOWN
* Typ pomiaru: `VISUAL_POSITION`; okno: nie
* Procedura: UP: w bieżącej sesji jakikolwiek knot/świeca powyżej VAH lub poprzedniego maksimum; DOWN: poniżej VAL/minimum; NONE: brak. Gdy naruszone obie strony — strona naruszona później.
* Wpisz `UNKNOWN`, gdy: początek sesji nie jest widoczny na screenshocie

### `price_vs_avwap`

* Warstwa A; interwały 4H, 30M; wartości: ABOVE, AT, BELOW, UNKNOWN
* Typ pomiaru: `VISUAL_POSITION`; okno: nie
* Procedura: Etykieta ceny względem linii AVWAP (punkt zakotwiczenia w notatce).
* Wpisz `UNKNOWN`, gdy: poziom nie jest narysowany/opisany albo cena jest na linii i nie da się rozstrzygnąć strony

### `passive_liquidity_above`

* Warstwa B; interwały 5M, 1M; wartości: THIN, THICK, NOT_VISIBLE, UNKNOWN
* Typ pomiaru: `QUALITATIVE_VISUAL`; okno: nie
* Procedura: W pasie cen widocznym nad bieżącą ceną: THICK, jeśli istnieje wyraźnie jaśniejszy pas (poziom) niż tło tego samego screenshotu; THIN, jeśli wszystkie poziomy mają barwę tła; NOT_VISIBLE, jeśli brak jakiejkolwiek płynności. Porównanie TYLKO w obrębie jednego screenshotu (skala barw jest normalizowana per widok).
* Wpisz `UNKNOWN`, gdy: nie da się wskazać pasa jaśniejszego od tła bez wahania; skala barw nasycona
* Wiarygodny pomiar wymaga: rzeczywista głębokość (ilości) na poziomach arkusza z L2

### `passive_liquidity_below`

* Warstwa B; interwały 5M, 1M; wartości: THIN, THICK, NOT_VISIBLE, UNKNOWN
* Typ pomiaru: `QUALITATIVE_VISUAL`; okno: nie
* Procedura: Jak passive_liquidity_above, dla pasa pod bieżącą ceną.
* Wpisz `UNKNOWN`, gdy: jak wyżej
* Wiarygodny pomiar wymaga: rzeczywista głębokość (ilości) na poziomach arkusza z L2

### `ask_side_after_consumption`

* Warstwa B; interwały 5M, 1M; wartości: REPLENISHED, NOT_REPLENISHED, NO_CONSUMPTION_SEEN, UNKNOWN
* Typ pomiaru: `QUALITATIVE_VISUAL`; okno: nie; wymaga dwóch screenshotów (`compared_with`)
* Procedura: Porównaj TEN SAM poziom cenowy (ten sam wiersz osi cen) na wcześniejszym (compared_with) i późniejszym screenshocie heatmapy o IDENTYCZNYCH ustawieniach widoku (view_settings). NO_CONSUMPTION_SEEN: cena nie dotarła do pasa. Po dotarciu ceny i zniknięciu pasa: REPLENISHED, jeśli na późniejszym screenshocie pas na tym poziomie jest ponownie co najmniej tak jasny jak na wcześniejszym; NOT_REPLENISHED, jeśli poziom pozostaje barwy tła do prawej krawędzi. To ocena wizualna, NIE pomiar Liquidity Resiliency.
* Wpisz `UNKNOWN`, gdy: różne view_settings, zmiana skali barw, poziom poza widokiem, pas częściowo jasny
* Wiarygodny pomiar wymaga: strumień zdarzeń L2 (dodania/anulowania/transakcje) — MODE B

### `bid_side_after_consumption`

* Warstwa B; interwały 5M, 1M; wartości: REPLENISHED, NOT_REPLENISHED, NO_CONSUMPTION_SEEN, UNKNOWN
* Typ pomiaru: `QUALITATIVE_VISUAL`; okno: nie; wymaga dwóch screenshotów (`compared_with`)
* Procedura: Jak ask_side_after_consumption, dla pasa bid pod ceną.
* Wpisz `UNKNOWN`, gdy: jak wyżej
* Wiarygodny pomiar wymaga: strumień zdarzeń L2 (dodania/anulowania/transakcje) — MODE B

### `footprint_aggression`

* Warstwa B; interwały 5M, 1M; wartości: BUY_DOMINANT, SELL_DOMINANT, BALANCED, UNKNOWN
* Typ pomiaru: `SIGN_RULE`; okno: tak
* Procedura: W oknie obserwacji odczytaj znak delty KAŻDEJ zamkniętej świecy footprint. BUY_DOMINANT: wszystkie dodatnie; SELL_DOMINANT: wszystkie ujemne; BALANCED: znaki mieszane lub zerowe. Wielkość delty nie jest oceniana.
* Wpisz `UNKNOWN`, gdy: znak delty którejkolwiek świecy w oknie nieczytelny
* Wiarygodny pomiar wymaga: transakcje z flagą agresora (wielkość przewagi)

### `price_response_to_aggression`

* Warstwa B; interwały 5M, 1M; wartości: ADVANCED, STALLED, REVERSED, UNKNOWN
* Typ pomiaru: `BAR_EXTREME_RULE`; okno: tak
* Procedura: Okno = świece agresji + co najmniej jedna późniejsza zamknięta świeca. Zakres agresji = od najniższego minimum do najwyższego maksimum świec agresji. Dla ostatniej zamkniętej świecy: ADVANCED, jeśli zamknięcie leży poza zakresem w kierunku agresora; REVERSED, jeśli poza zakresem po przeciwnej stronie; STALLED, jeśli wewnątrz zakresu.
* Wpisz `UNKNOWN`, gdy: brak zamkniętej świecy po świecach agresji; zamknięcie na krawędzi zakresu

### `aggression_at_extreme`

* Warstwa B; interwały 5M, 1M; wartości: BUY, SELL, NONE, UNKNOWN
* Typ pomiaru: `SIGN_RULE`; okno: tak
* Procedura: Komórki footprint na poziomie ekstremum (maksimum dla naruszenia UP, minimum dla DOWN): BUY, jeśli wolumen ask (kupno agresywne) jest wydrukowany jako większy od bid; SELL odwrotnie; NONE, jeśli komórki nie pokazują przewagi.
* Wpisz `UNKNOWN`, gdy: liczby w komórkach ekstremum nieczytelne
* Wiarygodny pomiar wymaga: transakcje z flagą agresora na poziomie ceny

### `price_response_at_extreme`

* Warstwa B; interwały 5M, 1M; wartości: ADVANCED, STALLED, REVERSED, UNKNOWN
* Typ pomiaru: `BAR_EXTREME_RULE`; okno: tak
* Procedura: Jak price_response_to_aggression, gdzie świece agresji = świece tworzące ekstremum.
* Wpisz `UNKNOWN`, gdy: brak zamkniętej świecy po świecach ekstremum

### `oi_change`

* Warstwa B; interwały 5M, 1M; wartości: RISING, FALLING, FLAT, UNKNOWN
* Typ pomiaru: `AXIS_COMPARISON`; okno: tak
* Procedura: Porównaj wartość OI na końcu okna z wartością na początku okna. FLAT tylko gdy etykiety osi/tooltip pokazują tę samą wartość.
* Wpisz `UNKNOWN`, gdy: różnicy nie da się rozstrzygnąć na osi (nie zgaduj FLAT)
* Wiarygodny pomiar wymaga: szereg czasowy OI (wielkość zmiany)

### `cvd_trend`

* Warstwa C; interwały 5M, 1M; wartości: RISING, FALLING, FLAT, UNKNOWN
* Typ pomiaru: `AXIS_COMPARISON`; okno: tak
* Procedura: Porównaj wartość CVD na końcu i na początku okna; FLAT tylko przy tej samej wartości.
* Wpisz `UNKNOWN`, gdy: różnicy nie da się rozstrzygnąć na osi (nie zgaduj FLAT)
* Wiarygodny pomiar wymaga: transakcje z flagą agresora

### `liquidations`

* Warstwa C; interwały 5M, 1M; wartości: LONGS_LIQUIDATED, SHORTS_LIQUIDATED, BOTH, NONE_SIGNIFICANT, UNKNOWN
* Typ pomiaru: `QUALITATIVE_VISUAL`; okno: tak
* Procedura: LONGS/SHORTS_LIQUIDATED: w oknie widać słupek likwidacji wyraźnie wyższy niż wszystkie inne słupki widoczne na tym samym screenshocie; BOTH: po obu stronach; NONE_SIGNIFICANT: brak takiego słupka.
* Wpisz `UNKNOWN`, gdy: skala słupków nie pozwala odróżnić wyróżniającego się słupka
* Wiarygodny pomiar wymaga: szereg wolumenu likwidacji (rozkład historyczny)

### `absorption_signal`

* Warstwa C; interwały 5M, 1M; wartości: BID_SIDE, ASK_SIDE, NONE, UNKNOWN
* Typ pomiaru: `DERIVED_INDICATOR`; okno: tak
* Procedura: Przepisz sygnał wskaźnika Absorption z okna (algorytm nieznany).
* Wpisz `UNKNOWN`, gdy: brak legendy znaczenia sygnału

Pola warstw D/E są zarejestrowane, lecz wyłączone; nie mają procedury, bo silnik ich nie używa.
