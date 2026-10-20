# TEST_REPORT — raport testów LAR-OFI

Raport wygenerowany z **rzeczywistego** uruchomienia `python3 -m pytest -v` w kontenerze projektu.

| Element | Wartość |
|---|---|
| Data uruchomienia (UTC) | 2026-10-20T09:39Z |
| Python 3.13.16, pytest 9.1.1 | **71 passed**, 0 failed, 0 skipped (3.29 s) |
| Python 3.11.17, pytest 9.1.1 | **71 passed**, 0 failed, 0 skipped (3.67 s) |
| Analiza statyczna `pyflakes src tests scripts` | brak uwag |
| Demo end-to-end `scripts/demo_synthetic.py` | wykonane; dziennik zweryfikowany (`verify_journal` = OK) |

> Wszystkie testy działają na **syntetycznych** fixture'ach (obrazy PNG 1×1 px, wymyślone obserwacje i świece). Potwierdzają poprawność reguł i mechaniki, **nie** skuteczność tradingową.

## 1. Testy krytyczne z sekcji 10 zadania

| # | Wymaganie | Testy | Wynik |
|---|---|---|---|
| 1 | Brak screenshotów → WAIT | `test_01_no_screenshots_gives_wait`<br>`test_01b_screenshots_without_observations_give_wait` | **PASSED** (2) |
| 2 | Screenshot z niewłaściwego instrumentu → odrzucenie | `test_02_wrong_instrument_dataset_rejected[instrument-ETHUSDT]`<br>`test_02_wrong_instrument_dataset_rejected[exchange-Binance]`<br>`test_02_wrong_instrument_dataset_rejected[contract_type-SPOT]`<br>`test_02b_screenshot_of_wrong_instrument_rejected` | **PASSED** (4) |
| 3 | Brak timestampu → status niewystarczających danych | `test_03_missing_timestamp_gives_insufficient_data`<br>`test_03b_naive_timestamp_is_rejected_not_guessed` | **PASSED** (2) |
| 4 | Nieaktualne dane → WAIT wg polityki aktualności | `test_04_stale_data_gives_wait_under_block_policy`<br>`test_04b_stale_data_excluded_under_exclude_policy`<br>`test_04c_chart_not_updated_gives_wait`<br>`test_04d_unsynchronised_screenshots_give_wait` | **PASSED** (4) |
| 5 | Sprzeczne informacje → WAIT | `test_05_conflicting_aggression_sources_give_wait`<br>`test_05b_conflicting_readings_across_timeframes_give_wait`<br>`test_05c_price_inconsistent_with_value_area_gives_wait` | **PASSED** (3) |
| 6 | Nieczytelne wartości → UNKNOWN | `test_06_unreadable_values_become_unknown`<br>`test_06b_uncertain_reading_treated_as_unknown_by_default` | **PASSED** (2) |
| 7 | Brak danych L2 → brak obliczeń prawdziwego OFI | `test_07_l2_quantities_cannot_be_entered_from_screenshots[ofi]`<br>`test_07_l2_quantities_cannot_be_entered_from_screenshots[queue_imbalance]`<br>`test_07_l2_quantities_cannot_be_entered_from_screenshots[liquidity_resiliency]`<br>`test_07b_screenshot_mode_reports_no_ofi`<br>`test_07c_l2_metrics_refuse_without_data` | **PASSED** (5) |
| 8 | Pojedynczy snapshot → brak pomiaru odbudowy | `test_08_single_snapshot_cannot_measure_replenishment`<br>`test_08b_comparison_against_non_heatmap_is_not_measurable`<br>`test_08c_comparison_with_later_screenshot_is_not_measurable`<br>`test_08d_l2_single_snapshot_cannot_measure_replenishment` | **PASSED** (4) |
| 9 | Zgodne CVD i footprint → nie podwójne potwierdzenie | `test_09_concordant_cvd_and_footprint_are_one_evidence_group` | **PASSED** (1) |
| 10 | Brak konfiguracji kosztów → brak twierdzeń o rentowności | `test_10_no_cost_config_means_no_profitability_claim`<br>`test_10b_cost_model_only_from_explicit_user_values` | **PASSED** (2) |
| 11 | Zmiana wyniku historycznej prognozy → zablokowana | `test_11_recorded_prediction_and_result_cannot_be_changed`<br>`test_11b_tampering_outside_sqlite_triggers_is_detected` | **PASSED** (2) |
| 12 | Dane z przyszłości → bez wpływu na wcześniejszą decyzję | `test_12_future_screenshots_do_not_affect_earlier_decision`<br>`test_12b_journal_rejects_future_or_late_recording`<br>`test_12c_resolution_entry_is_after_recording_and_baseline_uses_past_only` | **PASSED** (3) |
| 13 | Ponowny import → brak duplikacji | `test_13_reimport_same_dataset_creates_no_duplicates`<br>`test_13b_reimport_price_bars_creates_no_duplicates`<br>`test_13c_duplicate_file_inside_one_dataset_rejected` | **PASSED** (3) |
| 14 | Identyczne wejścia → identyczny wynik | `test_14_identical_inputs_identical_outputs` | **PASSED** (1) |

## 2. Pozostałe testy

### Setupy (lustra LONG/SHORT, przejścia stanów, brak potwierdzenia z samego knota/delty/absorpcji) — `tests/test_setups.py` (12/12 PASSED)

- `test_continuation_short_mirror` — PASSED
- `test_failed_auction_long_mirror` — PASSED
- `test_continuation_candidate_before_acceptance` — PASSED
- `test_mere_violation_of_vah_is_not_confirmation` — PASSED
- `test_absorbed_buying_invalidates_continuation` — PASSED
- `test_previous_candidate_invalidated_when_trigger_lost` — PASSED
- `test_wick_or_delta_or_absorption_alone_never_confirms_failed_auction` — PASSED
- `test_failed_auction_needs_replenishment_from_two_snapshots` — PASSED
- `test_failed_auction_invalidated_by_acceptance` — PASSED
- `test_opposite_live_setups_give_wait` — PASSED
- `test_disabled_layer_observations_are_ignored` — PASSED
- `test_probability_is_never_a_number` — PASSED

### Komponenty (intake, obserwacje, dziennik, ewaluacja, matematyka L2) — `tests/test_components.py` (19/19 PASSED)

- `test_non_image_and_empty_files_rejected` — PASSED
- `test_unknown_indicator_and_bad_timeframe_rejected` — PASSED
- `test_workspace_limit_flagged` — PASSED
- `test_capture_after_import_time_rejected` — PASSED
- `test_field_must_match_indicator_and_timeframe` — PASSED
- `test_correction_supersedes_and_keeps_history` — PASSED
- `test_bulk_entry_is_all_or_nothing` — PASSED
- `test_template_lists_only_applicable_fields` — PASSED
- `test_scoring_bands` — PASSED
- `test_funding_crossing` — PASSED
- `test_bad_bars_rejected_entirely` — PASSED
- `test_wilson_and_mdd` — PASSED
- `test_evaluation_counts_and_disclosure` — PASSED
- `test_chronological_split` — PASSED
- `test_ofi_contribution_cases` — PASSED
- `test_queue_imbalance_and_ofi_sum` — PASSED
- `test_price_impact_fit_recovers_slope` — PASSED
- `test_replay_validates_sequence_and_computes_metrics` — PASSED
- `test_delta_before_snapshot_marks_stream_incomplete` — PASSED

### CLI end-to-end — `tests/test_cli.py` (2/2 PASSED)

- `test_cli_import_observe_analyze` — PASSED
- `test_cli_predict_refuses_stale_screenshots` — PASSED

## 3. Pełny wynik `pytest -v` (Python 3.13)

```
============================= test session starts ==============================
platform linux -- Python 3.13.16, pytest-9.1.1, pluggy-1.7.0 -- /usr/bin/python3
rootdir: /home/user/Implementacja-systemu-LAR-OFI-dla-BTCUSDT-Perpetual
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.15.1
collecting ... collected 71 items

tests/test_cli.py::test_cli_import_observe_analyze PASSED                [  1%]
tests/test_cli.py::test_cli_predict_refuses_stale_screenshots PASSED     [  2%]
tests/test_components.py::test_non_image_and_empty_files_rejected PASSED [  4%]
tests/test_components.py::test_unknown_indicator_and_bad_timeframe_rejected PASSED [  5%]
tests/test_components.py::test_workspace_limit_flagged PASSED            [  7%]
tests/test_components.py::test_capture_after_import_time_rejected PASSED [  8%]
tests/test_components.py::test_field_must_match_indicator_and_timeframe PASSED [  9%]
tests/test_components.py::test_correction_supersedes_and_keeps_history PASSED [ 11%]
tests/test_components.py::test_bulk_entry_is_all_or_nothing PASSED       [ 12%]
tests/test_components.py::test_template_lists_only_applicable_fields PASSED [ 14%]
tests/test_components.py::test_scoring_bands PASSED                      [ 15%]
tests/test_components.py::test_funding_crossing PASSED                   [ 16%]
tests/test_components.py::test_bad_bars_rejected_entirely PASSED         [ 18%]
tests/test_components.py::test_wilson_and_mdd PASSED                     [ 19%]
tests/test_components.py::test_evaluation_counts_and_disclosure PASSED   [ 21%]
tests/test_components.py::test_chronological_split PASSED                [ 22%]
tests/test_components.py::test_ofi_contribution_cases PASSED             [ 23%]
tests/test_components.py::test_queue_imbalance_and_ofi_sum PASSED        [ 25%]
tests/test_components.py::test_price_impact_fit_recovers_slope PASSED    [ 26%]
tests/test_components.py::test_replay_validates_sequence_and_computes_metrics PASSED [ 28%]
tests/test_components.py::test_delta_before_snapshot_marks_stream_incomplete PASSED [ 29%]
tests/test_critical.py::test_01_no_screenshots_gives_wait PASSED         [ 30%]
tests/test_critical.py::test_01b_screenshots_without_observations_give_wait PASSED [ 32%]
tests/test_critical.py::test_02_wrong_instrument_dataset_rejected[instrument-ETHUSDT] PASSED [ 33%]
tests/test_critical.py::test_02_wrong_instrument_dataset_rejected[exchange-Binance] PASSED [ 35%]
tests/test_critical.py::test_02_wrong_instrument_dataset_rejected[contract_type-SPOT] PASSED [ 36%]
tests/test_critical.py::test_02b_screenshot_of_wrong_instrument_rejected PASSED [ 38%]
tests/test_critical.py::test_03_missing_timestamp_gives_insufficient_data PASSED [ 39%]
tests/test_critical.py::test_03b_naive_timestamp_is_rejected_not_guessed PASSED [ 40%]
tests/test_critical.py::test_04_stale_data_gives_wait_under_block_policy PASSED [ 42%]
tests/test_critical.py::test_04b_stale_data_excluded_under_exclude_policy PASSED [ 43%]
tests/test_critical.py::test_04c_chart_not_updated_gives_wait PASSED     [ 45%]
tests/test_critical.py::test_04d_unsynchronised_screenshots_give_wait PASSED [ 46%]
tests/test_critical.py::test_05_conflicting_aggression_sources_give_wait PASSED [ 47%]
tests/test_critical.py::test_05b_conflicting_readings_across_timeframes_give_wait PASSED [ 49%]
tests/test_critical.py::test_05c_price_inconsistent_with_value_area_gives_wait PASSED [ 50%]
tests/test_critical.py::test_06_unreadable_values_become_unknown PASSED  [ 52%]
tests/test_critical.py::test_06b_uncertain_reading_treated_as_unknown_by_default PASSED [ 53%]
tests/test_critical.py::test_07_l2_quantities_cannot_be_entered_from_screenshots[ofi] PASSED [ 54%]
tests/test_critical.py::test_07_l2_quantities_cannot_be_entered_from_screenshots[queue_imbalance] PASSED [ 56%]
tests/test_critical.py::test_07_l2_quantities_cannot_be_entered_from_screenshots[liquidity_resiliency] PASSED [ 57%]
tests/test_critical.py::test_07b_screenshot_mode_reports_no_ofi PASSED   [ 59%]
tests/test_critical.py::test_07c_l2_metrics_refuse_without_data PASSED   [ 60%]
tests/test_critical.py::test_08_single_snapshot_cannot_measure_replenishment PASSED [ 61%]
tests/test_critical.py::test_08b_comparison_against_non_heatmap_is_not_measurable PASSED [ 63%]
tests/test_critical.py::test_08c_comparison_with_later_screenshot_is_not_measurable PASSED [ 64%]
tests/test_critical.py::test_08d_l2_single_snapshot_cannot_measure_replenishment PASSED [ 66%]
tests/test_critical.py::test_09_concordant_cvd_and_footprint_are_one_evidence_group PASSED [ 67%]
tests/test_critical.py::test_10_no_cost_config_means_no_profitability_claim PASSED [ 69%]
tests/test_critical.py::test_10b_cost_model_only_from_explicit_user_values PASSED [ 70%]
tests/test_critical.py::test_11_recorded_prediction_and_result_cannot_be_changed PASSED [ 71%]
tests/test_critical.py::test_11b_tampering_outside_sqlite_triggers_is_detected PASSED [ 73%]
tests/test_critical.py::test_12_future_screenshots_do_not_affect_earlier_decision PASSED [ 74%]
tests/test_critical.py::test_12b_journal_rejects_future_or_late_recording PASSED [ 76%]
tests/test_critical.py::test_12c_resolution_entry_is_after_recording_and_baseline_uses_past_only PASSED [ 77%]
tests/test_critical.py::test_13_reimport_same_dataset_creates_no_duplicates PASSED [ 78%]
tests/test_critical.py::test_13b_reimport_price_bars_creates_no_duplicates PASSED [ 80%]
tests/test_critical.py::test_13c_duplicate_file_inside_one_dataset_rejected PASSED [ 81%]
tests/test_critical.py::test_14_identical_inputs_identical_outputs PASSED [ 83%]
tests/test_setups.py::test_continuation_short_mirror PASSED              [ 84%]
tests/test_setups.py::test_failed_auction_long_mirror PASSED             [ 85%]
tests/test_setups.py::test_continuation_candidate_before_acceptance PASSED [ 87%]
tests/test_setups.py::test_mere_violation_of_vah_is_not_confirmation PASSED [ 88%]
tests/test_setups.py::test_absorbed_buying_invalidates_continuation PASSED [ 90%]
tests/test_setups.py::test_previous_candidate_invalidated_when_trigger_lost PASSED [ 91%]
tests/test_setups.py::test_wick_or_delta_or_absorption_alone_never_confirms_failed_auction PASSED [ 92%]
tests/test_setups.py::test_failed_auction_needs_replenishment_from_two_snapshots PASSED [ 94%]
tests/test_setups.py::test_failed_auction_invalidated_by_acceptance PASSED [ 95%]
tests/test_setups.py::test_opposite_live_setups_give_wait PASSED         [ 97%]
tests/test_setups.py::test_disabled_layer_observations_are_ignored PASSED [ 98%]
tests/test_setups.py::test_probability_is_never_a_number PASSED          [100%]

============================== 71 passed in 3.29s ==============================
```

## 4. Wynik `pytest -q` (Python 3.11)

```
.......................................................................  [100%]
71 passed in 3.67s
```

## 5. Jak odtworzyć

```bash
pip install -e ".[dev]"
python -m pytest -v
python scripts/demo_synthetic.py /tmp/lar_demo
```
