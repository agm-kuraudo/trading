import argparse
import json
from pathlib import Path

import pandas as pd

from vpa.ml_validation.signal_analysis import SIGNAL_DIRECTIONS, SignalDirection, SignalType

SIGNIFICANCE = 0.05
CONFIG_PATH = Path("vpa/config/ticker_signals.json")


def _base_direction(signal_type_string: str) -> SignalDirection | None:
    """Resolve a signal_type string to its base direction, or None.

    Mirrors the ``direction_for`` precedent in ``vpa/backtesting/pnl.py`` but
    adds a string-to-enum guard: an unrecognised string raises ``ValueError``
    from ``SignalType(...)`` (caught here), and a recognised type may still be
    absent from ``SIGNAL_DIRECTIONS`` (``.get`` returns None). Kept local so the
    importer script stays decoupled from the backtesting package.
    """
    try:
        sig_type = SignalType(signal_type_string)
    except ValueError:
        return None
    return SIGNAL_DIRECTIONS.get(sig_type)


def _action(direction: SignalDirection) -> str:
    """Map a direction to an action string: UP -> BUY, DOWN -> SELL."""
    return "BUY" if direction == SignalDirection.UP else "SELL"


def _invert(direction: SignalDirection) -> SignalDirection:
    """Invert a direction: UP <-> DOWN."""
    return SignalDirection.DOWN if direction == SignalDirection.UP else SignalDirection.UP


def select_row(rows: pd.DataFrame) -> pd.Series | None:
    """Pick the representative horizon row for one signal type.

    The per-ticker analysis CSV holds one row per (signal_type, horizon). We
    collapse those to a single rule by preferring the most statistically
    convincing horizon: lowest significant p-value, tie-broken by the larger
    event_count. If no horizon is significant, fall back to the row with the
    most events so hold-days still reflects real data.
    """
    rows = rows.dropna(subset=["hit_rate"])
    if rows.empty:
        return None

    significant = rows[rows["p_value"].notna() & (rows["p_value"] < SIGNIFICANCE)]
    pool = significant if not significant.empty else rows

    # Sort: p_value ascending (NaN last), then event_count descending.
    pool = pool.sort_values(
        by=["p_value", "event_count"],
        ascending=[True, False],
        na_position="last",
    )
    return pool.iloc[0]


def get_rule(row: pd.Series, base_direction: SignalDirection | None) -> dict:
    """Map a single analysis row to a ticker-signal rule.

    The action is DERIVED from the signal's base direction (passed in) combined
    with the interpretation band, then mapped UP -> "BUY" / DOWN -> "SELL" (via
    ``_action``). It is no longer hardcoded to "BUY". Mirrors the interpretation
    bands used by SignalConditionalAnalyzer:
      - hit_rate < 0.45 (significant): reliable contrarian -> invert the base
        direction (``_invert``), then map to an action
      - hit_rate >= 0.60 (significant): strong signal -> keep the base direction
      - 0.55 < hit_rate < 0.60 (significant): weak edge -> keep the base
        direction (filter only)
      - otherwise (incl. 0.45-0.55 noise band or not significant): no signal
    An unknown signal type (base_direction is None) falls back to NONE rather
    than raising. suggested_hold_days is taken from the horizon that produced
    the row.
    """
    hit_rate = row.get("hit_rate")
    p_value = row.get("p_value")
    hold_days = int(row["horizon_days"])

    none_rule = {"adjusted_direction": "NONE"}

    if pd.isna(hit_rate) or pd.isna(p_value) or p_value >= SIGNIFICANCE:
        return none_rule

    if base_direction is None:
        # Unknown signal type / no base direction -> no actionable signal.
        return none_rule

    if hit_rate < 0.45:
        # Contrarian: the raw signal is wrong often enough to invert.
        return {
            "confidence_level": "High" if hit_rate < 0.35 else "Medium-High",
            "adjusted_direction": _action(_invert(base_direction)),
            "suggested_hold_days": hold_days,
        }
    if hit_rate >= 0.60:
        # Strong signal: keep the base direction.
        return {
            "confidence_level": "High",
            "adjusted_direction": _action(base_direction),
            "suggested_hold_days": hold_days,
        }
    if 0.55 < hit_rate < 0.60:
        # Weak edge: keep the base direction (filter only).
        return {
            "confidence_level": "Low-Medium",
            "adjusted_direction": _action(base_direction),
            "suggested_hold_days": hold_days,
        }

    # 0.45 <= hit_rate <= 0.55: noise band, treat as no actionable signal.
    return none_rule


def build_ticker_config(df: pd.DataFrame) -> dict:
    """Collapse the multi-horizon analysis frame to one rule per signal type."""
    ticker_config: dict = {}
    for sig_type, rows in df.groupby("signal_type"):
        chosen = select_row(rows)
        if chosen is None:
            ticker_config[sig_type] = {"adjusted_direction": "NONE"}
        else:
            base_direction = _base_direction(sig_type)
            ticker_config[sig_type] = get_rule(chosen, base_direction)
    return ticker_config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--analysis-csv", required=True)
    args = parser.parse_args()

    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            config = json.load(f)
    else:
        config = {}

    df = pd.read_csv(args.analysis_csv)
    config[args.ticker.upper()] = build_ticker_config(df)

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    print(f"Updated config for {args.ticker}")


if __name__ == "__main__":
    main()
