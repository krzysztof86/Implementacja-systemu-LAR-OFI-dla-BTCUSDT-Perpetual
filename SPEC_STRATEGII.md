# SPEC_STRATEGII — LAR-OFI (Liquidity, Aggression, Resiliency & Order Flow Imbalance)

Wersja specyfikacji: **2** (faza 5, po audycie; silnik `lar-ofi-engine/1`, schemat dziennika v2). Instrument: **Bybit BTCUSDT USDT Perpetual**.
Czas wewnętrzny: UTC. Wyświetlanie: Europe/Warsaw.

> To jest specyfikacja **hipotezy roboczej**. Żaden próg nie jest skalibrowany (`calibrated = false`).
> System nie składa zleceń i nie podaje prawdopodobieństw (`probability = NOT_CALIBRATED`).

Implementacja: `src/lar_ofi/engine.py` (stan rynku), `src/lar_ofi/setups.py` (setupy),
`src/lar_ofi/decision.py` (decyzja). Ten dokument opisuje dokładnie te reguły.

**Zmiany w wersji 2** (uzasadnienie i analiza: `FAZA_5_AUDYT_POPRAWKI.md`):
trzy znaczniki czasu (`data_as_of`, `decision_time`, `recorded_at`, §9); wymóg ostatniej zamkniętej
świecy 30M/5M i dowodu aktualności wykresu (§7); interwał decyzyjny MICRO — odczyt 1M nie może spełnić
warunku 5M (§2); procedury odczytu i okna obserwacji (`PROTOKOL_OBSERWACJI.md`); porównanie dwóch
heatmap nazwane jako jakościowa zmiana widocznej płynności, nie Liquidity Resiliency (§5); baseline
momentum tylko z cen znanych w chwili decyzji (§9); świece rozliczeniowe powiązane z rynkiem (§9).

---

## 1. Rozróżnienie poziomów wiedzy

| Poziom | Definicja w systemie | Przykład |
|---|---|---|
| **OBSERVED** | wartość odczytana przez człowieka (lub potwierdzony backend vision) z jednego konkretnego screenshotu; zawsze ma `observation_id` i `screenshot_id` | `oi_change (MICRO) = RISING` |
| **INFERRED** | deterministyczny wniosek z jednej lub kilku obserwacji według reguły z tej specyfikacji | `aggression_efficiency = INEFFECTIVE` (BUY + STALLED) |
| **HYPOTHESIS** | scenariusz / interpretacja kontekstowa, niebędąca warunkiem | „OI spada: zgodne z zamykaniem uwięzionych pozycji” |
| **UNKNOWN** | brak odczytu, odczyt nieczytelny/niepewny, dane wykluczone (nieaktualne, z przyszłości, bez znacznika czasu) | `ask_side_after_consumption = UNKNOWN: single snapshot` |

Odczyt `UNREADABLE` jest zapisywany jako `UNKNOWN` (wartość wpisana przez użytkownika jest odrzucana).
Odczyt `UNCERTAIN` jest domyślnie traktowany jako `UNKNOWN` (`observations.use_uncertain = false`).
Wyniki backendu vision są `UNVERIFIED` i ignorowane do czasu potwierdzenia (`lar-ofi confirm`).

## 2. Zakresy (scope) i interwały

| Scope | Interwały | Rola |
|---|---|---|
| CONTEXT | 4H | kontekst wyższego interwału — **nigdy nie jest warunkiem** |
| AUCTION | 30M | warstwa A — pozycja względem poprzedniego value area, akceptacja |
| MICRO | 5M, 1M | warstwy B i C — agresja, płynność, OI, likwidacje |

**Interwał decyzyjny MICRO** = `analysis_timeframe` z manifestu (5M lub 1M; domyślnie
`timeframes.micro_decision = 5M`). Dla pól używanych w warunkach setupów (agresja, reakcja ceny, OI,
płynność, porównanie heatmap):
* wartość musi pochodzić z interwału decyzyjnego; sam odczyt z drugiego interwału MICRO → `UNKNOWN`;
* zgodny odczyt z drugiego interwału to tylko kontrola spójności — **nie** dodatkowy dowód;
* jakakolwiek rozbieżność odczytów (także 5M vs 1M) → `CONFLICT` → WAIT.
Pola kontekstowe (`liquidations`, `absorption_signal`) mogą pochodzić z dowolnego interwału MICRO;
rozbieżność → `CONFLICT`. `last_price`: bierze się najpóźniejszy odczyt.

## 3. Schemat danych

### 3.1 Manifest zestawu (jeden moment analizy)

```json
{"manifest_version": 1, "instrument": "BTCUSDT", "exchange": "Bybit", "contract_type": "USDT_PERPETUAL",
 "source_platform": "OpenMarket.xyz", "data_source_config": "<giełdy w Agg.>", "analysis_timeframe": "5M",
 "regime_tag": null,
 "screenshots": [{"file": "...png", "timeframe": "5M", "indicators": ["Agg. CVD"],
                  "chart_instrument": "BTCUSDT", "captured_at_utc": "2026-10-20T09:59:45Z",
                  "data_last_update_utc": "2026-10-20T09:59:44Z", "live_feed_confirmed": false,
                  "view_settings": "<tylko heatmapy: zakres cen/czasu, skala barw>", "notes": ""}]}
```

`analysis_timeframe` musi być interwałem MICRO (5M/1M), inaczej zestaw odrzucony.
`live_feed_confirmed` (bool) — oświadczenie użytkownika, że wykres się aktualizował, gdy platforma nie
pokazuje czasu ostatniej aktualizacji. `view_settings` — wymagane identyczne w obu porównywanych heatmapach.

Walidacja: instrument / giełda / typ kontraktu muszą zgadzać się z konfiguracją (inaczej cały zestaw
odrzucony). Screenshot odrzucany przy: innym `chart_instrument`, nieznanym wskaźniku, nieprawidłowym
interwale, braku pliku, pustym pliku, pliku nie-obrazie (PNG/JPEG/WEBP po sygnaturze), duplikacie w
zestawie, nieprawidłowym znaczniku czasu (w tym bez strefy czasowej), czasie wykonania późniejszym niż
import, `data_last_update` późniejszym niż wykonanie. Flagowany (ale przyjęty): brak `captured_at_utc`,
brak `data_last_update_utc`, > 3 wskaźniki (limit workspace), wskaźnik warstwy D/E, nietypowy interwał
dla wskaźnika, ponowne użycie pliku z innego zestawu. `dataset_id` = SHA-256 manifestu + hashy plików,
więc ponowny import nic nie dodaje.

### 3.2 Słownik obserwacji (`src/lar_ofi/registry.py`)

Procedura odczytu każdego pola, typ pomiaru, okno obserwacji i warunki zapisu `UNKNOWN`:
**`PROTOKOL_OBSERWACJI.md`** (OBS-PROTOCOL-2). Pola z oknem (agresja, reakcja ceny, OI, CVD, likwidacje,
Absorption) wymagają `window_start_utc`/`window_end_utc`; okno musi kończyć się na ostatniej świecy
zamkniętej przed wykonaniem screenshotu, inaczej odczyt = `UNKNOWN` (`WINDOW_NOT_LATEST_CLOSED_BAR`).

| Pole | Warstwa | Interwały | Wskaźnik(i) | Wartości |
|---|---|---|---|---|
| `last_price` | A | wszystkie | dowolny | liczba |
| `prev_vah`, `prev_val`, `prev_poc` | A | 4H, 30M | Agg. TPO / Agg. Session Volume Profile | liczba |
| `price_vs_prev_value_area` | A | 4H, 30M | TPO / SVP | ABOVE, INSIDE, BELOW |
| `closed_bars_outside_value` | A | 30M | TPO / SVP | liczba całk. ≥ 0 — kolejne **zamknięte** bary 30M z zamknięciem poza poprzednim VA po bieżącej stronie |
| `returned_inside_value` | A | 30M | TPO / SVP | YES, NO — czy **ostatni zamknięty** bar 30M zamknął się z powrotem w VA po wyjściu poza nie w tej sesji |
| `violation_side` | A | 30M | TPO / SVP | UP, DOWN, NONE — handel powyżej VAH/ekstremum (UP) lub poniżej VAL (DOWN) w bieżącej sesji |
| `price_vs_avwap` | A | 4H, 30M | Anchored VWAP | ABOVE, AT, BELOW (kontekst) |
| `passive_liquidity_above` / `_below` | B | 5M, 1M | Agg. Order Book Heatmap | THIN, THICK, NOT_VISIBLE |
| `ask_side_after_consumption` / `bid_side_after_consumption` | B | 5M, 1M | Heatmap (**2 screenshoty**, `compared_with` = wcześniejszy) | REPLENISHED, NOT_REPLENISHED, NO_CONSUMPTION_SEEN |
| `footprint_aggression` | B | 5M, 1M | Agg. Volume Footprint | BUY_DOMINANT, SELL_DOMINANT, BALANCED |
| `price_response_to_aggression` | B | 5M, 1M | Footprint | ADVANCED, STALLED, REVERSED |
| `aggression_at_extreme` | B | 5M, 1M | Footprint | BUY, SELL, NONE |
| `price_response_at_extreme` | B | 5M, 1M | Footprint | ADVANCED, STALLED, REVERSED |
| `oi_change` | B | 5M, 1M | Agg. Open Interest | RISING, FALLING, FLAT |
| `cvd_trend` | C | 5M, 1M | Agg. CVD | RISING, FALLING, FLAT |
| `liquidations` | C | 5M, 1M | Agg. Liquidations | LONGS_LIQUIDATED, SHORTS_LIQUIDATED, BOTH, NONE_SIGNIFICANT |
| `absorption_signal` | C | 5M, 1M | Absorption (pochodny) | BID_SIDE, ASK_SIDE, NONE |
| warstwy D/E (`spot_cvd_trend`, `perp_cvd_trend`, `coinbase_premium`, `volatility_regime`, `gex_sign`) | D/E | — | — | przyjmowane, **ignorowane** przez silnik |

Każde pole może przyjąć `UNKNOWN`. Pola `ofi`, `queue_imbalance`, `price_impact`,
`liquidity_resiliency` itp. są **zakazane** jako obserwacje ze screenshotów.

### 3.3 Grupy źródeł (minimalna redundancja)

`footprint_aggression` i `cvd_trend` to dwa widoki **tych samych transakcji** → jedna grupa
`TRADE_AGGRESSION` i jedna wartość pochodna `trade_aggression`:

| footprint | CVD | `trade_aggression` |
|---|---|---|
| BUY / SELL / NEUTRAL | brak | wartość z footprint (adnotacja „single source”) |
| brak | RISING / FALLING / FLAT | BUY / SELL / NEUTRAL |
| zgodne | zgodne | ta wartość, adnotacja „ONE evidence group” — **nie** dwa potwierdzenia |
| BUY | FALLING (lub odwrotnie) | `CONFLICT` → WAIT |
| kierunek | neutralny (lub odwrotnie) | NEUTRAL (brak dominującej agresji) |

`aggression_efficiency`: UNKNOWN jeśli agresja lub reakcja nieznana; NOT_APPLICABLE przy NEUTRAL;
EFFECTIVE jeśli `price_response_to_aggression = ADVANCED`; w przeciwnym razie INEFFECTIVE.

## 4. Stany rynku (warstwa A, 30M)

| `market_state.label` | Reguła |
|---|---|
| `BALANCE_INSIDE_VALUE` | pozycja INSIDE i `violation_side = NONE` |
| `RETURNED_TO_VALUE_AFTER_UP/DOWN_VIOLATION` | pozycja INSIDE, naruszenie UP/DOWN, `returned_inside_value = YES` |
| `INSIDE_VALUE` | pozycja INSIDE, pozostałe przypadki |
| `OUTSIDE_VALUE_UP` / `OUTSIDE_VALUE_DOWN` | pozycja ABOVE / BELOW |
| `UNKNOWN` | brak / konflikt pozycji |

`acceptance`: `ACCEPTED_ABOVE/BELOW` gdy pozycja poza VA, `closed_bars_outside_value ≥ N`
(`acceptance_min_closed_bars_30m`, domyślnie **2 — założenie projektu, nieskalibrowane**) i
`returned_inside_value = NO`; `TESTING_*` gdy < N; `REJECTED_BACK_INSIDE` gdy `returned = YES`.

## 5. Setupy — reguły IF–THEN

Logika trójwartościowa: warunek z wejściem UNKNOWN/CONFLICT ma status UNKNOWN.
Brak głosowania i wag. Stan wariantu:

```
IF trigger UNKNOWN                                 THEN WAIT
IF trigger FALSE                                   THEN NONE
                                                   (INVALIDATED, jeśli poprzedni stan tego setupu
                                                    był CANDIDATE/CONFIRMED w tym kierunku)
IF trigger TRUE AND dowolny warunek unieważnienia TRUE   THEN INVALIDATED
IF trigger TRUE AND wszystkie candidate TRUE
       AND wszystkie confirmation TRUE             THEN CONFIRMED_<kier>
IF trigger TRUE AND wszystkie candidate TRUE       THEN CANDIDATE_<kier>
IF trigger TRUE AND żaden candidate FALSE (część UNKNOWN) THEN WAIT
ELSE                                               NONE
```

### 5.1 Setup 1 — CONTINUATION / AUCTION ACCEPTANCE

Hipoteza: rynek opuszcza poprzedni value area, a agresja skutecznie przesuwa cenę bez odbudowy
przeciwnej strony — kontynuacja jest możliwa.

| Id | LONG | SHORT (lustro) |
|---|---|---|
| **C-T** trigger | 30M `price_vs_prev_value_area = ABOVE` | `= BELOW` |
| **C-1** candidate | `trade_aggression = BUY` (footprint+CVD jako jedna grupa) | `= SELL` |
| **C-X1** unieważnienie | `returned_inside_value = YES` (ostatni zamknięty bar 30M z powrotem w VA) | to samo |
| **C-X2** unieważnienie | agresja BUY **i** `aggression_efficiency = INEFFECTIVE` (kupno absorbowane) | SELL + INEFFECTIVE |
| **C-2** confirmation | `closed_bars_outside_value ≥ N` **i** `returned_inside_value = NO` | to samo |
| **C-3** confirmation | `aggression_efficiency = EFFECTIVE` | to samo |
| **C-4** confirmation | `ask_side_after_consumption = NOT_REPLENISHED` (jakościowe porównanie 2 heatmap o identycznych `view_settings`; **nie** pomiar resiliency) — lub, jeśli `require_resiliency_for_confirmation = false`, `passive_liquidity_above ∈ {THIN, NOT_VISIBLE}` | `bid_side_…` / `passive_liquidity_below` |
| **C-5** confirmation | `oi_change ∈ {RISING, FLAT}` (ruch nie jest wyłącznie zamykaniem pozycji) | to samo |
| kontekst (nie warunek) | SHORTS_LIQUIDATED/BOTH → PRZECIW (ruch może być wymuszony); OI RISING → ZA; Absorption ASK_SIDE → PRZECIW (pomocniczo); gruba płynność ask → PRZECIW; 4H po tej samej stronie → ZA | lustrzanie |

Samo naruszenie VAH/VAL **nie jest** potwierdzeniem (test `test_mere_violation_of_vah_is_not_confirmation`).

### 5.2 Setup 2 — FAILED AUCTION / FAILED BREAKOUT

Hipoteza: agresja poza istotnym poziomem nie prowadzi do akceptacji — rotacja z powrotem do wartości.
SHORT = nieudane wybicie w górę; LONG = nieudane wybicie w dół.

| Id | SHORT (nieudane wybicie UP) | LONG (nieudane wybicie DOWN) |
|---|---|---|
| **F-T** trigger | `violation_side = UP` | `= DOWN` |
| **F-1** candidate | `aggression_at_extreme = BUY` | `= SELL` |
| **F-2** candidate | `price_response_at_extreme ∈ {STALLED, REVERSED}` | to samo |
| **F-X1** unieważnienie | akceptacja: pozycja ABOVE **i** `closed_bars_outside_value ≥ N` **i** `returned = NO` | BELOW … |
| **F-X2** unieważnienie | `price_response_at_extreme = ADVANCED` (agresja skuteczna) | to samo |
| **F-3** confirmation | `returned_inside_value = YES` **i** pozycja INSIDE | to samo |
| **F-4** confirmation | `ask_side_after_consumption = REPLENISHED` (jakościowe porównanie 2 heatmap o identycznych `view_settings`; **nie** pomiar resiliency) — lub przy wyłączonym wymogu `passive_liquidity_above = THICK` | `bid_side…` / `passive_liquidity_below` |
| kontekst (nie warunek) | OI FALLING → ZA; OI RISING → NEUTRALNY; LONGS_LIQUIDATED/BOTH → ZA; Absorption ASK_SIDE → ZA (pomocniczo, nigdy samodzielnie) | lustrzanie |

Knot świecy, delta czy Absorption **same** nie wystarczają: bez F-1, F-2, F-3, F-4 nie ma CONFIRMED
(test `test_wick_or_delta_or_absorption_alone_never_confirms_failed_auction`).

## 6. Decyzja i reguła konfliktu (`decision.py`)

Pierwsza pasująca reguła:

| Reguła | Warunek | Wynik |
|---|---|---|
| D1 | jakikolwiek problem blokujący danych: brak screenshotów, brak obserwacji, brak znacznika czasu na screenshocie niosącym dane (30M/5M/1M), nieaktualność przy `stale_policy = block`, opóźnienie danych wykresu, brak synchronizacji | **WAIT** |
| D2 | konflikt blokujący (rozbieżne odczyty, footprint vs CVD, cena vs VA, pozycja vs naruszenie, `returned = YES` przy barach poza VA, powrót bez naruszenia, VAH ≤ VAL) | **WAIT** |
| D3 | żaden setup nie jest CONFIRMED | **WAIT** |
| D4 | setupy wskazują różne kierunki (CONFIRMED vs CANDIDATE/CONFIRMED przeciwny) | **WAIT** |
| D5 | w pozostałych przypadkach | kierunek setupu CONFIRMED (**LONG/SHORT**) |

CANDIDATE zawsze daje WAIT z wypisanym **warunkiem potwierdzenia** (niespełnione warunki).

## 7. Warunki WAIT — lista zbiorcza

1. Brak screenshotów lub brak użytecznych obserwacji (`NO_DATA`).
Punkty 2–5 dotyczą screenshotów warstw decyzyjnych (30M/5M/1M), które **niosą obserwacje**;
screenshot bez obserwacji jest raportowany, ale nie blokuje decyzji.

2. Brak znacznika czasu na screenshocie warstw decyzyjnych (`INSUFFICIENT_DATA`).
3. Screenshot starszy niż `freshness.max_age_seconds[tf]` (domyślnie 1M: 120 s, 5M: 600 s,
   30M: 2700 s, 4H: 21600 s — **polityka użytkownika**).
4. `captured_at − data_last_update > max_update_lag_seconds` (120 s) albo **brak** `data_last_update_utc`
   i brak `live_feed_confirmed` (`FRESHNESS_UNVERIFIABLE`; polityka `require_update_evidence = true`).
4a. Screenshot 30M lub 5M wykonany **przed** ostatnim zamknięciem świecy swojego interwału przed czasem
   decyzji (`MISSING_LATEST_CLOSED_BAR`; `require_latest_closed_bar = ["30M", "5M"]`, świece wyrównane do UTC).
5. Rozrzut czasów wykonania w MICRO > 180 s lub w AUCTION > 900 s.
6. Dowolny konflikt z sekcji 6 (D2) lub konflikt setupów (D4).
7. Brak potwierdzenia: którykolwiek warunek confirmation FALSE lub UNKNOWN (w tym odbudowa przy jednym
   screenshocie heatmapy).
8. Unieważnienie setupu.

Screenshoty z czasem późniejszym niż czas decyzji są **wykluczane** (nie blokują i nie wpływają na decyzję).
Screenshot użyty wyłącznie jako wcześniejsza strona porównania heatmap nie podlega limitowi
świeżości/synchronizacji; jego wiek ogranicza `resiliency_max_gap_seconds` (900 s).

## 8. Macierz wymaganych wskaźników

| Decyzja / stan | Agg. TPO lub SVP (30M) | Footprint (5M/1M) | CVD | Heatmap ×2 (5M/1M) | Agg. OI | Liquidations | Absorption | AVWAP / 4H |
|---|---|---|---|---|---|---|---|---|
| CONTINUATION CANDIDATE | **wymagany** | **wymagany** albo CVD | albo footprint | — | — | — | — | — |
| CONTINUATION CONFIRMED | **wymagany** | **wymagany** (reakcja ceny) | opcjonalny (ta sama grupa) | **wymagane 2** | **wymagany** | kontekst | kontekst | kontekst |
| FAILED_AUCTION CANDIDATE | **wymagany** | **wymagany** (ekstremum) | — | — | — | — | — | — |
| FAILED_AUCTION CONFIRMED | **wymagany** | **wymagany** | — | **wymagane 2** | kontekst | kontekst | kontekst (nigdy sam) | — |

Limit 3 wskaźników na workspace: minimalny zestaw do CONFIRMED w obu setupach to 4 screenshoty:
(1) 30M: TPO + SVP + AVWAP, (2) 5M heatmap wcześniej, (3) 5M heatmap teraz, (4) 5M: Footprint + OI + CVD;
opcjonalnie (5) 1M: Liquidations + Absorption, (6) 4H: TPO. Szablon: `examples/manifest_template.json`.

## 9. Prognoza i rozliczenie

* Horyzonty: 5 i 15 minut. Prawdopodobieństwo: `NOT_CALIBRATED`.
* Trzy znaczniki czasu:
  `data_as_of` = czas wykonania najnowszego screenshotu, którego obserwacje silnik faktycznie użył
  (gdy żaden nie jest użyteczny — najnowszego niosącego obserwacje, nie późniejszego niż decyzja);
  `decision_time` = zegar systemowy w chwili oceny (`lar-ofi predict`);
  `recorded_at` = zegar w chwili zapisu (odczytany osobno, po ocenie).
  Wymagane `data_as_of ≤ decision_time ≤ recorded_at`, `recorded_at − data_as_of ≤ 120 s`
  (`max_record_delay_seconds`) i `recorded_at − decision_time ≤ 30 s` (`max_decision_to_record_seconds`).
  Inaczej `LATE_RECORDING` — prognoza nie jest zapisywana.
* Reguła rozliczenia zamrażana w prognozie: wejście = open pierwszej świecy 1m z `open_time ≥ recorded_at`;
  wyjście = open świecy `entry + h`; źródło cen = etykieta CSV użytkownika **oraz rynek**
  (instrument, giełda, typ kontraktu). Świece innego rynku nigdy nie rozliczają prognozy.
* Baseline momentum: kierunek = znak(close świecy 1m zamkniętej o `floor_minute(decision_time)` − close
  świecy zamkniętej h minut wcześniej) — wyłącznie ceny znane w chwili decyzji. Wynik baseline'u jest
  liczony na tym samym symulowanym wejściu/wyjściu co system.
* Ruch nieistotny: `|zwrot| ≤ neutral_band_bps` → NEUTRAL (dla WAIT: NO_SIGNIFICANT_MOVE). Pasmo =
  `evaluation.neutral_band_bps` lub, gdy brak, koszt round-trip z modelu kosztów. Gdy brak obu →
  `UNSCORABLE` (trafność nie jest oceniana).
* Koszt round-trip (tylko z parametrów użytkownika): opłata wejścia + opłata wyjścia + spread × (liczba
  nóg taker)/2 + poślizg × (liczba nóg taker); funding tylko gdy podano `funding_times_utc` i koszt.

## 10. Mapowanie mechanizmów do publikacji

Szczegóły i ograniczenia: `RESEARCH_EVIDENCE.md`, sekcja F. Skrót:

| Reguła | Źródło mechanizmu | Charakter |
|---|---|---|
| C-3, C-X2, F-2, F-X2 (agresja vs ruch ceny) | Cont, Kukanov, Stoikov (2014) — wpływ przepływu zależny od głębokości | hipoteza projektu (przybliżenie jakościowe) |
| C-4, F-4 (jakościowa zmiana widocznej płynności, 2 screenshoty) | inspiracja: Large (2007) — resiliency; **nie jest to pomiar resiliency** | hipoteza projektu |
| Grupa TRADE_AGGRESSION | Schmalz (2026) — trade-flow imbalance nieistotny samodzielnie | reguła metodologiczna |
| C-T, C-2, F-T, F-3, F-X1 (value area, akceptacja) | teoria aukcji / Market Profile — **poza listą publikacji** | hipoteza projektu |
| C-5, kontekst OI / likwidacje | brak źródła w zestawie | hipoteza projektu |
| MODE B: OFI, QI, price impact | Cont et al. (2014); Gould & Bonart (2016) | definicje z publikacji |
| Baseline'y, chronologia, ujawnianie uruchomień | Schmalz (2026) | kontrola metodologiczna |
| Domyślna egzekucja taker, brak modelu ryzyka maker | Bieganowski & Ślepaczuk (2026) | kontrola metodologiczna |
