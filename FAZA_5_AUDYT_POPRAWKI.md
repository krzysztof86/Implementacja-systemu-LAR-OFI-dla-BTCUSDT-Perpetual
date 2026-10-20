# FAZA 5 — poprawki po niezależnym audycie

Gałąź: `faza-5-poprawki-audytu` (od commita `2322a6c` z gałęzi `ccr-c24d3880-0mfxmy`).
Zakres: wyłącznie problemy wskazane w audycie. Nie powstała nowa strategia, progi strategiczne
(`acceptance_min_closed_bars_30m = 2`, polityki świeżości, `max_record_delay_seconds = 120`) **nie zostały
zmienione**. Brak danych empirycznych — **nie deklaruję poprawy trafności**.

Numery linii odnoszą się do stanu gałęzi po tej fazie. Testy: `FAZA_5_TESTY.md`.

---

## P0.1 — Bezpieczeństwo czasowe: trzy znaczniki czasu

**Ustalenie (potwierdzone):** `cmd_predict()` ustawiał `as_of = recorded_at = now`, a
`record_prediction()` mierzył opóźnienie jako `recorded_at − as_of`, czyli zawsze 0 s. Limit
`max_record_delay_seconds` nigdy nie mógł zadziałać. Odtworzenie na starym kodzie (commit `2322a6c`):
zestaw screenshotów sprzed godziny został zapisany w dzienniku (`prediction_id a95a91aa61496144`).
Przy luźniejszej polityce świeżości (polityka użytkownika) mogła to być prognoza kierunkowa.

**Zmiana:**

| Znacznik | Definicja | Gdzie |
|---|---|---|
| `data_as_of` | czas wykonania najnowszego screenshotu, którego obserwacje silnik faktycznie użył; gdy żaden nie jest użyteczny — najnowszego niosącego obserwacje, nie późniejszego niż decyzja (`data_as_of_basis`) | `src/lar_ofi/engine.py:179-193` |
| `decision_time` | zegar w chwili oceny (`predict`) lub wartość `--decision-time` (`analyze`) | `src/lar_ofi/cli.py:148`, `src/lar_ofi/observations.py:264-286` |
| `recorded_at` | zegar odczytany **osobno**, po ocenie, tuż przed zapisem | `src/lar_ofi/cli.py:151` |

`record_prediction()` (`src/lar_ofi/journal.py:73-93`) wymaga `data_as_of ≤ decision_time ≤ recorded_at`
(`TIME_ORDER_VIOLATION`), `recorded_at − data_as_of ≤ max_record_delay_seconds` i
`recorded_at − decision_time ≤ max_decision_to_record_seconds` (nowa wartość 30 s — ograniczenie
inżynierskie na czas oceny i zapisu, `default_config.toml:67`); brak `data_as_of` → `NO_DATA_AS_OF`.
Wszystkie trzy czasy są osobnymi kolumnami dziennika (`src/lar_ofi/db.py:72-74`) i wchodzą do hasha rekordu.

Schemat dziennika podniesiony do v2 (`src/lar_ofi/db.py:9`). Dziennik v1 nie jest otwierany
(`SchemaError`, `db.py:160-170`), bo jego rekordy powstały z wadliwą regułą czasu i nie mogą być mieszane.

## P0.2 — Baseline momentum bez informacji z przyszłości

**Ustalenie (potwierdzone):** kierunek baseline'u liczono jako `znak(open(entry) − open(entry − h))`, gdzie
`entry = ceil_minute(recorded_at)`. Dla prognozy zapisanej między granicami minut cena `open(entry)` nie
była znana w chwili decyzji. Odtworzenie na starym kodzie: ceny znane o 10:00:35 spadały, a świeca 10:00
wybiła w górę → stary baseline dał **LONG**.

**Zmiana:** `momentum_baseline()` (`src/lar_ofi/journal.py:262-273`): kierunek =
`znak(close świecy zamkniętej o floor_minute(decision_time) − close świecy zamkniętej h minut wcześniej)`.
Rekord baseline'u zawiera `known_at_utc` i otwarcia użytych świec. Wynik baseline'u nadal liczony jest na
tym samym symulowanym wejściu/wyjściu co system (`journal.py:345-350`); cena wejścia jest osobną, późniejszą
wielkością. Reguła zamrażana w prognozie jako `baseline_rule` (`journal.py:63`).

## P1 — Powtarzalność obserwacji

**Ustalenie:** etykiety THIN/THICK, ADVANCED/STALLED/REVERSED, REPLENISHED/NOT_REPLENISHED,
BUY_DOMINANT/SELL_DOMINANT nie miały procedury; dwóch obserwatorów mogło odczytać ten sam obraz inaczej.

**Zmiany:**
1. `OBS-PROTOCOL-2` w `src/lar_ofi/registry.py:242-376`: dla każdego aktywnego pola typ pomiaru, procedura,
   lista sytuacji wymagających `UNKNOWN` i — gdzie dotyczy — dane ilościowe potrzebne do wiarygodnego
   pomiaru. Bez wymyślonych progów: procedury używają znaków wydrukowanych wartości (SIGN_RULE),
   zamknięć względem ekstremów świec (BAR_EXTREME_RULE), wartości na początku/końcu okna (AXIS_COMPARISON)
   albo porównania w obrębie jednego obrazu (QUALITATIVE_VISUAL). Dokument dla człowieka:
   `PROTOKOL_OBSERWACJI.md`, generowany z rejestru (`scripts/gen_protocol_doc.py`) i sprawdzany testem.
   * BUY_DOMINANT/SELL_DOMINANT: **wszystkie** świece w oknie mają dodatnią/ujemną deltę; mieszane → BALANCED;
     nieczytelny znak którejkolwiek → UNKNOWN.
   * ADVANCED/STALLED/REVERSED: zamknięcie ostatniej świecy względem zakresu świec agresji; brak świecy po
     agresji lub zamknięcie na krawędzi → UNKNOWN.
   * THIN/THICK: tylko w obrębie jednego screenshotu (skala barw normalizowana per widok).
   * REPLENISHED/NOT_REPLENISHED: ten sam poziom cenowy na dwóch heatmapach o identycznych `view_settings`.
2. **Okno obserwacji** dla pól zależnych od okna: `window_start_utc`/`window_end_utc` obowiązkowe przy
   wartości różnej od UNKNOWN, na granicach świec, nie po wykonaniu screenshotu
   (`src/lar_ofi/observations.py:70-72, 102-123`); silnik traktuje okno niekończące się na ostatniej
   zamkniętej świecy jako UNKNOWN (`src/lar_ofi/engine.py:250-258, 296-298`).
3. **Porównanie heatmap** wymaga identycznych, niepustych `view_settings` (`engine.py:238-239`); pole
   manifestu `view_settings` (`src/lar_ofi/intake.py:182-185`).
4. **Oddzielenie od Liquidity Resiliency:** grupa `VISUAL_LIQUIDITY_CHANGE` (`registry.py:26-28`),
   klucze stanu `ask_side_visual_change`/`bid_side_visual_change` (`engine.py:499-502`), teksty warunków C-4/F-4
   (`src/lar_ofi/setups.py:140-143, 212-215`), pytanie 6 raportu (`src/lar_ofi/report.py:42-45`).
   Prawdziwy pomiar odbudowy pozostaje wyłącznie w MODE B (`lar_ofi/l2`), nadal wyłączonym.

**Pola wymagające danych ilościowych** (na screenshotach tylko przybliżenia jakościowe):
`passive_liquidity_*` (głębokość L2), `ask/bid_side_after_consumption` (strumień zdarzeń L2),
`footprint_aggression`, `aggression_at_extreme`, `cvd_trend` (transakcje z flagą agresora), `oi_change`
(szereg OI), `liquidations` (szereg wolumenu likwidacji). Pełna tabela: `PROTOKOL_OBSERWACJI.md`.

## P1 — Reguły strategiczne: analiza i decyzje

### a) Wymóg dwóch zamknięć 30M a prognoza 5M/15M

* **Fakt:** CONTINUATION CONFIRMED wymaga ≥ 2 zamkniętych świec 30M poza VA. Najwcześniejsze potwierdzenie
  następuje ≥ 60 min po otwarciu pierwszej świecy poza VA. FAILED_AUCTION wymaga zamknięcia 30M z powrotem
  w VA — potwierdzenie możliwe tylko na granicach :00/:30.
* **Konsekwencje:** (1) sygnał opisuje dojrzałą nierównowagę, a horyzont 5/15 min jest 2–6× krótszy niż
  krok aktualizacji warunku aukcyjnego; (2) wszystkie prognozy w obrębie jednej świecy 30M dzielą te same
  fakty aukcyjne → są silnie zależne (obsłużone w ewaluacji przez próbę bez nakładania, ale zależność
  przez wspólny stan 30M **nie** jest w pełni usunięta); (3) duży udział WAIT/CANDIDATE.
* **Wcześniej brakowało:** screenshot 30M mógł mieć do 45 min (`max_age 30M = 2700 s`) i nie zawierać
  ostatniego zamknięcia, od którego zależą `closed_bars_outside_value` i `returned_inside_value`.
* **Decyzja:** próg N = 2 **bez zmian** (zmiana bez danych byłaby dopasowaniem). Dodano regułę
  poprawności (nie próg): screenshot 30M i 5M musi być wykonany po ostatnim zamknięciu swojej świecy przed
  czasem decyzji (`MISSING_LATEST_CLOSED_BAR`, `engine.py:196-216`, `default_config.toml:30`).
  To **zmniejsza** liczbę sygnałów; uzasadnieniem jest poprawność, nie liczba sygnałów.
* **Rekomendacja do kalibracji (nie wdrożona):** porównać na segmencie DEVELOPMENT wyniki na horyzoncie
  zgodnym z krokiem 30M; obecnie horyzonty 5/15 min pozostają, bo tak określiło zadanie.

### b) Scalanie odczytów 1M i 5M

* **Wcześniej:** 1M i 5M były jednym zakresem MICRO; sam odczyt 1M mógł spełnić warunek, mimo innego okna.
* **Teraz** (`engine.py:36-41, 266, 303-340`): interwał decyzyjny = `analysis_timeframe` manifestu (5M/1M,
  domyślnie 5M; inna wartość → odrzucenie zestawu, `intake.py:102-109`). Pola warunków muszą pochodzić z
  interwału decyzyjnego; sam odczyt z drugiego interwału → UNKNOWN; zgodny odczyt drugiego interwału
  → tylko kontrola spójności (nie dodatkowy dowód); jakakolwiek rozbieżność → CONFLICT → WAIT.

### c) Konflikty między interwałami

| Para | Reguła | Skutek dla decyzji |
|---|---|---|
| 4H vs 30M | 4H wyłącznie kontekst | brak wpływu na LONG/SHORT; raportowane jako ZA/NEUTRAL |
| 30M vs 5M | różne pola (aukcja vs agresja); niezgodność kierunku daje FALSE w warunku, nie konflikt | NONE / CANDIDATE / INVALIDATED → WAIT |
| 5M vs 1M (to samo pole) | rozbieżność → CONFLICT (D2) | WAIT |
| 1M bez 5M | UNKNOWN dla pól warunków | CANDIDATE lub WAIT |

### d) Aktualność informacji w każdej warstwie (stan po zmianach)

| Warstwa | Reguły aktualności | Rola |
|---|---|---|
| 4H (CONTEXT) | max 21600 s; dowód aktualności | kontekst — nieaktualność tylko wyklucza |
| 30M (AUCTION) | ostatnia zamknięta świeca 30M + max 2700 s + dowód aktualności + synchronizacja 900 s | warunki C-T, C-2, F-T, F-3 |
| 5M (MICRO, decyzyjny) | ostatnia zamknięta świeca 5M + max 600 s + dowód aktualności + synchronizacja 180 s | warunki C-1…C-5, F-1, F-2, F-4 |
| 1M (MICRO, pomocniczy) | max 120 s + dowód aktualności + synchronizacja 180 s | kontrola spójności, kontekst |
| zapis prognozy | `recorded_at − data_as_of ≤ 120 s`, `recorded_at − decision_time ≤ 30 s` | anty-lookahead |

Reguła ostatniej zamkniętej świecy **nie** obejmuje 1M: przy ręcznym wprowadzaniu wymagałaby zapisu w tej
samej minucie co screenshot. 1M nie spełnia warunków samodzielnie, więc jego wiek ogranicza `max_age`.

### Konsekwencje dla LONG/SHORT/WAIT

* LONG/SHORT wymaga teraz dodatkowo: okien obserwacji kończących się na ostatniej zamkniętej świecy,
  identycznych `view_settings` heatmap, dowodu aktualności każdego screenshotu niosącego dane, screenshotów
  30M/5M po ostatnim zamknięciu, odczytów warunków z interwału decyzyjnego i zapisu ≤ 120 s od najnowszego
  użytego screenshotu.
* **Praktyczny skutek:** domyślne polityki wymagają, by od wykonania najnowszego screenshotu do `predict`
  minęło ≤ 120 s. Ręczne wpisanie ~15 pól w tym czasie jest trudne; spodziewam się przewagi WAIT/
  `NOT_RECORDED`. Nie poluzowałem polityk — to decyzja użytkownika (z ujawnionym hashem konfiguracji).
* Testy graniczne: `tests/test_faza5.py:258-295` (30M: 570 s vs 571 s; 5M: 270 s vs 271 s; N−1 vs N barów)
  oraz testy 1M/5M `tests/test_faza5.py:298-345`.

## P1 — Ewaluacja

**Ustalenia:** (1) wniosek „PRELIMINARY” powstawał z porównania dolnej granicy przedziału Wilsona systemu
z **punktową** trafnością baseline'u — to nie jest test różnicy; (2) prognozy z nakładającymi się oknami
traktowano jak niezależne; (3) wyniki kierunkowe, coverage, koszty i próba niezależna nie były wyraźnie
rozdzielone.

**Zmiany** (`src/lar_ofi/evaluation.py`):
* porównanie **parowane** na tych samych prognozach: dokładny test McNemara na parach niezgodnych
  (`:98-105, 129-153`), poprawka Bonferroniego na liczbę porównań (baseline'y × horyzonty, `:208`);
* **próba bez nakładania**: chronologiczne przerzedzenie, zachowuje prognozę tylko, gdy jej okno
  `[entry, exit)` zaczyna się po wyjściu poprzedniej (`:108-117`); liczba prognoz w nakładających się
  oknach raportowana (`:120-126`); horyzonty 5 i 15 min nigdy nie są łączone;
* wniosek tylko z segmentu TEST (po `test_start_utc`) i tylko gdy konfiguracja w nim się nie zmieniła
  (`:210-222, 273-283`); w pozostałych `IN_SAMPLE_DESCRIPTIVE_ONLY`;
* wynik ma cztery osobne części: `directional_accuracy`, coverage (poziom segmentu), `after_costs`,
  `independent_sample` (`:223-251`); przedziały Wilsona oznaczone jako opisowe.

**Ograniczenie, które pozostaje:** zależność szeregowa poza horyzontem (wspólny stan 30M, klastrowanie
zmienności) nie jest modelowana; przerzedzenie usuwa tylko wspólne ścieżki cen.

## P2 — Integralność danych

1. **Świece powiązane z rynkiem:** tabela `price_bars` ma kolumny `instrument`, `exchange`,
   `contract_type`, `interval` w kluczu głównym (`src/lar_ofi/db.py:111-124`). Import wymaga rynku z kolumn
   CSV (`symbol`, `exchange`, `contract_type`) lub jawnej deklaracji (`--instrument --exchange
   --contract-type`); brak → `MARKET_UNDECLARED`; niezgodność CSV z deklaracją → błąd wiersza
   (`src/lar_ofi/journal.py:174-241`). Reguła rozliczenia zamraża rynek prognozy (`journal.py:54-55`),
   a rozliczenie i baseline pobierają wyłącznie świece tego rynku (`journal.py:244-259, 317-323`).
2. **Brak `data_last_update_utc`:** wcześniej taki screenshot omijał kontrolę `DATA_NOT_UPDATED`, więc
   zamrożony wykres z bieżącym czasem screenshotu przechodził jako aktualny — **potwierdzone**. Teraz screenshot
   warstw decyzyjnych bez `data_last_update_utc` i bez jawnego oświadczenia `live_feed_confirmed: true` jest
   nieaktualny (`FRESHNESS_UNVERIFIABLE`, `engine.py:212-215`; polityka `require_update_evidence`,
   `default_config.toml:33`). Oświadczenie jest zapisywane przy screenshocie (`intake.py:170-181`).

## Czego nie zmieniłem

* Progi strategii i polityki użytkownika (z wyjątkiem nowych, jawnie opisanych polityk poprawności).
* Moduł L2 (MODE B) — poza nazewnictwem nie dotyczył go audyt.
* Kod składania zleceń — nie istnieje i nie powstał.
