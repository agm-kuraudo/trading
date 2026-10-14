# Implementation Plan: SP-354 Recent-Extreme Stop / Risk-Based Target Exit Strategy

## Overview

This plan implements the Recent_Extreme_Exit_Strategy as an opt-in `ExitStrategy`
in `vpa/backtesting/`, following the design's additive, backward-compatible
approach. Work proceeds bottom-up: data models first (new enums and the three
additive optional fields on `ExitResult`/`TradeRecord`), then the engine
thread-through, then the strategy itself (construction, geometry, forward scan),
then its property/unit tests, then engine integration, the CSV boundary, and
finally the variation-harness sweep. Each task builds on the previous ones and
ends wired into the existing engine and reporting pipeline.

The repo uses `pytest` + `hypothesis` + `ruff`. Property tests use
`@settings(max_examples=100)` and are tagged with a comment of the form
`# Feature: sp-354-recent-extreme-stop-target, Property N: <text>`.

## Tasks

- [x] 1. Extend data models with the new enums and additive fields
  - In `vpa/backtesting/models.py`, add an `ExitReason(Enum)` with members `STOP = "stop"`, `TARGET = "target"`, `FIXED_HOLD = "fixed_hold"`.
  - Add two new members to `SkipReason`: `UNAVAILABLE_RECENT_EXTREME = "unavailable_recent_extreme"` and `DEGENERATE_RISK_DISTANCE = "degenerate_risk_distance"`, leaving the existing members unchanged.
  - Append three optional fields to `ExitResult`: `stop_loss: float | None = None`, `profit_target: float | None = None`, `exit_reason: ExitReason | None = None` (after the existing `reason` field).
  - Append the same three optional defaulted fields to `TradeRecord` (after `signal_type`): `stop_loss: float | None = None`, `profit_target: float | None = None`, `exit_reason: ExitReason | None = None`.
  - _Requirements: 6.5, 7.1, 7.2_

  - [~]* 1.1 Write unit tests for the new models
    - Assert `ExitReason` has exactly `STOP`, `TARGET`, `FIXED_HOLD`.
    - Assert the two new `SkipReason` members exist and the pre-existing members are still present.
    - Assert a default-constructed `ExitResult(exit_index, exit_price, reason)` leaves `stop_loss`/`profit_target`/`exit_reason` at `None`.
    - Assert a `TradeRecord` built with only the original six fields leaves the three new fields at `None`.
    - _Requirements: 6.5, 7.1, 7.2_

- [x] 2. Thread the three extras through the engine
  - In `vpa/backtesting/engine.py` `_resolve_trade`, copy `exit_result.stop_loss`, `exit_result.profit_target`, and `exit_result.exit_reason` onto the constructed `TradeRecord`. This is the only engine change and is additive.
  - Confirm no other engine logic changes: price validation, skip handling, and return math stay as-is.
  - _Requirements: 7.3, 7.4, 8.3_

  - [~]* 2.1 Write regression tests for backward-compatible engine output
    - Run the engine with `FixedHoldExitStrategy` and with the percentage `StopLossExitStrategy`; assert every resulting `TradeRecord` has `stop_loss`, `profit_target`, and `exit_reason` equal to `None`.
    - Assert the other `TradeRecord` fields (dates, prices, `return_pct`, `signal_type`) are identical to the pre-SP-354 values for the same inputs.
    - **Property 11: Backward-compatible output for non-supplying strategies**
    - _Requirements: 7.4, 8.3_

- [x] 3. Create `RecentExtremeExitStrategy` skeleton with construction-time validation
  - In `vpa/backtesting/exit_strategy.py`, add a `@dataclass(frozen=True)` `RecentExtremeExitStrategy` with fields `lookback: int`, `reward_risk: float`, `buffer: float = 0.0`, `direction: SignalDirection = SignalDirection.UP`, and `_fixed_hold: FixedHoldExitStrategy = field(default_factory=FixedHoldExitStrategy)`.
  - Implement `__post_init__` validation: reject `bool` before the int check, raise `ValueError` when `lookback` is not a positive int, when `buffer < 0`, and when `reward_risk` is not strictly `> 0`.
  - Add a placeholder `resolve_exit(self, entry_index, price_series, hold_period) -> ExitResult` returning the fixed-hold fallback for now, so the class satisfies the `ExitStrategy` protocol and import resolves.
  - _Requirements: 1.1, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [~]* 3.1 Write construction and conformance unit tests
    - Parametrized `ValueError` cases for `lookback` in `{0, -1, 1.5, True}`, `buffer < 0`, and `reward_risk` in `{0, -1}`.
    - Assert the default `direction` is `SignalDirection.UP` and default `buffer` is `0.0`.
    - Assert `isinstance(RecentExtremeExitStrategy(lookback=5, reward_risk=2), ExitStrategy)`.
    - _Requirements: 1.1, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

- [x] 4. Implement `resolve_exit` stop/target geometry and degenerate skips
  - Compute the strict prior-L window `price_series[entry_index - lookback : entry_index]`; when `entry_index - lookback < 0`, return `ExitResult(None, None, SkipReason.UNAVAILABLE_RECENT_EXTREME)`.
  - For UP: `extreme = min(low)` over the window, `stop = extreme - buffer`; for DOWN: `extreme = max(high)`, `stop = extreme + buffer`.
  - Compute `entry_price = close[entry_index]`, `risk = abs(entry_price - stop)`, and `target = entry_price + risk * reward_risk` (UP) / `entry_price - risk * reward_risk` (DOWN).
  - Return `ExitResult(None, None, SkipReason.DEGENERATE_RISK_DISTANCE)` when `risk == 0`, or when the stop is on the non-adverse side (`stop >= entry_price` for UP, `stop <= entry_price` for DOWN).
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 6.1, 6.2, 6.3_

- [x] 5. Implement `resolve_exit` forward scan and fixed-hold fallback
  - Scan `j` from `entry_index + 1` to `min(entry_index + hold_period, last_index)` inclusive.
  - Test the stop before the target each bar so stop-first precedence holds when both breach on one bar.
  - UP stop: `low <= stop` -> `exit_price = open if open <= stop else stop`, reason `STOP`. UP target: `high >= target` -> `exit_price = open if open >= target else target`, reason `TARGET`.
  - DOWN stop: `high >= stop` -> `exit_price = open if open >= stop else stop`, reason `STOP`. DOWN target: `low <= target` -> `exit_price = open if open <= target else target`, reason `TARGET`.
  - Carry `stop`, `target`, and the `ExitReason` on the returned `ExitResult` for breach cases.
  - On no breach, delegate to `self._fixed_hold.resolve_exit(...)`; pass its result through verbatim when it carries a `SkipReason` (e.g. `INSUFFICIENT_FUTURE_DATA_EXIT`), otherwise return it with `stop`/`target` attached and `exit_reason = FIXED_HOLD`.
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9_

- [x] 6. Property and oracle tests for the strategy
  - [ ]* 6.1 Property test — recent-extreme stop geometry
    - **Property 1: Recent-extreme stop geometry**
    - Tag: `# Feature: sp-354-recent-extreme-stop-target, Property 1: ...`, `@settings(max_examples=100)`.
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 2.6_

  - [ ]* 6.2 Property test — risk distance and profit target by direction
    - **Property 2: Risk distance and profit target by direction**
    - _Requirements: 4.1, 4.2, 4.3_

  - [ ]* 6.3 Property test — first breach wins with stop-first precedence
    - **Property 3: First breach wins, with stop-first precedence**
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 9.3_

  - [ ]* 6.4 Property test — gap-through-at-open exit pricing
    - **Property 4: Gap-through-at-open exit pricing**
    - _Requirements: 5.7, 5.8_

  - [ ]* 6.5 Property test — no-breach delegates identically to fixed-hold fallback
    - **Property 5: No-breach delegates identically to the fixed-hold fallback**
    - _Requirements: 5.9_

  - [ ]* 6.6 Property test — unavailable recent extreme skips
    - **Property 6: Unavailable recent extreme skips**
    - _Requirements: 6.1_

  - [ ]* 6.7 Property test — degenerate risk distance skips
    - **Property 7: Degenerate risk distance skips**
    - _Requirements: 6.2, 6.3_

  - [ ]* 6.8 Property test — inputs are never mutated
    - **Property 8: Inputs are never mutated (immutability)**
    - _Requirements: 1.5_

  - [ ]* 6.9 Property test — determinism
    - **Property 9: Determinism**
    - _Requirements: 1.4, 1.6, 9.1_

  - [ ]* 6.10 Hand-computed oracle unit test
    - A tiny fixed Price_Series with hand-computed `exit_index`/`exit_price` for stop breach, target breach, and fixed-hold fallback, in both directions.
    - _Requirements: 9.2, 9.3_

- [x] 7. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Engine integration tests for the strategy
  - [ ]* 8.1 Skip recording for the two new SkipReasons
    - Run the engine on signals that trigger `UNAVAILABLE_RECENT_EXTREME` and `DEGENERATE_RISK_DISTANCE`; assert a `SkippedSignal` with each reason via the existing engine skip path.
    - _Requirements: 6.4_

  - [ ]* 8.2 Field population on resolved recent-extreme trades
    - Run the engine with a `RecentExtremeExitStrategy`; assert resolved `TradeRecord`s carry the computed `stop_loss`, `profit_target`, and `exit_reason`.
    - **Property 10: Recent-extreme per-trade output carries stop/target/reason**
    - _Requirements: 7.3_

- [x] 9. Extend the per-trade CSV in reporting.py
  - Append `"stop_loss"`, `"profit_target"`, `"exit_reason"` to `PER_TRADE_HEADER` after the existing seven columns.
  - In `per_trade_rows`, append the three cells per row: render `None` as `""`, numeric values via `str(...)`, and `exit_reason` via `.name`; keep the original seven columns in their current order and position.
  - _Requirements: 12.3, 12.4_

  - [ ]* 9.1 Tests for the CSV extension
    - Assert the first seven header columns and their order are unchanged and the three new columns are appended.
    - Assert recent-extreme trades populate the three columns and non-supplying trades render them as empty strings.
    - **Property 10: Recent-extreme per-trade output carries stop/target/reason**
    - **Property 11: Backward-compatible output for non-supplying strategies**
    - _Requirements: 12.3, 12.4_

- [x] 10. Add direction filters and the 12 recent-extreme default variations
  - In `vpa/backtesting/variations.py`, add `_include_long` and `_include_short` filters that admit only signals whose `SIGNAL_DIRECTIONS` value is `UP` / `DOWN` respectively.
  - Append twelve variations to `build_default_variations()` after the existing catalogue: for `reward in (1, 2, 3)`, `lookback in (5, 10)`, `direction in (UP, DOWN)`, each named `Recent_Extreme_{Long,Short}_R{r}_LB{lb}`, with `buffer=0`, direction carried explicitly, and a zero-arg `exit_strategy_factory` closure using default-arg binding to avoid late binding.
  - _Requirements: 10.1, 10.3, 10.4, 11.1, 11.2, 11.3, 11.4, 11.5_

  - [ ]* 10.1 Tests for the variation catalogue additions
    - Assert the leading slice of `build_default_variations()` names equals the known pre-SP-354 list (presence and order preserved).
    - Assert the twelve expected `Recent_Extreme_{Long,Short}_R{r}_LB{lb}` names are present.
    - Assert each new variation's `exit_strategy_factory()` returns a `RecentExtremeExitStrategy` with the expected `lookback`, `reward_risk`, `buffer == 0`, and `direction`.
    - Assert all `reporting.variation_filename` slugs are unique across the catalogue.
    - _Requirements: 10.1, 10.3, 10.4, 11.1, 11.2, 11.3, 11.4, 11.5_

- [x] 11. Harness and end-to-end pipeline tests
  - [ ]* 11.1 Failure isolation test
    - Inject a variation whose `exit_strategy_factory` raises; assert `run_variations` records a `VariationFailure` and the remaining variations (including recent-extreme ones) still complete with metrics and CSVs.
    - _Requirements: 12.1, 12.2_

  - [ ]* 11.2 End-to-end comparison-output test
    - Run the full `run_variations` -> reporting pipeline over the default catalogue; assert recent-extreme variations produce metrics plus per-trade and equity CSVs alongside the existing variations.
    - _Requirements: 10.2, 12.2_

  - [ ]* 11.3 Full-pipeline backward-compatibility test
    - Run the pipeline for a fixed-hold and a percentage-stop variation; assert it runs unchanged, all `TradeRecord` extras are `None`, and the appended CSV columns render empty.
    - **Property 11: Backward-compatible output for non-supplying strategies**
    - _Requirements: 12.4_

- [x] 12. Final verification
  - Run `ruff check .` and `ruff format --check .`; apply `ruff check --fix .` / `ruff format .` and resolve anything flagged.
  - Run the full suite `pytest -m ""` and fix any failures.
  - _Requirements: all (verification)_

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP; core implementation tasks are never optional.
- Each task references specific requirements for traceability; property-test sub-tasks additionally name the design Correctness Property they implement.
- Property tests run a minimum of 100 iterations via `@settings(max_examples=100)` and carry the `# Feature: sp-354-recent-extreme-stop-target, Property N: ...` tag.
- Checkpoints ensure incremental validation before the harness and reporting layers are wired up.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "3.1"] },
    { "id": 2, "tasks": ["6.1", "6.2", "6.3", "6.4", "6.5", "6.6", "6.7", "6.8", "6.9", "6.10"] },
    { "id": 3, "tasks": ["8.1", "8.2"] },
    { "id": 4, "tasks": ["9.1"] },
    { "id": 5, "tasks": ["10.1"] },
    { "id": 6, "tasks": ["11.1", "11.2", "11.3"] }
  ]
}
```
