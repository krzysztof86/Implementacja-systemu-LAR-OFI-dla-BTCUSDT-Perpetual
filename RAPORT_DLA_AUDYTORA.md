# RAPORT DLA AUDYTORA — LAR-OFI MVP

> **Dokument historyczny — stan po fazie 4.** Poprawki po audycie i aktualne wyniki: `FAZA_5_RAPORT_DLA_AUDYTORA.md`.

Data: 2026-10-20. Gałąź: `ccr-c24d3880-0mfxmy`. Silnik: `lar-ofi-engine/1`.

Dokumenty do kontroli: `SPEC_STRATEGII.md`, `RESEARCH_EVIDENCE.md`, `TEST_REPORT.md`,
`FAZA_0_AUDYT.md`, ten plik. Kod: `src/lar_ofi/`. Testy: `tests/`.

---

## 1. Co faktycznie zaimplementowałem

| Komponent (sekcja 8 zadania) | Stan | Moduł |
|---|---|---|
| A. Data Intake — import screenshotów, walidacja manifestu, rejestr wskaźników/interwałów, kontrola czasu, instrumentu, giełdy, typu kontraktu, platformy, sygnatury pliku, duplikatów | **działa**, testowane | `intake.py`, `registry.py` |
| B. Observation Extractor — słownik pól, ręczne wprowadzanie (pojedyncze i z szablonu), korekty append-only z historią, powiązanie z screenshotem, czytelność CLEAR/UNCERTAIN/UNREADABLE, interfejs vision z wymogiem potwierdzenia | **działa** (vision: tylko interfejs, brak wbudowanego backendu) | `observations.py`, `vision.py` |
| C. Market State Engine — świeżość, synchronizacja, dane z przyszłości, konflikty, grupy źródeł, stan aukcji, agresja i jej skuteczność, płynność, odbudowa, OI, likwidacje | **działa**, deterministyczny | `engine.py` |
| D. Setup Detector — CONTINUATION i FAILED_AUCTION, LONG i SHORT, stany NONE/CANDIDATE_*/CONFIRMED_*/INVALIDATED/WAIT | **działa** | `setups.py` |
| E. Decision Report — JSON + Markdown, wszystkie wymagane pola, odpowiedzi na 11 pytań, linki do dowodów z SHA-256 | **działa** | `decision.py`, `report.py` |
| F. Prediction Journal — niezmienność (triggery SQLite), łańcuch SHA-256, zamrożona reguła rozliczenia, ochrona przed spóźnionym zapisem, rozliczenie na świecach 1m użytkownika, baseline'y | **działa** | `journal.py` |
| Pomiar jakości (sekcja 9) — liczności, LONG/SHORT/WAIT, trafność ogółem / wg setupu / wg stanu rynku / wg tagu reżimu, coverage, konflikty, braki danych, koszty i MDD (tylko z modelem kosztów), baseline'y, podział chronologiczny, rejestr uruchomień | **działa** | `evaluation.py` |
| MODE B (L2) — rekonstrukcja arkusza snapshot+delta z walidacją sekwencji, OFI, queue imbalance, price impact, czas odbudowy; bramka `l2.enabled` | **zaimplementowane i przetestowane na danych syntetycznych; wyłączone domyślnie; brak adaptera do rzeczywistego strumienia Bybit** | `l2/` |
| CLI | **działa** | `cli.py` |

Brak jakiegokolwiek kodu składania zleceń, klienta API giełdy czy połączeń sieciowych.

## 2. Pliki utworzone i zmienione

Repozytorium było puste — **wszystkie pliki są nowe**, żaden istniejący plik nie został zmieniony.

```
.gitignore  pyproject.toml  README.md
FAZA_0_AUDYT.md  SPEC_STRATEGII.md  RESEARCH_EVIDENCE.md  TEST_REPORT.md  RAPORT_DLA_AUDYTORA.md
src/lar_ofi/{__init__,__main__,cli,config,db,decision,engine,enums,evaluation,intake,journal,
             observations,registry,report,setups,timeutil,vision}.py
src/lar_ofi/default_config.toml
src/lar_ofi/l2/{__init__,book,metrics}.py
tests/{conftest,test_critical,test_setups,test_components,test_cli}.py
scripts/demo_synthetic.py
examples/{manifest_template.json,user_config_template.toml}
```

## 3. Obowiązujące reguły tradingowe

Pełna definicja: `SPEC_STRATEGII.md` §5–§7. Skrót:

* **CONTINUATION LONG** (SHORT lustrzanie): trigger = 30M cena ABOVE poprzedniego VA; candidate = agresja BUY
  (footprint+CVD jako jedna grupa); confirmed = dodatkowo ≥ N zamkniętych barów 30M poza VA i brak powrotu,
  agresja skuteczna (ADVANCED), przeciwna strona (ask) **nie** odbudowała się (2 heatmapy), OI nie spada;
  unieważnienie = ostatni zamknięty bar 30M z powrotem w VA albo agresja BUY bez ruchu ceny.
* **FAILED_AUCTION SHORT** (LONG lustrzanie): trigger = naruszenie UP; candidate = agresja BUY przy ekstremum
  i brak dalszego ruchu (STALLED/REVERSED); confirmed = dodatkowo powrót zamknięciem 30M do VA i cena INSIDE,
  płynność ask przy ekstremum **odbudowana** (2 heatmapy); unieważnienie = akceptacja powyżej (≥ N barów)
  albo agresja przy ekstremum skuteczna.
* **Decyzja**: D1 problemy danych → WAIT; D2 konflikt → WAIT; D3 brak CONFIRMED → WAIT; D4 setupy w
  przeciwnych kierunkach → WAIT; D5 kierunek setupu CONFIRMED. Bez głosowania, bez wag.
* OI, likwidacje, Absorption, AVWAP, 4H — wyłącznie kontekst (HYPOTHESIS), poza C-5 (OI nie spada) w CONTINUATION.

## 4. Co opiera się na badaniach, a co jest hipotezą projektu

| Element | Podstawa |
|---|---|
| Definicje OFI, queue imbalance, model ΔP = β·OFI (MODE B) | Cont et al. 2014; Gould & Bonart 2016 — **definicje z publikacji** (wzór OFI oznaczony [PK], wymaga sprawdzenia w pełnym tekście) |
| „Agresja skuteczna / nieskuteczna” (C-3, C-X2, F-2, F-X2) | **hipoteza projektu**, inspirowana zależnością wpływu przepływu od głębokości (Cont et al.); nie jest OFI |
| Odbudowa płynności z dwóch screenshotów (C-4, F-4) | **hipoteza projektu**, inspirowana pojęciem resiliency (Large 2007); nie jest metodą Large'a |
| Value area, akceptacja, N = 2 bary 30M | **hipoteza projektu** (teoria aukcji / Market Profile — spoza listy publikacji) |
| OI i likwidacje | **hipoteza projektu**, brak źródła w zestawie |
| Footprint + CVD jako jedna grupa; baseline'y; chronologia; jawność uruchomień; koszty tylko od użytkownika | **kontrole metodologiczne** wynikające z Schmalz 2026 i Bieganowski & Ślepaczuk 2026 |

**Ograniczenie weryfikacji źródeł:** pełne teksty publikacji nie były dostępne z kontenera (DNS); twierdzenia
zweryfikowano na poziomie streszczeń i stron indeksujących. Szczegóły i znaczniki [ABS]/[SEC]/[PK]:
`RESEARCH_EVIDENCE.md` §0.

## 5. Dane wymagane do poszczególnych decyzji

| Stan | Minimalne dane |
|---|---|
| CONTINUATION CANDIDATE | 30M TPO/SVP (pozycja względem VA) + agresja (footprint lub CVD) |
| CONTINUATION CONFIRMED → LONG/SHORT | + `closed_bars_outside_value`, `returned_inside_value` (30M), `price_response_to_aggression` (footprint), **2 heatmapy** 5M/1M z porównaniem (`compared_with`), Agg. OI |
| FAILED_AUCTION CANDIDATE | 30M `violation_side` + footprint: `aggression_at_extreme`, `price_response_at_extreme` |
| FAILED_AUCTION CONFIRMED → SHORT/LONG | + `returned_inside_value`, pozycja INSIDE (30M), **2 heatmapy** z porównaniem |
| Każda decyzja | znaczniki czasu (ze strefą), świeżość wg polityki, synchronizacja, brak konfliktów |
| Rozliczenie | CSV świec 1m od użytkownika + `neutral_band_bps` lub pełny model kosztów |
| Twierdzenia o rentowności | pełny model kosztów użytkownika (fee wejścia/wyjścia, spread, poślizg; funding opcjonalnie) |

Macierz wskaźników i układ 4–6 screenshotów przy limicie 3 wskaźników: `SPEC_STRATEGII.md` §8.

## 6. Ograniczenia analizy screenshotów

* Brak event-level danych: nie da się odtworzyć OFI, kolejek, anulowań, rzeczywistej szybkości
  replenishment ani pełnej sekwencji zdarzeń — dlatego te pola są **zakazane** w MODE A.
* Odczyty THIN/THICK, ADVANCED/STALLED, RISING/FLAT są **subiektywne**; zgodność między osobami
  odczytującymi nie została zmierzona.
* Wskaźniki „Agg.” agregują wiele giełd; egzekucja dotyczy Bybit — rozbieżność źródła danych i miejsca
  egzekucji. Konfiguracja źródeł jest tylko deklaracją w manifeście (brak weryfikacji).
* Heatmapa pokazuje widoczną płynność, która może być anulowana (spoofing nie jest wykrywalny).
* Rozdzielczość czasowa = moment wykonania screenshotu; odbudowa mierzona jakościowo między dwoma obrazami.
* Algorytm wskaźnika Absorption jest nieznany — tylko kontekst pomocniczy.
* Odczyty liczbowe (VAH/VAL/cena) są opcjonalne i służą tylko do kontroli spójności.

## 7. Jak działają dwa setupy

Każdy setup ma wariant LONG i SHORT ocenianie niezależnie w logice trójwartościowej (TRUE/FALSE/UNKNOWN).
Trigger określa, czy setup w ogóle dotyczy sytuacji; warunki candidate dają CANDIDATE; komplet warunków
confirmation daje CONFIRMED; dowolny warunek unieważnienia daje INVALIDATED; brakujące wejścia dają WAIT.
Opcjonalny stan poprzedni (`--previous-dataset`) pozwala oznaczyć INVALIDATED, gdy wcześniejszy
CANDIDATE/CONFIRMED stracił trigger. Raport pokazuje każdy warunek, jego status i odczyt, z którego wynika.
Szczegóły i tabele: `SPEC_STRATEGII.md` §5.

## 8. Co powoduje WAIT

Lista zbiorcza w `SPEC_STRATEGII.md` §7: brak danych / obserwacji; brak znacznika czasu na screenshocie
niosącym dane; nieaktualność (polityka `block`); opóźnienie danych wykresu; brak synchronizacji;
konflikty odczytów lub pól; brak potwierdzenia (w tym odbudowa przy jednym screenshocie); unieważnienie;
setupy w przeciwnych kierunkach. CANDIDATE zawsze daje WAIT z warunkiem potwierdzenia.

## 9. Uruchomione testy

* `python3 -m pytest -v` na Python **3.13.16** i `python3.11 -m pytest -q` na Python **3.11.17**
  (pytest 9.1.1) — wynik w `TEST_REPORT.md` (pełne wyjście).
* `pyflakes src tests scripts` — bez uwag.
* `scripts/demo_synthetic.py` — pełny cykl import → obserwacje → raport → dziennik → świece → rozliczenie
  → ewaluacja → weryfikacja łańcucha (OK). Dane demo są syntetyczne.
* Instalacja `pip install -e ".[dev]"` w czystym venv + `lar-ofi init` i `lar-ofi l2-status` — działa.

## 10. Które testy przeszły, a które nie

**71/71 przeszło** na obu wersjach Pythona; 0 pominiętych. Wszystkie 14 testów krytycznych (38 przypadków
testowych) przechodzą — mapowanie w `TEST_REPORT.md` §1.

Błędy wykryte i naprawione w trakcie pracy (ujawniam dla kompletności):
1. Fixture świec miał `close > high` — walidator OHLC poprawnie odrzucił plik; poprawiono fixture.
2. `evaluation.py`: błędny klucz `recorded` przy podziale chronologicznym (KeyError) — poprawiono na `recorded_at`.
3. Testy CLI zakładały czasy z przyszłości względem zegara kontenera — import poprawnie je odrzucał
   (`CAPTURED_IN_FUTURE`); fixture CLI przeniesiono w przeszłość.
4. Zmiana projektowa: pierwotnie screenshot **bez obserwacji** (np. nieużyta wcześniejsza heatmapa) mógł
   zablokować decyzję przez brak synchronizacji. Teraz blokują tylko screenshoty niosące obserwacje;
   pozostałe są raportowane. Zmiana opisana w SPEC §7.

## 11. Czego nie zaimplementowałem i dlaczego

| Pozycja | Powód |
|---|---|
| Wbudowany backend vision | brak potwierdzonego, darmowego backendu; zadanie zabrania zakładania płatnego API. Jest interfejs + wymóg potwierdzenia. |
| Adapter rzeczywistego strumienia L2 Bybit (WebSocket) | brak potwierdzonego dostępu do danych L2; reguła sekwencji w `l2/book.py` jest generyczna i musi zostać sprawdzona z dokumentacją giełdy przed użyciem |
| Estymator Hawkesa Large'a | poza zakresem MVP; zamiast niego jawnie oznaczona miara projektowa |
| Warstwy D (spot vs perp) i E (ADX/ATR/GEX/skew) | zadanie: uruchamiać dopiero po potwierdzeniu dostępności i porównywalności danych; zarejestrowane, ignorowane przez silnik |
| Kalibracja progów / prawdopodobieństw | brak niezależnych danych; `NOT_CALIBRATED` |
| Pobieranie świec z Bybit | brak połączeń sieciowych z założenia; użytkownik dostarcza CSV ze wskazanym źródłem |
| Domyślne stawki kosztów Bybit | zakaz wpisywania fikcyjnych stawek |
| Automatyczny łańcuch stanów między kolejnymi zestawami | tylko ręczne `--previous-dataset` |
| Interfejs graficzny | poza zakresem; CLI + raporty Markdown |

## 12. Jak uruchomić projekt

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
python -m pytest -v
lar-ofi init
```

## 13. Pierwszy rzeczywisty cykl analizy

1. Ustal i zapisz w `my_config.toml` (przed zbieraniem wyników!): `evaluation.neutral_band_bps` lub
   pełny `[costs]` ze swojego konta; opcjonalnie `evaluation.test_start_utc`. Przejrzyj polityki świeżości.
2. W OpenMarket przygotuj workspace'y wg `SPEC_STRATEGII.md` §8. Zrób screenshot heatmapy 5M,
   po kilku minutach zestaw: 30M (TPO+SVP+AVWAP), heatmapa 5M ponownie, 5M (Footprint+OI+CVD),
   1M (Liquidations+Absorption), opcjonalnie 4H. Zanotuj czasy UTC wykonania i ostatniej aktualizacji.
3. Wypełnij manifest (wzór `examples/manifest_template.json`, pole `data_source_config`!) →
   `lar-ofi --config my_config.toml import manifest.json`.
4. `lar-ofi template <id> --out obs.json` → wpisz wartości; nieczytelne oznacz `"readability": "UNREADABLE"`;
   dla odbudowy ustaw `compared_with` na wcześniejszą heatmapę → `lar-ofi observe-file <id> obs.json`.
5. **Szybko** (domyślnie: screenshot 1M ≤ 120 s, 5M ≤ 600 s w chwili zapisu) uruchom
   `lar-ofi --config my_config.toml predict <id>`. Przeczytaj raport `.md`.
6. Po ≥ 15 min pobierz świece 1m BTCUSDT z wybranego źródła do CSV (`open_time_utc,open,high,low,close`)
   → `lar-ofi import-bars plik.csv --source user_csv_1m` → `lar-ofi resolve`.
7. Po zebraniu próby: `lar-ofi evaluate`; `lar-ofi verify-journal`. Raportuj **wszystkie** uruchomienia ewaluacji.

## 14. Parametry wymagające kalibracji (wszystkie obecnie NIESKALIBROWANE)

| Parametr | Domyślnie | Charakter |
|---|---|---|
| `thresholds.acceptance_min_closed_bars_30m` | 2 | założenie projektu |
| `thresholds.require_resiliency_for_confirmation` | true | wybór projektowy |
| `thresholds.resiliency_max_gap_seconds` | 900 | polityka |
| `freshness.max_age_seconds` (1M/5M/30M/4H) | 120/600/2700/21600 | polityka użytkownika |
| `freshness.max_update_lag_seconds` | 120 | polityka |
| `sync.micro_max_skew_seconds` / `auction_max_skew_seconds` | 180 / 900 | polityka |
| `prediction.max_record_delay_seconds` | 120 | kontrola anty-lookahead |
| `evaluation.neutral_band_bps` | brak | musi ustawić użytkownik |
| `evaluation.min_sample_for_any_claim` | 100 | polityka |
| koszty `[costs]` | brak | parametry konta użytkownika |
| MODE B: `interval_s`, `replenish_fraction`, `replenish_max_wait_s` | 10 s / brak / brak | nieskalibrowane |

Kalibracja tylko na segmencie DEVELOPMENT; segment TEST (`test_start_utc`) bez zmian konfiguracji —
system ostrzega `CONFIG_CHANGED_DURING_TEST`.

## 15. Zagrożenia prowadzące do błędnych prognoz

1. **Brak dowodu przewagi**: reguły to hipotezy; publikacje dotyczą innych rynków/horyzontów (sekundy,
   następny tick), a Schmalz pokazuje niestabilność OFI na BTC i siłę prostego AR(1).
2. **Subiektywność odczytów** i błąd potwierdzenia — ta sama osoba odczytuje i oczekuje wyniku.
   Rekomendacja: odczyt przed analizą kierunku, ewentualnie druga osoba.
3. **Opóźnienie**: ręczne wprowadzanie zajmuje czas; przy ścisłej polityce większość decyzji to WAIT,
   przy luźnej — decyzje na nieaktualnych danych.
4. **Rozbieżność źródeł**: dane „Agg.” vs egzekucja na Bybit; ceny rozliczenia z CSV użytkownika
   (open świecy ≠ cena wykonalna; brak spreadu w cenie).
5. **Mała próba / wielokrotne testowanie**: hit rate na kilkudziesięciu prognozach jest szumem;
   wiele uruchomień ewaluacji = ryzyko wyboru najlepszego wyniku (rejestr uruchomień to ujawnia, ale nie
   zapobiega).
6. **Nakładające się prognozy** w symulacji kosztów są sumowane addytywnie — MDD jest przybliżeniem.
7. **Funding** niemodelowany, jeśli użytkownik nie poda czasów i kosztu.
8. **Reżimy** (news, flash crash, niska płynność weekendowa) nie są wykrywane — warstwa E wyłączona.
9. **Spoofing / anulowania** niewidoczne na screenshotach — „odbudowa” może być pozorna.
10. **Wzory MODE B** oznaczone [PK] wymagają porównania z pełnym tekstem publikacji, a reguła sekwencji
    — z dokumentacją Bybit, zanim zostaną użyte na rzeczywistych danych.
11. **Dane syntetyczne**: wszystkie testy i demo używają danych wymyślonych — **system nie był jeszcze
    uruchomiony na ani jednym rzeczywistym screenshocie**.
