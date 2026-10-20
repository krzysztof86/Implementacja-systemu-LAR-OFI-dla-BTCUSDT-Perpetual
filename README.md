# LAR-OFI — półautomatyczna analiza BTCUSDT Perpetual (Bybit)

**L**iquidity, **A**ggression, **R**esiliency & **O**rder **F**low **I**mbalance — nazwa projektowa.
Narzędzie do zapisu obserwacji z wykresów OpenMarket, deterministycznej oceny dwóch setupów
(CONTINUATION, FAILED_AUCTION), generowania decyzji **LONG / SHORT / WAIT** z dowodami oraz
niezmiennego dziennika prognoz z rozliczeniem i ewaluacją.

* **Nie składa zleceń.** Nie łączy się z giełdą ani z API OpenMarket.
* **Nie podaje prawdopodobieństw** (`NOT_CALIBRATED`) i nie deklaruje przewagi statystycznej.
* Nie wymaga płatnego API; działa lokalnie (Python ≥ 3.11, tylko biblioteka standardowa).

Dokumenty: [`FAZA_0_AUDYT.md`](FAZA_0_AUDYT.md) · [`SPEC_STRATEGII.md`](SPEC_STRATEGII.md) ·
[`RESEARCH_EVIDENCE.md`](RESEARCH_EVIDENCE.md) · [`PROTOKOL_OBSERWACJI.md`](PROTOKOL_OBSERWACJI.md) ·
[`TEST_REPORT.md`](TEST_REPORT.md) · [`RAPORT_DLA_AUDYTORA.md`](RAPORT_DLA_AUDYTORA.md)

Faza 5 (poprawki po audycie): [`FAZA_5_AUDYT_POPRAWKI.md`](FAZA_5_AUDYT_POPRAWKI.md) ·
[`FAZA_5_TESTY.md`](FAZA_5_TESTY.md) · [`FAZA_5_RAPORT_DLA_AUDYTORA.md`](FAZA_5_RAPORT_DLA_AUDYTORA.md).
Dziennik ma schemat v2; katalog danych utworzony wersją sprzed fazy 5 nie jest otwierany (użyj nowego
`--data-dir`).

## Instalacja

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q                       # 114 testów
lar-ofi init                    # tworzy ./lar_ofi_data/journal.sqlite
```

Katalog danych: `--data-dir` lub zmienna `LAR_OFI_HOME` (domyślnie `./lar_ofi_data`).
Własna konfiguracja: `--config my.toml` (wzór: `examples/user_config_template.toml`).

## Cykl pracy (MODE A — screenshoty)

```bash
# 1. zrób screenshoty (patrz SPEC §8), wypełnij manifest wg examples/manifest_template.json
lar-ofi import ./sesja/manifest.json                 # -> dataset_id
lar-ofi template <dataset_id> --out obs.json         # szablon pól dla każdego screenshotu
#    uzupełnij "value" wg PROTOKOL_OBSERWACJI.md (lub "readability": "UNREADABLE");
#    pola z oknem: window_start_utc / window_end_utc; porównania heatmap: "compared_with"
lar-ofi observe-file <dataset_id> obs.json
lar-ofi analyze <dataset_id> [--decision-time ...]   # raport JSON + Markdown (bez zapisu w dzienniku)
lar-ofi predict <dataset_id>                         # zapis prognozy; najpóźniej 120 s po najnowszym screenshocie
# 2. po upływie horyzontu: pobierz świece 1m BTCUSDT (własne źródło), CSV: open_time_utc,open,high,low,close
lar-ofi import-bars bybit_1m.csv --source user_csv_1m \
    --instrument BTCUSDT --exchange Bybit --contract-type USDT_PERPETUAL
lar-ofi resolve
lar-ofi evaluate
lar-ofi verify-journal
```

Pozostałe: `observe` (pojedyncza obserwacja), `confirm` (potwierdzenie/korekta), `show`,
`l2-status`, `vision` (tylko z jawnie skonfigurowanym backendem).

## Demo na danych syntetycznych

```bash
python scripts/demo_synthetic.py /tmp/lar_demo
```

Dane demo są wymyślone (obrazy 1×1 px, wymyślone świece) i **nie są dowodem skuteczności**.

## Struktura

```
src/lar_ofi/
  default_config.toml  progi (nieskalibrowane), polityki, brak domyślnych kosztów
  registry.py          wskaźniki OpenMarket i słownik obserwacji
  intake.py            manifest, walidacja, import screenshotów
  observations.py      obserwacje (append-only), szablon, wejście silnika
  engine.py            stan rynku: świeżość, synchronizacja, konflikty, grupy źródeł
  setups.py            CONTINUATION i FAILED_AUCTION (LONG/SHORT)
  decision.py          reguły D1–D5 → LONG/SHORT/WAIT
  report.py            raport JSON/Markdown
  journal.py           dziennik prognoz, świece, rozliczenie
  evaluation.py        ewaluacja chronologiczna, baseline'y, koszty
  l2/                  MODE B: OFI, queue imbalance, price impact, replenishment (wyłączone)
  vision.py            interfejs opcjonalnego backendu vision
tests/                 71 testów, fixture'y syntetyczne
```
