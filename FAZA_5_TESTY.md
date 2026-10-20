# FAZA_5_TESTY — testy poprawek po audycie

Wyniki pochodzą z **rzeczywistych** uruchomień w kontenerze projektu (2026-10-20, ok. 10:15 UTC).
Wszystkie testy używają danych **syntetycznych**; potwierdzają reguły i mechanikę, a **nie** skuteczność tradingową.

## Podsumowanie

| Uruchomienie | Wynik |
|---|---|
| `python3 -m pytest -v` (Python 3.13.16, pytest 9.1.1) | **115 passed**, 0 failed, 0 skipped |
| `python3.11 -m pytest -v` (Python 3.11.17) | **115 passed**, 0 failed, 0 skipped |
| Testy integracyjne CLI `tests/test_cli.py` (przez `lar_ofi.cli.main`, argparse) | **4 passed** |
| Test dymny przez zainstalowany plik `lar-ofi` (osobne procesy, prawdziwy zegar) | import → observe-file (14) → predict `RECORDED` LONG → verify-journal OK; ten sam zestaw z `max_record_delay_seconds = 0` → `NOT_RECORDED` `LATE_RECORDING` |
| `pyflakes src tests scripts` | brak uwag |
| `scripts/demo_synthetic.py` | wykonane; `verify_journal` OK |

Przed fazą 5: 71 przypadków testowych. Po fazie 5: 115 = `test_faza5.py` 42 (nowy plik, 38 funkcji, część parametryzowana) + `test_cli.py` 4 (było 2: jeden zastąpiony, dwa nowe) + `test_critical.py` 38 + `test_components.py` 19 + `test_setups.py` 12 (bez zmian liczby; dostosowane do schematu v2 — szczegóły niżej).

## Odtworzenie błędów P0 na kodzie sprzed poprawek (commit `2322a6c`)

Skrypt uruchomiony w osobnym `git worktree` starego commita:

```
OLD BUG 1: screenshots 1h old, journaled anyway: a95a91aa61496144 decision WAIT
OLD BUG 2: prices known at 10:00:35 were falling; old momentum baseline direction: LONG (entry 2026-10-20T10:01:00Z )
```

Po poprawkach: ten sam przypadek 1 → `LATE_RECORDING` (`test_p0_late_decision_on_old_data_is_refused_even_if_recorded_promptly`, `test_cli_predict_on_old_screenshots_is_not_recorded`); przypadek 2 → `SHORT` z `known_at_utc = 10:09:00` (`test_p0_momentum_baseline_between_minute_boundaries_has_no_lookahead`).

## Testy regresyjne według ustaleń audytu

### P0.1 Trzy znaczniki czasu / spóźniony zapis — 11/11 PASSED

- `tests/test_faza5.py::test_p0_report_separates_data_as_of_and_decision_time` — PASSED
- `tests/test_faza5.py::test_p0_late_decision_on_old_data_is_refused_even_if_recorded_promptly` — PASSED
- `tests/test_faza5.py::test_p0_record_held_back_after_decision_is_refused` — PASSED
- `tests/test_faza5.py::test_p0_future_screenshot_does_not_move_data_as_of` — PASSED
- `tests/test_faza5.py::test_p0_stale_screenshots_still_count_for_data_as_of` — PASSED
- `tests/test_faza5.py::test_p0_data_as_of_ignores_newer_screenshot_that_was_not_used` — PASSED
- `tests/test_faza5.py::test_p0_no_data_cannot_be_journaled` — PASSED
- `tests/test_faza5.py::test_p0_v1_journal_is_not_mixed_with_v2` — PASSED
- `tests/test_cli.py::test_cli_predict_on_old_screenshots_is_not_recorded` — PASSED
- `tests/test_cli.py::test_cli_predict_detects_late_recording_with_simulated_clock` — PASSED
- `tests/test_critical.py::test_12b_journal_rejects_future_or_late_recording` — PASSED

### P0.2 Baseline momentum bez informacji przyszłej — 3/3 PASSED

- `tests/test_faza5.py::test_p0_momentum_baseline_between_minute_boundaries_has_no_lookahead` — PASSED
- `tests/test_faza5.py::test_p0_momentum_baseline_unit` — PASSED
- `tests/test_critical.py::test_12c_resolution_entry_is_after_recording_and_baseline_uses_past_only` — PASSED

### P1 Powtarzalność obserwacji — 13/13 PASSED

- `tests/test_faza5.py::test_p1_every_enabled_field_has_a_written_procedure` — PASSED
- `tests/test_faza5.py::test_p1_qualitative_fields_declare_the_quantitative_data_they_lack` — PASSED
- `tests/test_faza5.py::test_p1_window_fields_require_a_valid_window` — PASSED
- `tests/test_faza5.py::test_p1_window_not_ending_at_latest_closed_bar_is_unknown` — PASSED
- `tests/test_faza5.py::test_p1_heatmap_comparison_needs_identical_view_settings[views0]` — PASSED
- `tests/test_faza5.py::test_p1_heatmap_comparison_needs_identical_view_settings[views1]` — PASSED
- `tests/test_faza5.py::test_p1_visual_comparison_is_not_labelled_as_resiliency` — PASSED
- `tests/test_faza5.py::test_p1_template_carries_procedures` — PASSED
- `tests/test_faza5.py::test_p1_protocol_document_is_generated_from_registry` — PASSED
- `tests/test_critical.py::test_08_single_snapshot_cannot_measure_replenishment` — PASSED
- `tests/test_critical.py::test_08b_comparison_against_non_heatmap_is_not_measurable` — PASSED
- `tests/test_critical.py::test_08c_comparison_with_later_screenshot_is_not_measurable` — PASSED
- `tests/test_critical.py::test_08d_l2_single_snapshot_cannot_measure_replenishment` — PASSED

### P1 Reguły strategiczne (testy graniczne) — 12/12 PASSED

- `tests/test_faza5.py::test_p1_30m_screenshot_must_contain_latest_closed_bar[-570-LONG]` — PASSED
- `tests/test_faza5.py::test_p1_30m_screenshot_must_contain_latest_closed_bar[-571-WAIT]` — PASSED
- `tests/test_faza5.py::test_p1_5m_screenshot_must_contain_latest_closed_bar[-270-LONG]` — PASSED
- `tests/test_faza5.py::test_p1_5m_screenshot_must_contain_latest_closed_bar[-271-WAIT]` — PASSED
- `tests/test_faza5.py::test_p1_acceptance_boundary[1-CANDIDATE_LONG]` — PASSED
- `tests/test_faza5.py::test_p1_acceptance_boundary[2-CONFIRMED_LONG]` — PASSED
- `tests/test_faza5.py::test_p1_1m_reading_alone_cannot_satisfy_a_5m_condition` — PASSED
- `tests/test_faza5.py::test_p1_concordant_1m_reading_adds_no_evidence` — PASSED
- `tests/test_faza5.py::test_p1_analysis_timeframe_selects_the_decision_timeframe` — PASSED
- `tests/test_faza5.py::test_p1_analysis_timeframe_must_be_micro` — PASSED
- `tests/test_faza5.py::test_p1_failed_auction_still_confirms_under_new_rules` — PASSED
- `tests/test_critical.py::test_05b_conflicting_readings_across_timeframes_give_wait` — PASSED

### P1 Ewaluacja — 7/7 PASSED

- `tests/test_faza5.py::test_p1_mcnemar_exact_values` — PASSED
- `tests/test_faza5.py::test_p1_overlapping_predictions_are_thinned` — PASSED
- `tests/test_faza5.py::test_p1_high_accuracy_equal_to_baseline_is_not_an_edge` — PASSED
- `tests/test_faza5.py::test_p1_claim_only_from_independent_segment_and_bonferroni` — PASSED
- `tests/test_faza5.py::test_p1_insufficient_non_overlapping_sample` — PASSED
- `tests/test_components.py::test_evaluation_counts_and_disclosure` — PASSED
- `tests/test_components.py::test_chronological_split` — PASSED

### P2 Integralność danych — 8/8 PASSED

- `tests/test_faza5.py::test_p2_bars_of_another_market_never_settle_a_prediction` — PASSED
- `tests/test_faza5.py::test_p2_bar_market_must_be_declared_and_consistent` — PASSED
- `tests/test_faza5.py::test_p2_missing_last_update_cannot_pass_as_fresh` — PASSED
- `tests/test_faza5.py::test_p2_user_live_attestation_is_accepted_and_recorded` — PASSED
- `tests/test_faza5.py::test_p2_live_attestation_must_be_boolean` — PASSED
- `tests/test_faza5.py::test_p2_require_update_evidence_can_be_disabled_explicitly` — PASSED
- `tests/test_cli.py::test_cli_import_bars_requires_market` — PASSED
- `tests/test_critical.py::test_13b_reimport_price_bars_creates_no_duplicates` — PASSED

## Zmiany w istniejących testach (jawnie)

* `tests/conftest.py`: `T0` przesunięte na 10:09:30 UTC (wewnątrz świec 30M 10:00 i 5M 10:05, aby fixture'y spełniały regułę ostatniej zamkniętej świecy); domyślne `data_last_update_utc` = 1 s przed wykonaniem; identyczne `view_settings` obu heatmap; okna obserwacji generowane przez `windows_for()`; świece z `MARKET`.
* `tests/test_critical.py`: `as_of` → `decision_time`; `import_price_bars(..., MARKET, ...)`; oczekiwane czasy wejścia 10:10/10:15; komunikat `TIME_ORDER_VIOLATION` zamiast `future`; test 04d z przesunięciem −250 s (synchronizacja w obrębie świecy 5M); test 06b z oknem; nowe klucze `ask_side_visual_change`, `after_costs`.
* `tests/test_components.py`: nowa struktura ewaluacji (`directional_accuracy.non_overlapping`, `IN_SAMPLE_DESCRIPTIVE_ONLY`), korekta obserwacji z oknem, świece z rynkiem.
* `tests/test_cli.py`: dawny test `test_cli_predict_refuses_stale_screenshots` oczekiwał zapisu WAIT na starych danych — to właśnie był objaw błędu P0; zastąpiony testem oczekującym `NOT_RECORDED`/`LATE_RECORDING`.

Żaden test nie został pominięty ani wyłączony.

## Pełny wynik `pytest -v` (Python 3.13)

```
============================= test session starts ==============================
platform linux -- Python 3.13.16, pytest-9.1.1, pluggy-1.7.0 -- /usr/bin/python3
rootdir: /home/user/Implementacja-systemu-LAR-OFI-dla-BTCUSDT-Perpetual
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.15.1
collecting ... collected 115 items

tests/test_cli.py::test_cli_import_observe_analyze PASSED                [  0%]
tests/test_cli.py::test_cli_predict_on_old_screenshots_is_not_recorded PASSED [  1%]
tests/test_cli.py::test_cli_predict_detects_late_recording_with_simulated_clock PASSED [  2%]
tests/test_cli.py::test_cli_import_bars_requires_market PASSED           [  3%]
tests/test_components.py::test_non_image_and_empty_files_rejected PASSED [  4%]
tests/test_components.py::test_unknown_indicator_and_bad_timeframe_rejected PASSED [  5%]
tests/test_components.py::test_workspace_limit_flagged PASSED            [  6%]
tests/test_components.py::test_capture_after_import_time_rejected PASSED [  6%]
tests/test_components.py::test_field_must_match_indicator_and_timeframe PASSED [  7%]
tests/test_components.py::test_correction_supersedes_and_keeps_history PASSED [  8%]
tests/test_components.py::test_bulk_entry_is_all_or_nothing PASSED       [  9%]
tests/test_components.py::test_template_lists_only_applicable_fields PASSED [ 10%]
tests/test_components.py::test_scoring_bands PASSED                      [ 11%]
tests/test_components.py::test_funding_crossing PASSED                   [ 12%]
tests/test_components.py::test_bad_bars_rejected_entirely PASSED         [ 13%]
tests/test_components.py::test_wilson_and_mdd PASSED                     [ 13%]
tests/test_components.py::test_evaluation_counts_and_disclosure PASSED   [ 14%]
tests/test_components.py::test_chronological_split PASSED                [ 15%]
tests/test_components.py::test_ofi_contribution_cases PASSED             [ 16%]
tests/test_components.py::test_queue_imbalance_and_ofi_sum PASSED        [ 17%]
tests/test_components.py::test_price_impact_fit_recovers_slope PASSED    [ 18%]
tests/test_components.py::test_replay_validates_sequence_and_computes_metrics PASSED [ 19%]
tests/test_components.py::test_delta_before_snapshot_marks_stream_incomplete PASSED [ 20%]
tests/test_critical.py::test_01_no_screenshots_gives_wait PASSED         [ 20%]
tests/test_critical.py::test_01b_screenshots_without_observations_give_wait PASSED [ 21%]
tests/test_critical.py::test_02_wrong_instrument_dataset_rejected[instrument-ETHUSDT] PASSED [ 22%]
tests/test_critical.py::test_02_wrong_instrument_dataset_rejected[exchange-Binance] PASSED [ 23%]
tests/test_critical.py::test_02_wrong_instrument_dataset_rejected[contract_type-SPOT] PASSED [ 24%]
tests/test_critical.py::test_02b_screenshot_of_wrong_instrument_rejected PASSED [ 25%]
tests/test_critical.py::test_03_missing_timestamp_gives_insufficient_data PASSED [ 26%]
tests/test_critical.py::test_03b_naive_timestamp_is_rejected_not_guessed PASSED [ 26%]
tests/test_critical.py::test_04_stale_data_gives_wait_under_block_policy PASSED [ 27%]
tests/test_critical.py::test_04b_stale_data_excluded_under_exclude_policy PASSED [ 28%]
tests/test_critical.py::test_04c_chart_not_updated_gives_wait PASSED     [ 29%]
tests/test_critical.py::test_04d_unsynchronised_screenshots_give_wait PASSED [ 30%]
tests/test_critical.py::test_05_conflicting_aggression_sources_give_wait PASSED [ 31%]
tests/test_critical.py::test_05b_conflicting_readings_across_timeframes_give_wait PASSED [ 32%]
tests/test_critical.py::test_05c_price_inconsistent_with_value_area_gives_wait PASSED [ 33%]
tests/test_critical.py::test_06_unreadable_values_become_unknown PASSED  [ 33%]
tests/test_critical.py::test_06b_uncertain_reading_treated_as_unknown_by_default PASSED [ 34%]
tests/test_critical.py::test_07_l2_quantities_cannot_be_entered_from_screenshots[ofi] PASSED [ 35%]
tests/test_critical.py::test_07_l2_quantities_cannot_be_entered_from_screenshots[queue_imbalance] PASSED [ 36%]
tests/test_critical.py::test_07_l2_quantities_cannot_be_entered_from_screenshots[liquidity_resiliency] PASSED [ 37%]
tests/test_critical.py::test_07b_screenshot_mode_reports_no_ofi PASSED   [ 38%]
tests/test_critical.py::test_07c_l2_metrics_refuse_without_data PASSED   [ 39%]
tests/test_critical.py::test_08_single_snapshot_cannot_measure_replenishment PASSED [ 40%]
tests/test_critical.py::test_08b_comparison_against_non_heatmap_is_not_measurable PASSED [ 40%]
tests/test_critical.py::test_08c_comparison_with_later_screenshot_is_not_measurable PASSED [ 41%]
tests/test_critical.py::test_08d_l2_single_snapshot_cannot_measure_replenishment PASSED [ 42%]
tests/test_critical.py::test_09_concordant_cvd_and_footprint_are_one_evidence_group PASSED [ 43%]
tests/test_critical.py::test_10_no_cost_config_means_no_profitability_claim PASSED [ 44%]
tests/test_critical.py::test_10b_cost_model_only_from_explicit_user_values PASSED [ 45%]
tests/test_critical.py::test_11_recorded_prediction_and_result_cannot_be_changed PASSED [ 46%]
tests/test_critical.py::test_11b_tampering_outside_sqlite_triggers_is_detected PASSED [ 46%]
tests/test_critical.py::test_12_future_screenshots_do_not_affect_earlier_decision PASSED [ 47%]
tests/test_critical.py::test_12b_journal_rejects_future_or_late_recording PASSED [ 48%]
tests/test_critical.py::test_12c_resolution_entry_is_after_recording_and_baseline_uses_past_only PASSED [ 49%]
tests/test_critical.py::test_13_reimport_same_dataset_creates_no_duplicates PASSED [ 50%]
tests/test_critical.py::test_13b_reimport_price_bars_creates_no_duplicates PASSED [ 51%]
tests/test_critical.py::test_13c_duplicate_file_inside_one_dataset_rejected PASSED [ 52%]
tests/test_critical.py::test_14_identical_inputs_identical_outputs PASSED [ 53%]
tests/test_faza5.py::test_p0_report_separates_data_as_of_and_decision_time PASSED [ 53%]
tests/test_faza5.py::test_p0_late_decision_on_old_data_is_refused_even_if_recorded_promptly PASSED [ 54%]
tests/test_faza5.py::test_p0_record_held_back_after_decision_is_refused PASSED [ 55%]
tests/test_faza5.py::test_p0_future_screenshot_does_not_move_data_as_of PASSED [ 56%]
tests/test_faza5.py::test_p0_stale_screenshots_still_count_for_data_as_of PASSED [ 57%]
tests/test_faza5.py::test_p0_data_as_of_ignores_newer_screenshot_that_was_not_used PASSED [ 58%]
tests/test_faza5.py::test_p0_no_data_cannot_be_journaled PASSED          [ 59%]
tests/test_faza5.py::test_p0_v1_journal_is_not_mixed_with_v2 PASSED      [ 60%]
tests/test_faza5.py::test_p0_momentum_baseline_between_minute_boundaries_has_no_lookahead PASSED [ 60%]
tests/test_faza5.py::test_p0_momentum_baseline_unit PASSED               [ 61%]
tests/test_faza5.py::test_p1_every_enabled_field_has_a_written_procedure PASSED [ 62%]
tests/test_faza5.py::test_p1_qualitative_fields_declare_the_quantitative_data_they_lack PASSED [ 63%]
tests/test_faza5.py::test_p1_window_fields_require_a_valid_window PASSED [ 64%]
tests/test_faza5.py::test_p1_window_not_ending_at_latest_closed_bar_is_unknown PASSED [ 65%]
tests/test_faza5.py::test_p1_heatmap_comparison_needs_identical_view_settings[views0] PASSED [ 66%]
tests/test_faza5.py::test_p1_heatmap_comparison_needs_identical_view_settings[views1] PASSED [ 66%]
tests/test_faza5.py::test_p1_visual_comparison_is_not_labelled_as_resiliency PASSED [ 67%]
tests/test_faza5.py::test_p1_template_carries_procedures PASSED          [ 68%]
tests/test_faza5.py::test_p1_30m_screenshot_must_contain_latest_closed_bar[-570-LONG] PASSED [ 69%]
tests/test_faza5.py::test_p1_30m_screenshot_must_contain_latest_closed_bar[-571-WAIT] PASSED [ 70%]
tests/test_faza5.py::test_p1_5m_screenshot_must_contain_latest_closed_bar[-270-LONG] PASSED [ 71%]
tests/test_faza5.py::test_p1_5m_screenshot_must_contain_latest_closed_bar[-271-WAIT] PASSED [ 72%]
tests/test_faza5.py::test_p1_acceptance_boundary[1-CANDIDATE_LONG] PASSED [ 73%]
tests/test_faza5.py::test_p1_acceptance_boundary[2-CONFIRMED_LONG] PASSED [ 73%]
tests/test_faza5.py::test_p1_1m_reading_alone_cannot_satisfy_a_5m_condition PASSED [ 74%]
tests/test_faza5.py::test_p1_concordant_1m_reading_adds_no_evidence PASSED [ 75%]
tests/test_faza5.py::test_p1_analysis_timeframe_selects_the_decision_timeframe PASSED [ 76%]
tests/test_faza5.py::test_p1_analysis_timeframe_must_be_micro PASSED     [ 77%]
tests/test_faza5.py::test_p1_failed_auction_still_confirms_under_new_rules PASSED [ 78%]
tests/test_faza5.py::test_p1_mcnemar_exact_values PASSED                 [ 79%]
tests/test_faza5.py::test_p1_overlapping_predictions_are_thinned PASSED  [ 80%]
tests/test_faza5.py::test_p1_high_accuracy_equal_to_baseline_is_not_an_edge PASSED [ 80%]
tests/test_faza5.py::test_p1_claim_only_from_independent_segment_and_bonferroni PASSED [ 81%]
tests/test_faza5.py::test_p1_insufficient_non_overlapping_sample PASSED  [ 82%]
tests/test_faza5.py::test_p2_bars_of_another_market_never_settle_a_prediction PASSED [ 83%]
tests/test_faza5.py::test_p2_bar_market_must_be_declared_and_consistent PASSED [ 84%]
tests/test_faza5.py::test_p2_missing_last_update_cannot_pass_as_fresh PASSED [ 85%]
tests/test_faza5.py::test_p2_user_live_attestation_is_accepted_and_recorded PASSED [ 86%]
tests/test_faza5.py::test_p2_live_attestation_must_be_boolean PASSED     [ 86%]
tests/test_faza5.py::test_p2_require_update_evidence_can_be_disabled_explicitly PASSED [ 87%]
tests/test_faza5.py::test_env_helper_is_isolated PASSED                  [ 88%]
tests/test_faza5.py::test_p1_protocol_document_is_generated_from_registry PASSED [ 89%]
tests/test_setups.py::test_continuation_short_mirror PASSED              [ 90%]
tests/test_setups.py::test_failed_auction_long_mirror PASSED             [ 91%]
tests/test_setups.py::test_continuation_candidate_before_acceptance PASSED [ 92%]
tests/test_setups.py::test_mere_violation_of_vah_is_not_confirmation PASSED [ 93%]
tests/test_setups.py::test_absorbed_buying_invalidates_continuation PASSED [ 93%]
tests/test_setups.py::test_previous_candidate_invalidated_when_trigger_lost PASSED [ 94%]
tests/test_setups.py::test_wick_or_delta_or_absorption_alone_never_confirms_failed_auction PASSED [ 95%]
tests/test_setups.py::test_failed_auction_needs_replenishment_from_two_snapshots PASSED [ 96%]
tests/test_setups.py::test_failed_auction_invalidated_by_acceptance PASSED [ 97%]
tests/test_setups.py::test_opposite_live_setups_give_wait PASSED         [ 98%]
tests/test_setups.py::test_disabled_layer_observations_are_ignored PASSED [ 99%]
tests/test_setups.py::test_probability_is_never_a_number PASSED          [100%]

============================= 115 passed in 5.31s ==============================
```

## Pełny wynik `pytest -v` (Python 3.11)

```
============================= test session starts ==============================
platform linux -- Python 3.11.17, pytest-9.1.1, pluggy-1.7.0 -- /usr/bin/python3.11
rootdir: /home/user/Implementacja-systemu-LAR-OFI-dla-BTCUSDT-Perpetual
configfile: pyproject.toml
testpaths: tests
collecting ... collected 115 items

tests/test_cli.py::test_cli_import_observe_analyze PASSED                [  0%]
tests/test_cli.py::test_cli_predict_on_old_screenshots_is_not_recorded PASSED [  1%]
tests/test_cli.py::test_cli_predict_detects_late_recording_with_simulated_clock PASSED [  2%]
tests/test_cli.py::test_cli_import_bars_requires_market PASSED           [  3%]
tests/test_components.py::test_non_image_and_empty_files_rejected PASSED [  4%]
tests/test_components.py::test_unknown_indicator_and_bad_timeframe_rejected PASSED [  5%]
tests/test_components.py::test_workspace_limit_flagged PASSED            [  6%]
tests/test_components.py::test_capture_after_import_time_rejected PASSED [  6%]
tests/test_components.py::test_field_must_match_indicator_and_timeframe PASSED [  7%]
tests/test_components.py::test_correction_supersedes_and_keeps_history PASSED [  8%]
tests/test_components.py::test_bulk_entry_is_all_or_nothing PASSED       [  9%]
tests/test_components.py::test_template_lists_only_applicable_fields PASSED [ 10%]
tests/test_components.py::test_scoring_bands PASSED                      [ 11%]
tests/test_components.py::test_funding_crossing PASSED                   [ 12%]
tests/test_components.py::test_bad_bars_rejected_entirely PASSED         [ 13%]
tests/test_components.py::test_wilson_and_mdd PASSED                     [ 13%]
tests/test_components.py::test_evaluation_counts_and_disclosure PASSED   [ 14%]
tests/test_components.py::test_chronological_split PASSED                [ 15%]
tests/test_components.py::test_ofi_contribution_cases PASSED             [ 16%]
tests/test_components.py::test_queue_imbalance_and_ofi_sum PASSED        [ 17%]
tests/test_components.py::test_price_impact_fit_recovers_slope PASSED    [ 18%]
tests/test_components.py::test_replay_validates_sequence_and_computes_metrics PASSED [ 19%]
tests/test_components.py::test_delta_before_snapshot_marks_stream_incomplete PASSED [ 20%]
tests/test_critical.py::test_01_no_screenshots_gives_wait PASSED         [ 20%]
tests/test_critical.py::test_01b_screenshots_without_observations_give_wait PASSED [ 21%]
tests/test_critical.py::test_02_wrong_instrument_dataset_rejected[instrument-ETHUSDT] PASSED [ 22%]
tests/test_critical.py::test_02_wrong_instrument_dataset_rejected[exchange-Binance] PASSED [ 23%]
tests/test_critical.py::test_02_wrong_instrument_dataset_rejected[contract_type-SPOT] PASSED [ 24%]
tests/test_critical.py::test_02b_screenshot_of_wrong_instrument_rejected PASSED [ 25%]
tests/test_critical.py::test_03_missing_timestamp_gives_insufficient_data PASSED [ 26%]
tests/test_critical.py::test_03b_naive_timestamp_is_rejected_not_guessed PASSED [ 26%]
tests/test_critical.py::test_04_stale_data_gives_wait_under_block_policy PASSED [ 27%]
tests/test_critical.py::test_04b_stale_data_excluded_under_exclude_policy PASSED [ 28%]
tests/test_critical.py::test_04c_chart_not_updated_gives_wait PASSED     [ 29%]
tests/test_critical.py::test_04d_unsynchronised_screenshots_give_wait PASSED [ 30%]
tests/test_critical.py::test_05_conflicting_aggression_sources_give_wait PASSED [ 31%]
tests/test_critical.py::test_05b_conflicting_readings_across_timeframes_give_wait PASSED [ 32%]
tests/test_critical.py::test_05c_price_inconsistent_with_value_area_gives_wait PASSED [ 33%]
tests/test_critical.py::test_06_unreadable_values_become_unknown PASSED  [ 33%]
tests/test_critical.py::test_06b_uncertain_reading_treated_as_unknown_by_default PASSED [ 34%]
tests/test_critical.py::test_07_l2_quantities_cannot_be_entered_from_screenshots[ofi] PASSED [ 35%]
tests/test_critical.py::test_07_l2_quantities_cannot_be_entered_from_screenshots[queue_imbalance] PASSED [ 36%]
tests/test_critical.py::test_07_l2_quantities_cannot_be_entered_from_screenshots[liquidity_resiliency] PASSED [ 37%]
tests/test_critical.py::test_07b_screenshot_mode_reports_no_ofi PASSED   [ 38%]
tests/test_critical.py::test_07c_l2_metrics_refuse_without_data PASSED   [ 39%]
tests/test_critical.py::test_08_single_snapshot_cannot_measure_replenishment PASSED [ 40%]
tests/test_critical.py::test_08b_comparison_against_non_heatmap_is_not_measurable PASSED [ 40%]
tests/test_critical.py::test_08c_comparison_with_later_screenshot_is_not_measurable PASSED [ 41%]
tests/test_critical.py::test_08d_l2_single_snapshot_cannot_measure_replenishment PASSED [ 42%]
tests/test_critical.py::test_09_concordant_cvd_and_footprint_are_one_evidence_group PASSED [ 43%]
tests/test_critical.py::test_10_no_cost_config_means_no_profitability_claim PASSED [ 44%]
tests/test_critical.py::test_10b_cost_model_only_from_explicit_user_values PASSED [ 45%]
tests/test_critical.py::test_11_recorded_prediction_and_result_cannot_be_changed PASSED [ 46%]
tests/test_critical.py::test_11b_tampering_outside_sqlite_triggers_is_detected PASSED [ 46%]
tests/test_critical.py::test_12_future_screenshots_do_not_affect_earlier_decision PASSED [ 47%]
tests/test_critical.py::test_12b_journal_rejects_future_or_late_recording PASSED [ 48%]
tests/test_critical.py::test_12c_resolution_entry_is_after_recording_and_baseline_uses_past_only PASSED [ 49%]
tests/test_critical.py::test_13_reimport_same_dataset_creates_no_duplicates PASSED [ 50%]
tests/test_critical.py::test_13b_reimport_price_bars_creates_no_duplicates PASSED [ 51%]
tests/test_critical.py::test_13c_duplicate_file_inside_one_dataset_rejected PASSED [ 52%]
tests/test_critical.py::test_14_identical_inputs_identical_outputs PASSED [ 53%]
tests/test_faza5.py::test_p0_report_separates_data_as_of_and_decision_time PASSED [ 53%]
tests/test_faza5.py::test_p0_late_decision_on_old_data_is_refused_even_if_recorded_promptly PASSED [ 54%]
tests/test_faza5.py::test_p0_record_held_back_after_decision_is_refused PASSED [ 55%]
tests/test_faza5.py::test_p0_future_screenshot_does_not_move_data_as_of PASSED [ 56%]
tests/test_faza5.py::test_p0_stale_screenshots_still_count_for_data_as_of PASSED [ 57%]
tests/test_faza5.py::test_p0_data_as_of_ignores_newer_screenshot_that_was_not_used PASSED [ 58%]
tests/test_faza5.py::test_p0_no_data_cannot_be_journaled PASSED          [ 59%]
tests/test_faza5.py::test_p0_v1_journal_is_not_mixed_with_v2 PASSED      [ 60%]
tests/test_faza5.py::test_p0_momentum_baseline_between_minute_boundaries_has_no_lookahead PASSED [ 60%]
tests/test_faza5.py::test_p0_momentum_baseline_unit PASSED               [ 61%]
tests/test_faza5.py::test_p1_every_enabled_field_has_a_written_procedure PASSED [ 62%]
tests/test_faza5.py::test_p1_qualitative_fields_declare_the_quantitative_data_they_lack PASSED [ 63%]
tests/test_faza5.py::test_p1_window_fields_require_a_valid_window PASSED [ 64%]
tests/test_faza5.py::test_p1_window_not_ending_at_latest_closed_bar_is_unknown PASSED [ 65%]
tests/test_faza5.py::test_p1_heatmap_comparison_needs_identical_view_settings[views0] PASSED [ 66%]
tests/test_faza5.py::test_p1_heatmap_comparison_needs_identical_view_settings[views1] PASSED [ 66%]
tests/test_faza5.py::test_p1_visual_comparison_is_not_labelled_as_resiliency PASSED [ 67%]
tests/test_faza5.py::test_p1_template_carries_procedures PASSED          [ 68%]
tests/test_faza5.py::test_p1_30m_screenshot_must_contain_latest_closed_bar[-570-LONG] PASSED [ 69%]
tests/test_faza5.py::test_p1_30m_screenshot_must_contain_latest_closed_bar[-571-WAIT] PASSED [ 70%]
tests/test_faza5.py::test_p1_5m_screenshot_must_contain_latest_closed_bar[-270-LONG] PASSED [ 71%]
tests/test_faza5.py::test_p1_5m_screenshot_must_contain_latest_closed_bar[-271-WAIT] PASSED [ 72%]
tests/test_faza5.py::test_p1_acceptance_boundary[1-CANDIDATE_LONG] PASSED [ 73%]
tests/test_faza5.py::test_p1_acceptance_boundary[2-CONFIRMED_LONG] PASSED [ 73%]
tests/test_faza5.py::test_p1_1m_reading_alone_cannot_satisfy_a_5m_condition PASSED [ 74%]
tests/test_faza5.py::test_p1_concordant_1m_reading_adds_no_evidence PASSED [ 75%]
tests/test_faza5.py::test_p1_analysis_timeframe_selects_the_decision_timeframe PASSED [ 76%]
tests/test_faza5.py::test_p1_analysis_timeframe_must_be_micro PASSED     [ 77%]
tests/test_faza5.py::test_p1_failed_auction_still_confirms_under_new_rules PASSED [ 78%]
tests/test_faza5.py::test_p1_mcnemar_exact_values PASSED                 [ 79%]
tests/test_faza5.py::test_p1_overlapping_predictions_are_thinned PASSED  [ 80%]
tests/test_faza5.py::test_p1_high_accuracy_equal_to_baseline_is_not_an_edge PASSED [ 80%]
tests/test_faza5.py::test_p1_claim_only_from_independent_segment_and_bonferroni PASSED [ 81%]
tests/test_faza5.py::test_p1_insufficient_non_overlapping_sample PASSED  [ 82%]
tests/test_faza5.py::test_p2_bars_of_another_market_never_settle_a_prediction PASSED [ 83%]
tests/test_faza5.py::test_p2_bar_market_must_be_declared_and_consistent PASSED [ 84%]
tests/test_faza5.py::test_p2_missing_last_update_cannot_pass_as_fresh PASSED [ 85%]
tests/test_faza5.py::test_p2_user_live_attestation_is_accepted_and_recorded PASSED [ 86%]
tests/test_faza5.py::test_p2_live_attestation_must_be_boolean PASSED     [ 86%]
tests/test_faza5.py::test_p2_require_update_evidence_can_be_disabled_explicitly PASSED [ 87%]
tests/test_faza5.py::test_env_helper_is_isolated PASSED                  [ 88%]
tests/test_faza5.py::test_p1_protocol_document_is_generated_from_registry PASSED [ 89%]
tests/test_setups.py::test_continuation_short_mirror PASSED              [ 90%]
tests/test_setups.py::test_failed_auction_long_mirror PASSED             [ 91%]
tests/test_setups.py::test_continuation_candidate_before_acceptance PASSED [ 92%]
tests/test_setups.py::test_mere_violation_of_vah_is_not_confirmation PASSED [ 93%]
tests/test_setups.py::test_absorbed_buying_invalidates_continuation PASSED [ 93%]
tests/test_setups.py::test_previous_candidate_invalidated_when_trigger_lost PASSED [ 94%]
tests/test_setups.py::test_wick_or_delta_or_absorption_alone_never_confirms_failed_auction PASSED [ 95%]
tests/test_setups.py::test_failed_auction_needs_replenishment_from_two_snapshots PASSED [ 96%]
tests/test_setups.py::test_failed_auction_invalidated_by_acceptance PASSED [ 97%]
tests/test_setups.py::test_opposite_live_setups_give_wait PASSED         [ 98%]
tests/test_setups.py::test_disabled_layer_observations_are_ignored PASSED [ 99%]
tests/test_setups.py::test_probability_is_never_a_number PASSED          [100%]

============================= 115 passed in 5.95s ==============================
```
