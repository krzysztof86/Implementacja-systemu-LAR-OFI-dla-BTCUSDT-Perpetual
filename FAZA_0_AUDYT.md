# FAZA 0 — Audyt repozytorium i środowiska

Data audytu: 2026-10-20 (UTC). Gałąź robocza: `ccr-c24d3880-0mfxmy`.

## 1. Stan repozytorium

| Element | Wynik |
|---|---|
| Commity | **brak** (`git log`: „your current branch does not have any commits yet”) |
| Pliki śledzone / nieśledzone | **brak** (poza katalogiem `.git`) |
| Gałęzie zdalne | `git ls-remote origin` nie zwrócił żadnych referencji — zdalne repozytorium jest puste |
| Istniejący kod do ponownego wykorzystania | **brak** |
| Zależności zadeklarowane | **brak** |

Wniosek: repozytorium jest puste. Zgodnie z sekcją 8 zadania tworzę samodzielny projekt
Python 3.11+, z SQLite jako lokalnym rejestrem, pytest jako frameworkiem testów i lokalnym CLI.
Nie ma czego nadpisywać ani usuwać.

## 2. Środowisko wykonawcze (kontener, w którym powstał projekt)

| Element | Wynik |
|---|---|
| System | Linux x86_64 |
| Python domyślny | 3.13.16 (`/usr/bin/python3`) |
| Dostępne również | `python3.11`, `python3.12` |
| SQLite (moduł `sqlite3`) | 3.45.1 |
| `tomllib`, `zoneinfo` (stdlib) | dostępne; strefa `Europe/Warsaw` rozwiązywana z systemowej bazy tz |
| pytest | nie był zainstalowany — doinstalowano `pytest 9.1.1` (`pip install pytest`) |
| Pillow, PyYAML | obecne w systemie, **nie są używane** przez projekt (brak twardych zależności) |
| Dostęp do sieci | przez proxy; strony arxiv.org / ssrn.com / doi.org **nie były osiągalne** narzędziem pobierania stron (błąd DNS). Weryfikacja publikacji wykonana przez wyszukiwarkę (streszczenia, strony indeksujące) — szczegóły i ograniczenia w `RESEARCH_EVIDENCE.md`. |

## 3. Dostępność danych i usług (stan na dzień audytu)

| Zasób | Status | Konsekwencja projektowa |
|---|---|---|
| Screenshoty OpenMarket | dostarczane ręcznie przez użytkownika | MODE A — tryb podstawowy |
| API OpenMarket | **NIEPOTWIERDZONY** | brak integracji; nie zakładam istnienia API |
| Surowe dane L2 (event-level) | **NIEPOTWIERDZONY** | MODE B przygotowany jako interfejs, **domyślnie wyłączony** |
| Płatne API vision | **brak / niepotwierdzone** | ekstrakcja ręczna; backend vision tylko po jawnej konfiguracji |
| Parametry kosztów konta Bybit | **nie dostarczono** | brak domyślnych stawek; bez nich system nie formułuje twierdzeń o rentowności |
| Dane cenowe do rozliczania prognoz | **nie dostarczono** | import CSV świec 1m dostarczonych przez użytkownika (źródło jawnie etykietowane) |

## 4. Decyzje wynikające z audytu

1. Projekt bez zależności runtime poza biblioteką standardową Pythona (≥3.11: `tomllib`, `zoneinfo`,
   `sqlite3`, `hashlib`, `argparse`). Jedyna zależność deweloperska: `pytest`.
2. Brak jakiegokolwiek modułu składania zleceń i brak klientów API giełd.
3. Wszystkie progi strategii w pliku konfiguracyjnym z flagą `calibrated = false`.
4. Rejestr prognoz w SQLite z wyzwalaczami blokującymi `UPDATE`/`DELETE` i łańcuchem skrótów SHA-256.
5. Moduł L2 (Cont et al., Gould–Bonart, odbudowa płynności) implementowany tylko na strumieniu
   zdarzeń z walidacją ciągłości sekwencji; bez takiego strumienia zwraca błąd `L2DataUnavailable`.
