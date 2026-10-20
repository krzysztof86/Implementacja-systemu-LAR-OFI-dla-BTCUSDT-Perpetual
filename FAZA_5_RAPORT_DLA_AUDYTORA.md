# FAZA 5 — RAPORT DLA AUDYTORA

Gałąź: `faza-5-poprawki-audytu`, bazująca na `ccr-c24d3880-0mfxmy` @ `2322a6c`. Publikacja przez pull
request **bez automatycznego mergowania**. Szczegóły merytoryczne: `FAZA_5_AUDYT_POPRAWKI.md`;
wyniki testów: `FAZA_5_TESTY.md`; procedury odczytu: `PROTOKOL_OBSERWACJI.md`.

## 1. Status ustaleń audytu

| Ustalenie | Priorytet | Status | Dowód |
|---|---|---|---|
| `predict` ustawiał `as_of = now`, limit opóźnienia nie działał | P0 | **naprawione**; błąd odtworzony na starym kodzie | `test_p0_late_decision_on_old_data_is_refused_even_if_recorded_promptly`, `test_cli_predict_on_old_screenshots_is_not_recorded`, `test_cli_predict_detects_late_recording_with_simulated_clock` |
| Baseline momentum używał ceny spoza chwili decyzji | P0 | **naprawione**; błąd odtworzony na starym kodzie | `test_p0_momentum_baseline_between_minute_boundaries_has_no_lookahead`, `test_p0_momentum_baseline_unit` |
| Brak procedur klasyfikacji odczytów | P1 | **naprawione w zakresie procedur i wymuszeń w kodzie**; powtarzalność między obserwatorami **niezmierzona** | `test_p1_every_enabled_field_has_a_written_procedure`, `test_p1_window_*`, `test_p1_protocol_document_is_generated_from_registry` |
| Ocena dwóch heatmap mylona z Liquidity Resiliency | P1 | **naprawione** (nazewnictwo, wymóg `view_settings`) | `test_p1_visual_comparison_is_not_labelled_as_resiliency`, `test_p1_heatmap_comparison_needs_identical_view_settings` |
| Reguły strategiczne: 2×30M vs 5/15 min, scalanie 1M/5M, konflikty, aktualność | P1 | **przeanalizowane**; zmiany poprawności (nie progów); progi bez zmian | `FAZA_5_AUDYT_POPRAWKI.md` §P1; testy graniczne `test_p1_30m_*`, `test_p1_5m_*`, `test_p1_acceptance_boundary`, `test_p1_1m_*` |
| Wilson vs punktowy baseline jako „dowód przewagi” | P1 | **naprawione** (McNemar dokładny, parowany, Bonferroni) | `test_p1_high_accuracy_equal_to_baseline_is_not_an_edge`, `test_p1_claim_only_from_independent_segment_and_bonferroni`, `test_p1_mcnemar_exact_values` |
| Zależność nakładających się prognoz | P1 | **częściowo**: przerzedzenie usuwa wspólne ścieżki cen; zależność szeregowa poza horyzontem pozostaje | `test_p1_overlapping_predictions_are_thinned`, `test_p1_insufficient_non_overlapping_sample` |
| Rozróżnienie trafność / coverage / koszty / próba niezależna | P1 | **naprawione** (cztery osobne sekcje raportu ewaluacji) | `evaluation.py:223-251`, `test_p1_claim_only_from_independent_segment_and_bonferroni` |
| Świece bez powiązania z rynkiem | P2 | **naprawione** | `test_p2_bars_of_another_market_never_settle_a_prediction`, `test_p2_bar_market_must_be_declared_and_consistent`, `test_cli_import_bars_requires_market` |
| Brak `data_last_update_utc` omijał kontrolę aktualności | P2 | **potwierdzone i naprawione** | `test_p2_missing_last_update_cannot_pass_as_fresh`, `test_p2_user_live_attestation_is_accepted_and_recorded` |

## 2. Zmienione pliki i linie (stan po fazie 5)

Zakresy funkcji wyliczone z AST (`ast.FunctionDef.lineno/end_lineno`) na stanie gałęzi po fazie 5.

| Plik | Linie | Zmiana |
|---|---|---|
| `src/lar_ofi/cli.py` | 54-56 | `_clock()` — jedno źródło czasu (podmienialne w teście integracyjnym) |
| | 143-158 | `cmd_predict`: `decision_time = _clock()` przed oceną (148), `recorded_at = _clock()` osobno przed zapisem (151) |
| | 161-171 | `cmd_import_bars`: rynek z flag, `REJECTED` przy `MARKET_UNDECLARED` |
| | 87-98, 109-124 | `observe` z oknem; `confirm` przenosi okno korygowanej obserwacji |
| | 217-264 | parser: `--decision-time`, `--window-start/--window-end`, `--instrument/--exchange/--contract-type` |
| | 13, 267-274 | obsługa `SchemaError` |
| `src/lar_ofi/journal.py` | 1-24 | opis trzech znaczników czasu i reguły baseline'u |
| | 41-66 | `resolution_rule`: zamrożony `market` (54-55) i `baseline_rule` (63) |
| | 73-136 | `record_prediction`: `NO_DATA_AS_OF` (80), `TIME_ORDER_VIOLATION` (82), `LATE_RECORDING` od `data_as_of` (87) i od `decision_time` (93); trzy czasy zapisane i w hashu rekordu |
| | 174-241 | `import_price_bars`: rynek z kolumn CSV lub deklaracji; `MARKET_UNDECLARED` (193), niezgodność → błąd wiersza (202) |
| | 244-259 | `_bar`, `_bar_open`, `_bar_close` filtrowane rynkiem |
| | 262-273 | `momentum_baseline`: tylko świece zamknięte do `floor_minute(decision_time)` |
| | 300-364 | `resolve_predictions`: świece rynku prognozy (317-323), baseline z `decision_time` (345-350) |
| `src/lar_ofi/engine.py` | 33-41 | `GATING_MICRO_FIELDS` |
| | 126-193 | `_screen_screenshots`: `data_as_of` z użytych screenshotów + `data_as_of_basis` (179-192) |
| | 196-216 | `_staleness`: `MISSING_LATEST_CLOSED_BAR` (204-208), `FRESHNESS_UNVERIFIABLE` (212-215) |
| | 223-247 | `_comparison_problem`: identyczne `view_settings` (236-239) |
| | 250-258 | `_window_problem`: okno kończy się na ostatniej zamkniętej świecy |
| | 261-340 | `_resolve`: PRIMARY/SECONDARY (303-305), sam odczyt drugiego interwału → UNKNOWN (331-335), zgodny → bez wagi (337-339) |
| | 499-503 | `ask/bid_side_visual_change` (zamiast `*_resiliency`) |
| | 548-611 | `assess`: `decision_time_utc`, `data_as_of_utc`, `data_as_of_basis`, `data_content_latest_utc` (593-596) |
| `src/lar_ofi/evaluation.py` | 1-21 | opis metodologii |
| | 98-172 | `mcnemar_exact_p`, `non_overlapping`, `_n_overlapping`, `_paired`, `_after_costs` |
| | 178-252 | `_segment_summary`: cztery sekcje wyniku, wniosek tylko z segmentu niezależnego, Bonferroni (208) |
| | 255-296 | `evaluate`: segment TEST przestaje być niezależny przy zmianie konfiguracji (278-283) |
| | 304-354 | raport Markdown w nowej strukturze |
| `src/lar_ofi/observations.py` | 36-99, 102-123 | `_prepare` z oknem i `protocol_version`; `_check_window` |
| | 139-163 | import zbiorczy przekazuje okna |
| | 219-254 | szablon: procedura, typ pomiaru, warunek UNKNOWN, potrzebne dane ilościowe, okno |
| | 264-291 | `build_engine_input(decision_time, cfg)`, interwał decyzyjny MICRO |
| `src/lar_ofi/registry.py` | 26-28, 57-64, 242-376 | grupa `VISUAL_LIQUIDITY_CHANGE`; `FieldSpec.protocol/requires_window`; `OBS-PROTOCOL-2` |
| `src/lar_ofi/intake.py` | 101-109, 170-185, 276-283 | `analysis_timeframe` musi być MICRO; `live_feed_confirmed`; `view_settings` |
| `src/lar_ofi/db.py` | 9-13, 44-45, 63-65, 72-74, 111-124, 160-170 | schemat v2; `SchemaError` dla dziennika v1 |
| `src/lar_ofi/setups.py` | 140-143, 212-215 | teksty C-4/F-4: jakościowe porównanie, nie resiliency |
| `src/lar_ofi/report.py` | 42-45, 64-66, 105-108 | pytanie 6; `decision_time`/`data_as_of` w raporcie |
| `src/lar_ofi/timeutil.py` | 60-72 | `TIMEFRAME_SECONDS`, `floor_bar`, `floor_minute` (świece wyrównane do UTC) |
| `src/lar_ofi/config.py` | 53-59 | walidacja nowych opcji |
| `src/lar_ofi/default_config.toml` | 16-19, 26-33, 60-67, 74-77 | `micro_decision`, `require_latest_closed_bar`, `require_update_evidence`, `max_decision_to_record_seconds`, `alpha` |
| `tests/test_faza5.py` | nowy | 42 przypadki regresyjne |
| `tests/test_cli.py` | całość | integracja CLI, w tym symulowany zegar |
| `tests/conftest.py`, `tests/test_critical.py`, `tests/test_components.py`, `tests/test_setups.py` | — | dostosowanie do schematu v2 (opis w `FAZA_5_TESTY.md`) |
| `scripts/gen_protocol_doc.py`, `PROTOKOL_OBSERWACJI.md` | nowe | protokół generowany z rejestru |
| `scripts/demo_synthetic.py`, `examples/*`, `README.md`, `SPEC_STRATEGII.md` | — | aktualizacja do v2 |
| `RAPORT_DLA_AUDYTORA.md`, `TEST_REPORT.md` | linia 3 | oznaczone jako historyczne (stan po fazie 4) |

## 3. Wyniki testów

* Python 3.13.16: **115 passed**, 0 failed, 0 skipped. Python 3.11.17: **115 passed**.
* Integracja CLI (`tests/test_cli.py`): 4 passed; test dymny zainstalowanego `lar-ofi` w osobnych
  procesach: zapis `RECORDED` dla świeżych danych, `NOT_RECORDED`/`LATE_RECORDING` przy przekroczeniu limitu.
* `pyflakes`: bez uwag. Demo syntetyczne: wykonane, łańcuch dziennika poprawny.
* Oba błędy P0 odtworzone na kodzie sprzed poprawek (wyjście w `FAZA_5_TESTY.md`).
* Dane syntetyczne **nie są** dowodem skuteczności; nie raportuję żadnej trafności.

## 4. Ograniczenia, których nie udało się usunąć

1. **Powtarzalność odczytów nie jest zmierzona.** Procedury i okna ograniczają dowolność, ale zgodność
   między obserwatorami (np. dwóch osób na tych samych screenshotach) wymaga badania na rzeczywistych
   obrazach. THIN/THICK, REPLENISHED/NOT_REPLENISHED i likwidacje pozostają ocenami jakościowymi.
2. **Wykonalność ręcznego procesu:** domyślnie od najnowszego użytego screenshotu do zapisu może minąć
   ≤ 120 s, a screenshoty 30M/5M muszą zawierać ostatnie zamknięcie. Ręczne wpisanie pól w tym czasie jest
   trudne; spodziewana przewaga WAIT/`NOT_RECORDED`. Nie luzowałem polityk — to decyzja użytkownika.
3. **Zależność szeregowa** poza horyzontem (wspólny stan 30M, klastrowanie zmienności) nie jest
   modelowana; McNemar zakłada niezależne pary, przerzedzenie usuwa tylko nakładające się okna.
4. **Niedopasowanie skal:** warunki 30M (≥ 2 zamknięcia) a horyzont 5/15 min — przeanalizowane, nie
   zmienione bez danych (zadanie zabrania zmiany progów pod liczbę sygnałów).
5. **Wyrównanie świec do UTC** (`floor_bar`) to założenie — należy potwierdzić, że OpenMarket/Bybit
   wyrównują 30M i 5M do 00:00 UTC (dla 30M/5M jest to standard, dla 4H reguła nie jest stosowana).
6. **`live_feed_confirmed`** to oświadczenie użytkownika — nie jest weryfikowalne przez system; jest
   zapisywane i ujawniane w raporcie (flagi screenshotu).
7. **Rynek świec** jest deklaracją użytkownika lub kolumną CSV; system nie weryfikuje, że ceny w pliku
   rzeczywiście pochodzą z deklarowanego rynku (brak połączeń sieciowych z założenia).
8. **Dziennik v1** nie jest migrowany — świadomie, bo jego znaczniki czasu powstały z wadliwą regułą.
9. Ograniczenia z fazy 4 pozostają aktualne (`RAPORT_DLA_AUDYTORA.md` §15), w szczególności: brak
   uruchomienia na rzeczywistych screenshotach, weryfikacja publikacji tylko na poziomie streszczeń.

## 5. Czego nie zrobiłem

* Nie zmieniłem progów strategii, horyzontów ani polityk użytkownika (poza dodaniem jawnie opisanych
  reguł poprawności i ograniczenia inżynierskiego 30 s między decyzją a zapisem).
* Nie zmieniałem niepowiązanych modułów (L2 bez zmian funkcjonalnych).
* Nie dodałem kodu składania zleceń — taka funkcjonalność nie istnieje w projekcie.
* Nie mergowałem zmian.
