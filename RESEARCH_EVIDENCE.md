# RESEARCH_EVIDENCE — podstawy naukowe LAR-OFI

LAR-OFI to **nazwa projektowa**, nie istniejąca strategia naukowa. Żaden z autorów poniżej nie
zaproponował reguł CONTINUATION / FAILED_AUCTION opisanych w `SPEC_STRATEGII.md`.
Publikacje dostarczają **mechanizmów** i **definicji miar**; reguły tradingowe są hipotezami projektu.

## 0. Metoda weryfikacji i jej ograniczenia (przeczytaj najpierw)

W środowisku, w którym powstał projekt (2026-10-20), serwery `arxiv.org`, `ssrn.com`, `doi.org`,
`alphaxiv.org`, `ar5iv` **nie były osiągalne** narzędziem pobierania stron (błąd DNS). Pełne teksty
**nie zostały przeczytane w tej sesji**. Weryfikacja została wykonana przez wyszukiwarkę, na podstawie
streszczeń i stron indeksujących (arXiv listing, SSRN listing, RePEc/IDEAS, HAL, ScienceDirect) oraz prac
cytujących. Każde twierdzenie poniżej ma znacznik:

| Znacznik | Znaczenie |
|---|---|
| **[ABS]** | potwierdzone w streszczeniu / na stronie indeksującej publikacji |
| **[SEC]** | pochodzi ze źródła wtórnego (praca cytująca, przegląd, streszczenie serwisu) — nie sprawdzone w oryginale |
| **[PK]** | z mojej wcześniejszej wiedzy o publikacji, **niezweryfikowane w tej sesji** — audytor powinien sprawdzić w pełnym tekście |

Zalecenie dla audytora: porównać wzory oznaczone [PK] (zwłaszcza definicję `e_n` w Cont et al.)
z pełnym tekstem, zanim MODE B zostanie użyty na rzeczywistych danych.

---

## A. Cont, Kukanov, Stoikov — *The Price Impact of Order Book Events*

* Źródło: arXiv:1011.6402 (2010); Journal of Financial Econometrics 12(1), 2014, s. 47–88 [ABS].

**Twierdzenie z publikacji**
* W krótkich przedziałach zmiany ceny są w głównej mierze wyjaśniane przez Order Flow Imbalance (OFI) —
  nierównowagę podaży i popytu na najlepszym bidzie i asku [ABS].
* Relacja OFI → zmiana ceny jest liniowa, a jej nachylenie jest odwrotnie proporcjonalne do głębokości
  rynku [ABS].
* Wynik odporny na sezonowość śróddzienną, stabilny między skalami czasu i spółkami [ABS].
* Model liniowy + argument skalowania implikuje empiryczną relację „pierwiastkową” między wielkością
  zmian ceny a wolumenem, która jest bardziej zaszumiona niż relacja z OFI [ABS].
* OFI omawiane jako miara adverse selection dla zleceń limit [ABS].

**Zakres rynku i danych**
* NYSE TAQ (Trades and Quotes), 50 spółek amerykańskich [ABS].
* Szczegóły: miesiąc kwiecień 2010, przedziały ~10 s, estymacja w oknach 30-minutowych [PK].

**Definicja miary (zaimplementowana w `src/lar_ofi/l2/metrics.py`)** [PK]

```
e_n = 1{Pb_n >= Pb_n-1}·qb_n − 1{Pb_n <= Pb_n-1}·qb_n-1 − 1{Pa_n <= Pa_n-1}·qa_n + 1{Pa_n >= Pa_n-1}·qa_n-1
OFI_k = Σ e_n dla zdarzeń w przedziale k;     ΔP_k = β·OFI_k + ε_k,   β ~ 1/głębokość
```

**Co rzeczywiście wynika z badań**
* Relacja jest głównie **współczesna (kontemporaniczna)**: OFI w przedziale wyjaśnia zmianę ceny w tym
  samym przedziale. Publikacja nie jest dowodem, że OFI prognozuje przyszłe zwroty.
* Wpływ tej samej presji zależy od dostępnej głębokości.

**Jak przekładamy to na BTCUSDT**
* MODE A (screenshoty): używamy wyłącznie **jakościowej idei** — „czy agresja przesuwa cenę?”
  (`aggression_efficiency` = EFFECTIVE / INEFFECTIVE na podstawie `price_response_to_aggression`).
  To **nie jest OFI** i nie jest tak nazywane.
* MODE B (L2): prawdziwe OFI liczone ze strumienia best bid/ask z walidacją ciągłości sekwencji;
  domyślnie wyłączone.

**Co pozostaje hipotezą**
* Że relacja obowiązuje dla agregowanych danych BTCUSDT perpetual i horyzontów 5–15 min.
* Że wizualna ocena „agresja vs ruch ceny” jest użytecznym przybliżeniem tej relacji.

**Czego nie wolno twierdzić**
* Że CVD / delta wolumenu = OFI (OFI wymaga zmian kolejek na best bid/ask, w tym anulowań).
* Że publikacja wykazała przewidywalność 5-minutowych zwrotów BTC.
* Że R² czy β z akcji amerykańskich przenoszą się na BTCUSDT.

---

## B. Gould, Bonart — *Queue Imbalance as a One-Tick-Ahead Price Predictor in a Limit Order Book*

* Źródło: arXiv:1512.03492 (2015) [ABS]; wersja czasopismowa (Market Microstructure and Liquidity, 2016) [SEC — nie potwierdzono dokładnej cytacji].

**Twierdzenie z publikacji**
* Nierównowaga kolejek na najlepszych poziomach ma statystycznie istotny związek z kierunkiem **następnej**
  zmiany mid-price we wszystkich badanych spółkach [ABS].
* Regresja logistyczna znacząco poprawia klasyfikację względem modelu zerowego dla spółek
  „large-tick”, umiarkowanie dla „small-tick”; lokalna regresja logistyczna nieco lepsza, ale
  droższa obliczeniowo [ABS].

**Zakres rynku i danych**: 10 płynnych spółek z Nasdaq [ABS]; źródło danych (LOBSTER) i okres [PK].

**Definicja miary (zaimplementowana w MODE B)**: `I = (q_bid − q_ask) / (q_bid + q_ask)` na najlepszych
poziomach [ABS: znormalizowana różnica w [−1, 1]].

**Co rzeczywiście wynika**: przewidywalność kierunku **jednej następnej zmiany mid-price** na rynku akcji,
silniejsza przy dużym ticku względem ceny.

**Jak przekładamy na BTCUSDT**: wyłącznie w MODE B, na prawdziwych kolejkach. Pole heatmapy
`passive_liquidity_above/below` (THIN/THICK) **nie jest** queue imbalance i nie jest tak nazywane.

**Co pozostaje hipotezą**: czy BTCUSDT na Bybit zachowuje się jak rynek „large-tick” czy „small-tick”
(nie sprawdzono); czy jakakolwiek informacja z QI przetrwa do horyzontu 5 min.

**Czego nie wolno twierdzić**: że QI prognozuje ruch 5M/15M; że wyniki z Nasdaq dotyczą krypto;
że screenshot heatmapy mierzy QI.

---

## C. Jeremy Large — *Measuring the Resiliency of an Electronic Limit Order Book*

* Źródło: Journal of Financial Markets 10(1), 2007, s. 1–25, doi:10.1016/j.finmar.2006.09.001 [ABS].

**Twierdzenie z publikacji**
* Arkusz jest „resilient”, gdy szybko wraca do normalnego kształtu po dużych transakcjach [ABS].
* Zaproponowano funkcję odpowiedzi impulsowej w czasie ciągłym opartą na intensywnościach, mierzącą
  odporność przez skalę czasu i prawdopodobieństwo odbudowy arkusza [ABS].
* Zlecenia i anulowania modelowane jako 10-wymiarowy, wzajemnie wzbudzający się proces Hawkesa [ABS].
* Wyniki raportowane w przeglądach: arkusz odporny w mniej niż ~40% przypadków, a odbudowa trwa ~20 s;
  agresywne zlecenia limit wywoływane głównie przez agresywne zlecenia rynkowe [SEC].

**Zakres danych**: akcje Barclays, LSE SETS, styczeń 2002, 22 dni sesyjne [ABS/SEC].

**Co rzeczywiście wynika**: odporność jest **mierzalna tylko z sekwencji zdarzeń w czasie** i jest
zjawiskiem warunkowym (nie zawsze występuje).

**Jak przekładamy na BTCUSDT**
* MODE A: pola `ask_side_after_consumption` / `bid_side_after_consumption` wymagają **dwóch
  uporządkowanych w czasie** screenshotów heatmapy (`compared_with`, odstęp ≤ `resiliency_max_gap_seconds`).
  Pojedynczy screenshot → UNKNOWN (test krytyczny 8).
* MODE B: `replenishment_times` — **miara projektowa** (czas powrotu głębokości najlepszego poziomu do
  ułamka stanu sprzed transakcji). To **nie jest** estymator Hawkesa Large'a.

**Co pozostaje hipotezą**: że odbudowa widoczna na agregowanej heatmapie odróżnia presję trwałą od
absorbowanej na BTCUSDT; parametry `fraction`, `max_wait_s` są nieskalibrowane.

**Czego nie wolno twierdzić**: że 40% / 20 s dotyczą BTC; że jeden screenshot mierzy odporność;
że nasza miara jest metodą Large'a.

---

## D. Bieganowski, Ślepaczuk — *Explainable Patterns in Cryptocurrency Microstructure*

* Źródło: arXiv:2602.00776 (złożony 31.01.2026), także SSRN 6159346 [ABS].

**Twierdzenie z publikacji**
* Te same, inżynieryjnie zbudowane cechy order book i transakcji mają podobną ważność predykcyjną i
  podobne kształty zależności SHAP dla pięciu aktywów (BTC, LTC, ETC, ENJ, ROSE) mimo różnej płynności
  i zmienności [ABS].
* Model: CatBoost z kierunkowym celem GMADL, walidacja krzyżowa szeregów czasowych [ABS].
* Interpretacja SHAP powiązana z OFI, spreadem i teorią adverse selection [ABS].
* Handlowalność sprawdzana konserwatywnym backtestem taker (top-of-book) i backtestem maker o stałej
  głębokości; analiza flash crash pokazuje rozbieżność taker vs maker zgodną z adverse selection [ABS].
* Streszczenia wtórne: strategie taker „ogólnie zyskowne” w ich backteście, maker mniej spójne; w
  flash crashu maker kumulował stratne longi [SEC — nie zweryfikowano kosztów ani horyzontu].

**Zakres danych**: Binance Futures perpetual, order book + transakcje z częstotliwością 1 s,
1.01.2022 – 12.10.2025 [ABS].

**Co rzeczywiście wynika**: cechy typu OFI / spread niosą informację na horyzoncie **sekund** na
perpetualach Binance; egzekucja maker narażona na adverse selection.

**Jak przekładamy**: uzasadnienie, by w ogóle analizować cechy mikrostruktury perpetual; domyślna
egzekucja w symulacji kosztów = TAKER; ryzyko niewypełnienia maker **nie jest modelowane** i raport to
deklaruje.

**Co pozostaje hipotezą**: że cokolwiek z tego przenosi się na Bybit, na dane agregowane, na
screenshoty i na horyzont 5–15 min.

**Czego nie wolno twierdzić**: że ich wyniki backtestu dowodzą rentowności LAR-OFI; że nasze pola ze
screenshotów to ich cechy.

---

## E. Schmalz — *Order Flow Imbalance and Short-Horizon BTC/USDT Returns: A Signal That Kept Needing More Scrutiny*

* Źródło: SSRN 7227998, Michael Schmalz (Johns Hopkins), datowany 29.07.2026 [ABS].

**Twierdzenie z publikacji** [ABS]
* Testuje, czy OFI (definicja Cont et al.) prognozuje zwroty mid-price BTC/USDT w horyzoncie 1–10 s,
  na L2 odtworzonym ze strumienia diff-depth Binance.US.
* Trzy kolejne rozszerzenia tej samej rejestracji: ~7, ~9 i ~17 dni; walk-forward, Newey–West,
  przedziały bootstrap blokowy; benchmarki: signed trade-flow imbalance i AR(1).
* ~7 dni: istotnie dodatnie R² out-of-sample (ok. 0,17%–1,00%), przetrwało test placebo.
* ~9 dni: wynik zerowy lub ujemny na każdym horyzoncie.
* ~17 dni, po naprawie dwóch błędów potoku danych i dodaniu purge/embargo: ponownie dodatni.
* AR(1) dorównuje lub przewyższa OFI prawie na każdym horyzoncie; trade-flow imbalance nigdy
  samodzielnie istotny; pojedynczy wynik walk-forward należy traktować jako tymczasowy.

**Co rzeczywiście wynika**: efekt OFI na BTC/USDT, jeśli istnieje, jest mały, niestabilny w krótkich
próbach i wrażliwy na błędy potoku danych; prosty baseline może być równie dobry.

**Jak przekładamy na projekt** (kontrola metodologiczna, nie reguła tradingowa)
* Obowiązkowe baseline'y w ewaluacji (`MOMENTUM_SAME_HORIZON`, `ALWAYS_LONG`) na tych samych znacznikach czasu.
* Walidacja ciągłości sekwencji L2 (luki → brak metryk).
* Ujawnianie liczby uruchomień ewaluacji; chronologiczny podział; brak twierdzeń poniżej
  `min_sample_for_any_claim`.
* CVD (przepływ transakcji) nigdy nie jest samodzielnym dowodem.

**Czego nie wolno twierdzić**: że OFI daje przewagę na BTC; że wyniki 1–10 s dotyczą 5–15 min;
że Binance.US = Bybit.

---

## F. Mapa: mechanizm → element systemu → status

| Element systemu | Mechanizm / źródło | Status |
|---|---|---|
| `aggression_efficiency` (agresja vs ruch ceny) | wpływ przepływu zależny od głębokości — Cont et al. | **HIPOTEZA projektu** (jakościowe przybliżenie, nie OFI) |
| Grupa źródeł TRADE_AGGRESSION (footprint + CVD liczone raz) | te same transakcje; Schmalz: trade-flow imbalance nieistotny samodzielnie | reguła **metodologiczna** projektu |
| Odbudowa płynności z 2 screenshotów | resiliency — Large | **HIPOTEZA projektu**; pomiar jakościowy |
| OFI, Queue Imbalance, price impact (MODE B) | Cont et al.; Gould & Bonart | **definicje z publikacji** [PK/ABS]; wyłączone bez danych L2 |
| Replenishment time (MODE B) | koncept resiliency — Large | **miara projektowa**, nie metoda Large'a |
| Akceptacja / odrzucenie poza value area (TPO/profil) | teoria aukcji rynkowej (Market Profile) — **nie** z powyższych publikacji | **HIPOTEZA projektu** |
| OI, likwidacje jako kontekst | brak publikacji w zestawie | **HIPOTEZA projektu** (tylko kontekst, nie warunek) |
| Absorption (wskaźnik OpenMarket) | algorytm nieznany | **pomocniczy, niezweryfikowany** |
| Baseline'y, brak losowego podziału, ujawnianie uruchomień | Schmalz | kontrola metodologiczna |
| Koszty taker domyślnie, brak modelu ryzyka maker | Bieganowski & Ślepaczuk (adverse selection) | kontrola metodologiczna |

## G. Źródła (strony faktycznie zwrócone przez wyszukiwarkę)

* arXiv 1011.6402 — https://arxiv.org/abs/1011.6402 ; HAL: https://hal.sorbonne-universite.fr/hal-00937055 ; RePEc: https://ideas.repec.org/a/oup/jfinec/v12y2013i1p47-88.html
* arXiv 1512.03492 — https://arxiv.org/pdf/1512.03492 ; RePEc: https://ideas.repec.org/p/arx/papers/1512.03492.html
* Large 2007 — https://www.sciencedirect.com/science/article/abs/pii/S1386418106000528 ; RePEc: https://ideas.repec.org/a/eee/finmar/v10y2007i1p1-25.html ; przegląd Hawkes: https://arxiv.org/pdf/1502.04592
* arXiv 2602.00776 — https://arxiv.org/abs/2602.00776 ; SSRN: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6159346
* SSRN 7227998 — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7227998
