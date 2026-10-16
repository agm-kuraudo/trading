# Bugfix Requirements Document

## Introduction

The per-ticker config importer `scripts/import_ticker_signals.py` (function `get_rule`) hardcodes
`"adjusted_direction": "BUY"` for every actionable signal band instead of deriving the direction
from the signal's real base direction. The code comment assumes a contrarian/bearish inversion,
which happens to be correct for the signals observed so far (`distribution`, `strong_bearish`,
`dss_bearish` all have sub-45% hit rates on AAPL, so inverting their DOWN base to BUY is right),
but this is an assumption rather than a derivation.

The project already models signal base directions in `SIGNAL_DIRECTIONS` (a
`dict[SignalType, SignalDirection]` in `vpa/ml_validation/signal_analysis.py`), with `SignalDirection.UP`
and `SignalDirection.DOWN` entries. The correct `adjusted_direction` is a function of the signal's
base direction combined with the interpretation band (contrarian inverts, strong-signal keeps), mapped
to an action string (`UP -> "BUY"`, `DOWN -> "SELL"`). Because `get_rule` ignores the base direction and
always emits `"BUY"`, it produces the wrong action for any signal whose base direction and band should
resolve to SELL.

This bug surfaces whenever a signal's `(base direction, band)` combination should yield SELL:
a DOWN-base signal in the strong-signal band (should keep DOWN -> SELL) and an UP-base signal in the
contrarian band (should invert to DOWN -> SELL) both currently emit `"BUY"`. The fix derives the
direction from `SIGNAL_DIRECTIONS` rather than hardcoding it. This ticket is tracked as Jira SP-360.

## Bug Analysis

### Current Behavior (Defect)

`get_rule` hardcodes `"BUY"` for all three actionable bands and never consults `SIGNAL_DIRECTIONS`,
so the emitted action is independent of the signal's real base direction.

1.1 WHEN a signal's base direction is DOWN and its hit_rate is in the strong-signal band (hit_rate >= 0.60, significant) THEN the system emits `adjusted_direction` = "BUY" instead of "SELL"
1.2 WHEN a signal's base direction is UP and its hit_rate is in the contrarian band (hit_rate < 0.45, significant) THEN the system emits `adjusted_direction` = "BUY" instead of "SELL" (the inverted direction)
1.3 WHEN a signal's hit_rate is in the weak-edge band (0.55 < hit_rate < 0.60, significant) THEN the system emits a hardcoded `adjusted_direction` = "BUY" regardless of the signal's base direction
1.4 WHEN the importer processes a row THEN the system derives `adjusted_direction` without mapping the grouped `signal_type` string back to a `SignalType` and without looking up `SIGNAL_DIRECTIONS`

### Expected Behavior (Correct)

The `adjusted_direction` must be derived from the signal's base direction (resolved from
`SIGNAL_DIRECTIONS` via the `signal_type` string) combined with the band, then mapped to an action
string: `SignalDirection.UP -> "BUY"`, `SignalDirection.DOWN -> "SELL"`.

2.1 WHEN a signal's base direction is DOWN and its hit_rate is in the strong-signal band (hit_rate >= 0.60, significant) THEN the system SHALL keep the base direction and emit `adjusted_direction` = "SELL"
2.2 WHEN a signal's base direction is UP and its hit_rate is in the contrarian band (hit_rate < 0.45, significant) THEN the system SHALL invert the base direction and emit `adjusted_direction` = "SELL"
2.3 WHEN a signal's base direction is UP and its hit_rate is in the strong-signal band (hit_rate >= 0.60, significant) THEN the system SHALL keep the base direction and emit `adjusted_direction` = "BUY"
2.4 WHEN a signal's base direction is DOWN and its hit_rate is in the contrarian band (hit_rate < 0.45, significant) THEN the system SHALL invert the base direction and emit `adjusted_direction` = "BUY"
2.5 WHEN a signal's hit_rate is in the weak-edge band (0.55 < hit_rate < 0.60, significant) THEN the system SHALL derive `adjusted_direction` from the signal's base direction (keeping it, consistent with the strong-signal band) rather than hardcoding "BUY", mapping UP -> "BUY" and DOWN -> "SELL"
2.6 WHEN the `signal_type` string has no corresponding `SignalType` or no entry in `SIGNAL_DIRECTIONS` THEN the system SHALL fall back to a rule with `adjusted_direction` = "NONE" rather than raising an exception

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a signal's hit_rate is in the noise band (0.45 <= hit_rate <= 0.55) THEN the system SHALL CONTINUE TO return `{"adjusted_direction": "NONE"}`
3.2 WHEN a signal's p_value is missing or not significant (p_value >= SIGNIFICANCE) or hit_rate is missing THEN the system SHALL CONTINUE TO return `{"adjusted_direction": "NONE"}`
3.3 WHEN a signal's base direction is DOWN and its hit_rate is in the contrarian band (hit_rate < 0.45, significant) — the case exercised by the AAPL signals seen so far (`distribution`, `strong_bearish`, `dss_bearish`) — THEN the system SHALL CONTINUE TO emit `adjusted_direction` = "BUY"
3.4 WHEN an actionable rule is produced THEN the system SHALL CONTINUE TO include `confidence_level` and `suggested_hold_days`, with `confidence_level` keyed off the same hit_rate thresholds as today (contrarian: "High" if hit_rate < 0.35 else "Medium-High"; strong-signal: "High"; weak-edge: "Low-Medium") and `suggested_hold_days` taken from the row's `horizon_days`
3.5 WHEN `select_row` chooses the representative horizon for a signal type THEN the system SHALL CONTINUE TO use the existing selection logic (lowest significant p-value, tie-broken by larger event_count, falling back to most events when none are significant)
3.6 WHEN `build_ticker_config` groups the frame by `signal_type` and a signal type has no usable row (`select_row` returns None) THEN the system SHALL CONTINUE TO assign `{"adjusted_direction": "NONE"}` for that signal type

## Bug Condition and Properties

### Key Definitions

- **F**: the original `get_rule` (and the `build_ticker_config` path that calls it) before the fix.
- **F'**: the fixed `get_rule` that derives `adjusted_direction` from `SIGNAL_DIRECTIONS` and the band.
- **X**: the input to the rule derivation — the chosen analysis `row` (carrying `hit_rate`, `p_value`,
  `horizon_days`) together with its `signal_type` string, from which the base direction is resolved.
- **base(X)**: the signal's base direction, `SIGNAL_DIRECTIONS.get(SignalType(X.signal_type))`,
  or `None` when the type is unknown / has no entry.
- **band(X)**: the interpretation band derived from `hit_rate`/`p_value`
  (contrarian | strong-signal | weak-edge | noise/none).
- **invert(d)**: `UP -> DOWN`, `DOWN -> UP`.
- **action(d)**: `UP -> "BUY"`, `DOWN -> "SELL"`.

### Bug Condition Function

```pascal
FUNCTION isBugCondition(X)
  INPUT:  X = (signal_type string, hit_rate, p_value, horizon_days)
  OUTPUT: boolean

  // Only actionable, significant bands can be mislabelled; NONE bands are unaffected.
  IF base(X) = None THEN
    RETURN false            // unknown type -> NONE under both F and F' (see preservation)
  END IF

  IF band(X) = contrarian THEN
    expected ← action(invert(base(X)))
  ELSE IF band(X) = strong-signal OR band(X) = weak-edge THEN
    expected ← action(base(X))
  ELSE
    RETURN false            // noise / not-significant -> NONE, no direction emitted
  END IF

  // F always emits "BUY" for actionable bands; the bug is any input whose
  // correctly-derived action is not "BUY".
  RETURN expected ≠ "BUY"
END FUNCTION
```

Concretely, `isBugCondition(X)` is true for:
- a DOWN-base signal in the strong-signal band (expected "SELL"),
- a DOWN-base signal in the weak-edge band (expected "SELL"),
- an UP-base signal in the contrarian band (expected "SELL").

### Fix Checking Property

```pascal
// Property: Fix Checking - adjusted_direction is derived, not hardcoded
FOR ALL X WHERE isBugCondition(X) DO
  result ← getRule'(X)
  IF band(X) = contrarian THEN
    ASSERT result.adjusted_direction = action(invert(base(X)))
  ELSE                         // strong-signal or weak-edge
    ASSERT result.adjusted_direction = action(base(X))
  END IF
END FOR
```

### Preservation Checking Property

```pascal
// Property: Preservation Checking - non-buggy inputs behave identically
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT getRule(X) = getRule'(X)
END FOR
```

This preserves: DOWN-base contrarian signals (still "BUY"), UP-base strong-signal/weak-edge signals
(still "BUY"), every noise/not-significant input (still `{"adjusted_direction": "NONE"}`), unknown
signal types (NONE under both), and the unchanged `confidence_level`, `suggested_hold_days`,
`select_row`, and `build_ticker_config` grouping behaviour.
