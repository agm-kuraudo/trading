# Signal Direction Derivation Bugfix Design

## Overview

The per-ticker config importer `scripts/import_ticker_signals.py` collapses a multi-horizon
analysis CSV into one rule per signal type. Its `get_rule` function hardcodes
`"adjusted_direction": "BUY"` for all three actionable interpretation bands, so the emitted
action is independent of the signal's real base direction. The correct action is a function of
the signal's base direction (modelled in `SIGNAL_DIRECTIONS` in
`vpa/ml_validation/signal_analysis.py`) combined with the band: the contrarian band inverts the
base direction, while the strong-signal and weak-edge bands keep it. The resolved direction is
then mapped to an action string (`UP -> "BUY"`, `DOWN -> "SELL"`).

The fix derives `adjusted_direction` instead of hardcoding it. Because the current signature of
`get_rule(row)` receives only the analysis row and not the `signal_type` string (the string is
the `groupby` key in `build_ticker_config`), the fix must thread the base direction into the rule
derivation. The band logic, confidence levels, hold-days, `select_row` selection, and
`build_ticker_config` grouping/NONE-fallback behaviour all remain unchanged. Unknown signal types
fall back to `{"adjusted_direction": "NONE"}` and never raise.

This bug is tracked as Jira SP-360.

## Glossary

- **Bug_Condition (C)**: The condition that triggers the bug — a significant, actionable signal
  whose correctly-derived action is `"SELL"` (not `"BUY"`). Concretely: a DOWN-base signal in the
  strong-signal band, a DOWN-base signal in the weak-edge band, or an UP-base signal in the
  contrarian band. See `isBugCondition` below.
- **Property (P)**: The desired behaviour — `adjusted_direction` is derived from the base
  direction and band (`action(invert(base))` for contrarian, `action(base)` for strong-signal and
  weak-edge).
- **Preservation**: Every behaviour outside the bug condition must be byte-for-byte unchanged:
  DOWN-base contrarian (still `"BUY"`), UP-base strong-signal/weak-edge (still `"BUY"`), all
  noise/not-significant/missing inputs (still `{"adjusted_direction": "NONE"}`), unknown types
  (NONE under both old and new code), and the unchanged `confidence_level`, `suggested_hold_days`,
  `select_row`, and `build_ticker_config` grouping.
- **`get_rule`**: The function in `scripts/import_ticker_signals.py` that maps a single analysis
  row to a ticker-signal rule dict (`confidence_level`, `adjusted_direction`, `suggested_hold_days`
  — or `{"adjusted_direction": "NONE"}`).
- **`select_row`**: The function in `scripts/import_ticker_signals.py` that picks the
  representative horizon row for one signal type (lowest significant p-value, tie-broken by larger
  `event_count`, falling back to most events when none are significant). Unchanged by this fix.
- **`build_ticker_config`**: The function in `scripts/import_ticker_signals.py` that groups the
  frame by `signal_type`, calls `select_row` then `get_rule`, and assigns
  `{"adjusted_direction": "NONE"}` when `select_row` returns None. The `signal_type` string is the
  `groupby` key here. Lightly changed only to pass the base direction into rule derivation.
- **`SIGNAL_DIRECTIONS`**: The `dict[SignalType, SignalDirection]` in
  `vpa/ml_validation/signal_analysis.py` mapping each signal type to its base direction
  (`SignalDirection.UP` / `SignalDirection.DOWN`).
- **`direction_for`**: The existing helper in `vpa/backtesting/pnl.py`
  (`direction_for(signal_type: SignalType) -> SignalDirection | None`) that returns
  `SIGNAL_DIRECTIONS.get(signal_type)` — the precedent for a None-returning (non-raising)
  resolution.
- **base(X)**: The signal's base direction, resolved from the `signal_type` string via
  `SignalType(...)` then `SIGNAL_DIRECTIONS.get(...)`, or `None` when the type is unknown / has no
  entry.
- **band(X)**: The interpretation band from `hit_rate`/`p_value`
  (contrarian | strong-signal | weak-edge | noise/none).
- **invert(d)**: `UP -> DOWN`, `DOWN -> UP`.
- **action(d)**: `UP -> "BUY"`, `DOWN -> "SELL"`.

## Bug Details

### Bug Condition

The bug manifests whenever the correctly-derived action for a significant, actionable signal is
`"SELL"`. `get_rule` always emits `"BUY"` for the contrarian, strong-signal, and weak-edge bands
and never consults `SIGNAL_DIRECTIONS`, so every signal whose `(base direction, band)` combination
should resolve to SELL is mislabelled. The function is both ignoring the base direction and failing
to map the grouped `signal_type` string back to a `SignalType`.

**Formal Specification:**
```
FUNCTION isBugCondition(X)
  INPUT:  X = (signal_type string, hit_rate, p_value, horizon_days)
  OUTPUT: boolean

  // Only significant, actionable bands can be mislabelled; NONE bands are unaffected.
  IF base(X) = None THEN
    RETURN false            // unknown type -> NONE under both old and new code (preserved)
  END IF

  IF band(X) = contrarian THEN
    expected ← action(invert(base(X)))
  ELSE IF band(X) = strong-signal OR band(X) = weak-edge THEN
    expected ← action(base(X))
  ELSE
    RETURN false            // noise / not-significant -> NONE, no direction emitted
  END IF

  // The old get_rule always emits "BUY" for actionable bands; the bug is any
  // input whose correctly-derived action is not "BUY".
  RETURN expected ≠ "BUY"
END FUNCTION
```

Where `band(X)` follows the existing thresholds exactly:
```
FUNCTION band(X)
  IF hit_rate is missing OR p_value is missing OR p_value >= SIGNIFICANCE THEN
    RETURN none            // SIGNIFICANCE = 0.05
  IF hit_rate < 0.45            THEN RETURN contrarian
  IF hit_rate >= 0.60           THEN RETURN strong-signal
  IF 0.55 < hit_rate < 0.60     THEN RETURN weak-edge
  RETURN none                    // 0.45 <= hit_rate <= 0.55 noise band
END FUNCTION
```

And the desired correct behaviour:
```
FUNCTION expectedBehavior(X, result)
  INPUT:  X, result = fixed get_rule output for X
  OUTPUT: boolean
  IF band(X) = contrarian THEN
    RETURN result.adjusted_direction = action(invert(base(X)))
  ELSE                        // strong-signal or weak-edge
    RETURN result.adjusted_direction = action(base(X))
END FUNCTION
```

### Examples

- **DOWN-base, strong-signal (bug -> fixed)**: `distribution` (base DOWN), `hit_rate = 0.62`,
  `p_value = 0.01`. Old code emits `"BUY"`; correct is keep DOWN -> `"SELL"`. *(Req 1.1, 2.1)*
- **UP-base, contrarian (bug -> fixed)**: `accumulation` (base UP), `hit_rate = 0.40`,
  `p_value = 0.01`. Old code emits `"BUY"`; correct is invert UP -> DOWN -> `"SELL"`. *(Req 1.2, 2.2)*
- **DOWN-base, weak-edge (bug -> fixed)**: `strong_bearish` (base DOWN), `hit_rate = 0.57`,
  `p_value = 0.02`. Old code emits `"BUY"`; correct is keep DOWN -> `"SELL"`. *(Req 1.3, 2.5)*
- **DOWN-base, contrarian (preserved)**: `distribution` (base DOWN), `hit_rate = 0.40`,
  `p_value = 0.01`. Invert DOWN -> UP -> `"BUY"`. Unchanged. *(Req 2.4, 3.3)*
- **UP-base, strong-signal (preserved)**: `accumulation` (base UP), `hit_rate = 0.62`,
  `p_value = 0.01`. Keep UP -> `"BUY"`. Unchanged. *(Req 2.3)*
- **Noise band (preserved)**: `hit_rate = 0.50`, `p_value = 0.01` -> `{"adjusted_direction": "NONE"}`.
  Unchanged. *(Req 3.1)*
- **Not significant (preserved)**: `hit_rate = 0.40`, `p_value = 0.20` ->
  `{"adjusted_direction": "NONE"}`. Unchanged. *(Req 3.2)*
- **Unknown signal_type (preserved, no raise)**: `signal_type = "mystery_signal"`,
  `hit_rate = 0.62`, `p_value = 0.01` -> `{"adjusted_direction": "NONE"}`, never raises. *(Req 2.6)*

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- DOWN-base contrarian signals continue to emit `adjusted_direction = "BUY"` (the AAPL case:
  `distribution`, `strong_bearish`, `dss_bearish` all sub-45% -> invert DOWN to BUY). *(Req 3.3)*
- UP-base strong-signal and weak-edge signals continue to emit `adjusted_direction = "BUY"`.
- Every noise-band input (`0.45 <= hit_rate <= 0.55`) continues to return
  `{"adjusted_direction": "NONE"}`. *(Req 3.1)*
- Every input with missing `hit_rate`, missing `p_value`, or `p_value >= SIGNIFICANCE` continues to
  return `{"adjusted_direction": "NONE"}`. *(Req 3.2)*
- `confidence_level` is keyed off the same `hit_rate` thresholds (contrarian: `"High"` if
  `hit_rate < 0.35` else `"Medium-High"`; strong-signal: `"High"`; weak-edge: `"Low-Medium"`), and
  `suggested_hold_days` is still taken from the row's `horizon_days`. *(Req 3.4)*
- `select_row` selection logic is unchanged (lowest significant p-value, tie-broken by larger
  `event_count`, fallback to most events). *(Req 3.5)*
- `build_ticker_config` grouping by `signal_type` and its `{"adjusted_direction": "NONE"}`
  assignment when `select_row` returns None are unchanged. *(Req 3.6)*

**Scope:**
All inputs that do NOT satisfy the bug condition should be completely unaffected by this fix. This
includes:
- DOWN-base contrarian and UP-base strong-signal/weak-edge actionable rules (direction already
  `"BUY"` under correct derivation).
- All noise-band, not-significant, and missing-field inputs (NONE under both old and new code).
- Unknown `signal_type` strings with no `SignalType` or no `SIGNAL_DIRECTIONS` entry (NONE under
  both old and new code).

**Note:** The actual expected correct behaviour for buggy inputs is defined in the Correctness
Properties section (Property 1). This section focuses on what must NOT change.

## Hypothesized Root Cause

Based on the bug description and a read of `scripts/import_ticker_signals.py`, the cause is a
single, well-understood design gap rather than an uncertain defect:

1. **Hardcoded action, no derivation (primary, confirmed by reading the code)**: `get_rule`
   returns a literal `"adjusted_direction": "BUY"` in all three actionable branches and never
   references `SIGNAL_DIRECTIONS`. The emitted action is therefore independent of the signal's base
   direction. This is the root cause.

2. **Base direction not available at the call site**: `get_rule(row: pd.Series)` receives only the
   analysis row. The `signal_type` string is the `groupby` key in `build_ticker_config`
   (`for sig_type, rows in df.groupby("signal_type")`) and is not guaranteed to be a column on the
   chosen row. So even if `get_rule` wanted to derive direction, it currently lacks the input
   needed to resolve the base direction.

3. **Comment encodes an assumption, not a rule**: the existing docstring describes the contrarian
   band as "invert to BUY", which is only correct for DOWN-base signals. The logic silently assumes
   every actionable signal resolves to BUY, which holds for the AAPL signals seen so far but is not
   a derivation.

4. **Unknown-type handling must be defensive**: resolving the string to a `SignalType` via
   `SignalType(signal_type_string)` raises `ValueError` for unrecognised strings, and a recognised
   type could still be absent from `SIGNAL_DIRECTIONS`. The fix must resolve this without raising.

## Correctness Properties

Property 1: Bug Condition - adjusted_direction is derived from base direction and band

_For any_ input where the bug condition holds (`isBugCondition` returns true — a DOWN-base
strong-signal, a DOWN-base weak-edge, or an UP-base contrarian signal), the fixed `get_rule` SHALL
emit `adjusted_direction` derived from the signal's base direction and band: `action(invert(base))`
for the contrarian band and `action(base)` for the strong-signal and weak-edge bands, where
`action` maps `SignalDirection.UP -> "BUY"` and `SignalDirection.DOWN -> "SELL"`. In every such
case the derived value is `"SELL"`.

**Validates: Requirements 2.1, 2.2, 2.5**

Property 2: Preservation - non-buggy inputs behave identically

_For any_ input where the bug condition does NOT hold (`isBugCondition` returns false), the fixed
`get_rule` (and the `build_ticker_config` path that calls it) SHALL produce the same result as the
original function, preserving: DOWN-base contrarian signals (still `"BUY"`), UP-base
strong-signal/weak-edge signals (still `"BUY"`), every noise-band / not-significant / missing-field
input (still `{"adjusted_direction": "NONE"}`), unknown signal types (NONE under both, never
raising), and the unchanged `confidence_level`, `suggested_hold_days`, `select_row`, and
`build_ticker_config` grouping behaviour.

**Validates: Requirements 2.3, 2.4, 2.6, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**

## Fix Implementation

### Changes Required

Assuming the root cause analysis is correct (it is confirmed by reading the code).

**File**: `scripts/import_ticker_signals.py`

**Primary function**: `get_rule`, with a small signature change and two new pure helpers.

**Specific Changes**:

1. **Thread the base direction into rule derivation (chosen approach)**: Resolve the base direction
   in `build_ticker_config` from the `groupby` key and pass it into `get_rule`.

   - `build_ticker_config` already owns the `signal_type` string (`sig_type` loop variable), so it
     is the natural, lowest-coupling place to resolve the base direction. Change the call to
     `get_rule(chosen, base_direction)` where `base_direction = _base_direction(sig_type)`.
   - `get_rule` becomes `get_rule(row: pd.Series, base_direction: SignalDirection | None) -> dict`.

   **Why this approach over the alternative** (passing the raw `signal_type` string into `get_rule`
   and resolving inside): resolving in `build_ticker_config` keeps `get_rule` free of the
   string-to-enum concern, keeps the enum-resolution logic in one place (used once per signal
   type, not per row), and makes `get_rule` directly unit-testable with a `SignalDirection` without
   needing a valid enum string. It also mirrors the existing module boundary — `build_ticker_config`
   is already the function that knows the `signal_type`. The `None` case (unknown type) is resolved
   once, up front, and flows naturally into the existing NONE fallback.

2. **Add a safe base-direction resolver** mirroring the `direction_for` precedent in
   `vpa/backtesting/pnl.py`. A small local helper keeps `scripts/` from importing backtesting
   internals, while reusing the exact `SIGNAL_DIRECTIONS.get(...)` semantics:

   ```
   FUNCTION _base_direction(signal_type_string)
     TRY
       sig_type ← SignalType(signal_type_string)
     EXCEPT ValueError
       RETURN None
     RETURN SIGNAL_DIRECTIONS.get(sig_type)   // None when type has no entry
   END FUNCTION
   ```

   Import `SignalType`, `SignalDirection`, and `SIGNAL_DIRECTIONS` from
   `vpa.ml_validation.signal_analysis`. (Reusing `direction_for` from `vpa.backtesting.pnl` was
   considered but rejected: it does not guard the `SignalType(...)` conversion — it takes a
   `SignalType`, not a string — and importing it would couple the importer script to the
   backtesting package. The local helper adds the string-guard the script needs.)

3. **Add two tiny pure helpers** for the direction-to-action mapping and the inversion:

   ```
   FUNCTION _action(direction)              // SignalDirection -> str
     RETURN "BUY" IF direction = UP ELSE "SELL"
   END FUNCTION

   FUNCTION _invert(direction)              // SignalDirection -> SignalDirection
     RETURN DOWN IF direction = UP ELSE UP
   END FUNCTION
   ```

4. **Derive `adjusted_direction` inside `get_rule`** instead of hardcoding, keeping the band
   structure, confidence levels, and hold-days byte-for-byte:

   ```
   FUNCTION get_rule(row, base_direction)
     hit_rate ← row.get("hit_rate"); p_value ← row.get("p_value")
     hold_days ← int(row["horizon_days"])
     none_rule ← {"adjusted_direction": "NONE"}

     IF hit_rate is NaN OR p_value is NaN OR p_value >= SIGNIFICANCE THEN RETURN none_rule
     IF base_direction = None THEN RETURN none_rule          // unknown type -> NONE (Req 2.6)

     IF hit_rate < 0.45 THEN                                 // contrarian: invert
       direction ← _invert(base_direction)
       RETURN {confidence_level: "High" IF hit_rate < 0.35 ELSE "Medium-High",
               adjusted_direction: _action(direction), suggested_hold_days: hold_days}
     IF hit_rate >= 0.60 THEN                                // strong-signal: keep
       RETURN {confidence_level: "High",
               adjusted_direction: _action(base_direction), suggested_hold_days: hold_days}
     IF 0.55 < hit_rate < 0.60 THEN                          // weak-edge: keep (derived)
       RETURN {confidence_level: "Low-Medium",
               adjusted_direction: _action(base_direction), suggested_hold_days: hold_days}

     RETURN none_rule                                        // 0.45-0.55 noise band
   END FUNCTION
   ```

5. **Update the docstring** to state that the action is derived from the base direction
   (contrarian inverts, strong-signal and weak-edge keep), replacing the "invert to BUY" assumption.

6. **Update the one existing caller** (`build_ticker_config`) to pass the resolved base direction.
   No other module calls `get_rule` (verified: the only external import is the test module
   `vpa/tests/test_ticker_config.py`). `build_ticker_config` keeps its NONE fallback when
   `select_row` returns None unchanged.

**Note on signature change and existing tests**: `vpa/tests/test_ticker_config.py` already exists
and calls `get_rule(row)` with a single argument in `test_get_rule_hold_days_from_horizon` and
`test_get_rule_noise_band_is_none`. Those call sites must be updated to pass a `base_direction`
argument (the Testing Strategy below covers how), and their expectations re-anchored to the derived
behaviour. `build_ticker_config`-level tests that feed a real `signal_type` column
(`test_build_ticker_config_collapses_horizons`) exercise the end-to-end path and should be updated
to reflect derived directions where the band resolves to SELL.

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate
the bug on the unfixed code, then verify the fix derives the correct action and preserves existing
behaviour. Tests live in the existing module `vpa/tests/test_ticker_config.py` (which already
imports `build_ticker_config`, `get_rule`, and `select_row` via the `sys.path.insert` + `from
import_ticker_signals import ...` pattern). The brief's assumption that no test file exists is
incorrect — this file is extended, and its two `get_rule(row)` single-argument call sites are
migrated to the new signature. New direction-derivation cases are added here; `select_row` tests
are untouched (Req 3.5).

Run with the project venv on the FAST path (slow marker deselected):

```
& "d:\projects\trading\.venv\Scripts\python.exe" -m pytest vpa/tests/test_ticker_config.py
```

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm the
root cause: `get_rule` emits `"BUY"` regardless of base direction. If a case unexpectedly passes on
the unfixed code, re-hypothesise.

**Test Plan**: Construct analysis rows for each buggy `(base direction, band)` combination and
assert the derived action is `"SELL"`. Run these against the UNFIXED code to observe them fail
(the unfixed code emits `"BUY"`), confirming the defect and the root cause. Because the unfixed
`get_rule` takes only `row`, the exploratory assertions are expressed at the `build_ticker_config`
level (which carries the `signal_type` string) so they run meaningfully against both old and new
code.

**Test Cases** (expected to FAIL on unfixed code):
1. **DOWN strong-signal -> SELL**: `distribution` (DOWN), `hit_rate = 0.62`, `p_value = 0.01`.
   Expect `"SELL"`; unfixed emits `"BUY"`. *(Req 2.1)*
2. **DOWN weak-edge -> SELL**: `strong_bearish` (DOWN), `hit_rate = 0.57`, `p_value = 0.02`.
   Expect `"SELL"`; unfixed emits `"BUY"`. *(Req 2.5)*
3. **UP contrarian -> SELL**: `accumulation` (UP), `hit_rate = 0.40`, `p_value = 0.01`.
   Expect `"SELL"` (invert UP -> DOWN); unfixed emits `"BUY"`. *(Req 2.2)*

**Expected Counterexamples**:
- The unfixed code returns `"BUY"` for all three, confirming the action is hardcoded and
  independent of `SIGNAL_DIRECTIONS`.

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the
expected derived behaviour.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := get_rule_fixed(input)
  ASSERT expectedBehavior(input, result)   // contrarian: action(invert(base)); else action(base)
END FOR
```

Maps to **Property 1**. Concretely the three exploratory cases above, re-run against the fixed code
and now asserting `"SELL"`, plus a direct `get_rule` call passing `SignalDirection.DOWN`/`UP`:
- `get_rule(row(hit_rate=0.62, p_value=0.01, horizon_days=10), SignalDirection.DOWN)` ->
  `adjusted_direction == "SELL"`, `confidence_level == "High"`, `suggested_hold_days == 10`.
- `get_rule(row(hit_rate=0.57, p_value=0.02, horizon_days=5), SignalDirection.DOWN)` ->
  `"SELL"`, `"Low-Medium"`, `5`.
- `get_rule(row(hit_rate=0.40, p_value=0.01, horizon_days=3), SignalDirection.UP)` ->
  `"SELL"`, `"Medium-High"`, `3`.

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed function
produces the same result as the original function.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT get_rule_original(input) = get_rule_fixed(input)
END FOR
```

Maps to **Property 2**.

**Testing Approach**: Property-based testing (hypothesis, already used in this repo —
`test_pnl.py`, `test_metrics.py`, `test_dss_bressert_properties.py`) is a good fit for preservation
because it generates many inputs across the domain and catches edge cases. Given the small, closed
input space here, one focused property test plus explicit examples is proportional — avoid
over-engineering a large generator suite for a single-function change.

**Test Plan**: Observe behaviour on the UNFIXED code for the preserved cases, then assert the fixed
code matches. For the property test, generate `(base_direction, hit_rate, p_value, horizon_days)`
tuples restricted to the NON-buggy region (the complement of the bug condition) and assert the
derived action equals the old hardcoded result (`"BUY"` for actionable non-buggy bands, `"NONE"`
otherwise).

**Test Cases**:
1. **DOWN contrarian still BUY**: `distribution` (DOWN), `hit_rate = 0.40`, `p_value = 0.01` ->
   `"BUY"` (the AAPL case). *(Req 2.4, 3.3)*
2. **UP strong-signal still BUY**: `accumulation` (UP), `hit_rate = 0.62`, `p_value = 0.01` ->
   `"BUY"`. *(Req 2.3)*
3. **UP weak-edge still BUY**: `accumulation` (UP), `hit_rate = 0.57`, `p_value = 0.02` -> `"BUY"`.
4. **Noise band still NONE**: `hit_rate = 0.50`, `p_value = 0.01` ->
   `{"adjusted_direction": "NONE"}`. *(Req 3.1)*
5. **Not significant still NONE**: `hit_rate = 0.40`, `p_value = 0.20` ->
   `{"adjusted_direction": "NONE"}`. *(Req 3.2)*
6. **Missing hit_rate still NONE**: `hit_rate = NaN`, `p_value = 0.01` ->
   `{"adjusted_direction": "NONE"}`. *(Req 3.2)*
7. **Unknown signal_type -> NONE, no raise**: `build_ticker_config` with
   `signal_type = "mystery_signal"`, `hit_rate = 0.62`, `p_value = 0.01` ->
   `{"adjusted_direction": "NONE"}` and no exception. *(Req 2.6)*
8. **confidence_level / hold_days unchanged**: assert the confidence thresholds and
   `suggested_hold_days` exactly for each actionable band. *(Req 3.4)*
9. **select_row unchanged**: existing `select_row` tests pass unmodified. *(Req 3.5)*
10. **build_ticker_config grouping / NONE fallback unchanged**: a signal type with no usable row
    still gets `{"adjusted_direction": "NONE"}`. *(Req 3.6)*

### Unit Tests

- Fix-Checking cases: DOWN strong-signal -> SELL, DOWN weak-edge -> SELL, UP contrarian -> SELL
  (direct `get_rule` calls with explicit `SignalDirection`).
- Preserved BUY cases: DOWN contrarian, UP strong-signal, UP weak-edge.
- NONE cases: noise band, not significant, missing `hit_rate`.
- Unknown `signal_type` -> NONE via `build_ticker_config`, asserting no exception.
- Confidence-level and `suggested_hold_days` assertions per band (Req 3.4).
- Migrate the two existing single-argument `get_rule(row)` call sites to the new
  `get_rule(row, base_direction)` signature and re-anchor their expectations.

### Property-Based Tests

- One hypothesis property over the NON-buggy input region asserting the fixed `get_rule` matches
  the original hardcoded behaviour (`"BUY"` for non-buggy actionable bands, `"NONE"` otherwise) —
  the Preservation Checking property.
- Optionally, a property over the buggy region asserting the derived action equals
  `action(invert(base))` for contrarian and `action(base)` for strong-signal/weak-edge — the Fix
  Checking property. Keep generators small and the strategy closed over `SIGNAL_DIRECTIONS` keys,
  proportional to this single-function change.

### Integration Tests

- `build_ticker_config` end-to-end over a multi-signal-type, multi-horizon frame: confirm each
  signal type collapses to one rule and that directions are derived (SELL where the band resolves
  to SELL, BUY where it resolves to BUY, NONE otherwise) — exercising `select_row` +
  `_base_direction` + `get_rule` together.
- Update `test_build_ticker_config_collapses_horizons` so the `distribution` DOWN-base contrarian
  case still asserts `"BUY"` (preserved) and add a strong-signal DOWN case asserting `"SELL"`.
- Mixed frame including an unknown `signal_type` column value to confirm the NONE fallback and
  no-raise behaviour flow through the grouping path (Req 2.6, 3.6).
