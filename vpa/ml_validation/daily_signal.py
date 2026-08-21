"""Daily VPA Signal Generator.

Runs daily after market close, classifies the latest candle using VPA logic,
applies contrarian inversion (bearish VPA -> BUY), and appends structured
signals to a persistent CSV log.
"""

import argparse
import csv
import datetime
import json
import math
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from vpa.app import Candle, calculate_adx, identify_acc_or_dist
from vpa.ml_validation.exceptions import InsufficientDataError
from vpa.ml_validation.feature_extractor import VPAFeatureExtractor
from vpa.ml_validation.signal_analysis import (
    SIGNAL_DIRECTIONS,
    SignalConditionalAnalyzer,
    SignalType,
)

# Import thresholds directly from SignalConditionalAnalyzer (Req 8.4)
COMPOSITE_THRESHOLD: float = SignalConditionalAnalyzer.COMPOSITE_THRESHOLD
ACC_DIST_SCORE_THRESHOLD: float = SignalConditionalAnalyzer.ACC_DIST_SCORE_THRESHOLD


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SignalRecord:
    """A single actionable trading signal produced by the generator."""

    ticker: str  # e.g. "SPY", "AAPL"
    date: str  # ISO 8601 YYYY-MM-DD
    signal_type: str  # e.g. "distribution"
    original_direction: str  # "up" or "down"
    adjusted_direction: str  # Always "BUY" for actionable signals
    confidence_level: str  # "High", "Medium-High", "Low-Medium", "Low"
    suggested_hold_days: int  # Always 10


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONFIDENCE_MAP: dict[SignalType, str] = {
    SignalType.DISTRIBUTION: "High",
    SignalType.STRONG_BEARISH: "Medium-High",
    SignalType.STRONG_BULLISH: "Low-Medium",
    SignalType.ACCUMULATION: "Low",
}

CONFIDENCE_ORDER: list[str] = ["High", "Medium-High", "Low-Medium", "Low"]

EXCLUDED_SIGNALS: set[SignalType] = {SignalType.ACCUMULATION_TEST_PASS}

CSV_COLUMNS: list[str] = [
    "ticker",
    "date",
    "signal_type",
    "original_direction",
    "adjusted_direction",
    "confidence_level",
    "suggested_hold_days",
]


# ---------------------------------------------------------------------------
# Signal Building
# ---------------------------------------------------------------------------


def build_signal_records(ticker: str, date: str, signal_types: set[SignalType]) -> list[SignalRecord]:
    """Build sorted SignalRecords from classified signal types.

    Filters out excluded signals (ACCUMULATION_TEST_PASS), creates one
    SignalRecord per remaining type with contrarian inversion (all signals
    become BUY), and sorts by confidence descending (High first).

    Args:
        ticker: The ticker symbol (e.g. "SPY", "AAPL").
        date: ISO 8601 date string (YYYY-MM-DD) for the signal.
        signal_types: Set of classified SignalType values from the latest candle.

    Returns:
        List of SignalRecord sorted by confidence (High → Low), empty if no
        actionable signals remain after filtering.
    """
    actionable = signal_types - EXCLUDED_SIGNALS

    records: list[SignalRecord] = []
    for sig_type in actionable:
        records.append(
            SignalRecord(
                ticker=ticker,
                date=date,
                signal_type=sig_type.value,
                original_direction=SIGNAL_DIRECTIONS[sig_type].value,
                adjusted_direction="BUY",
                confidence_level=CONFIDENCE_MAP[sig_type],
                suggested_hold_days=10,
            )
        )

    records.sort(key=lambda r: CONFIDENCE_ORDER.index(r.confidence_level))
    return records


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify_last_row(df: pd.DataFrame) -> set[SignalType]:
    """Classify the final row of a feature DataFrame into VPA signal types.

    Extracts composite_score, acc_dist_flag, acc_dist_type, and acc_dist_score
    from the last row and applies threshold logic to determine which signal
    types are active.

    Returns an empty set if relevant fields are NaN or no thresholds are met.
    """
    if df.empty:
        return set()

    last_row = df.iloc[-1]

    # Extract relevant fields
    composite_score = last_row.get("composite_score")
    acc_dist_flag = last_row.get("acc_dist_flag")
    acc_dist_type = last_row.get("acc_dist_type")
    acc_dist_score = last_row.get("acc_dist_score")

    signals: set[SignalType] = set()

    # --- Composite score thresholds ---
    # Check composite_score is numeric and not NaN
    if composite_score is not None and not (isinstance(composite_score, float) and math.isnan(composite_score)):
        score = float(composite_score)
        if not math.isnan(score):
            if score >= COMPOSITE_THRESHOLD:
                signals.add(SignalType.STRONG_BULLISH)
            if score <= -COMPOSITE_THRESHOLD:
                signals.add(SignalType.STRONG_BEARISH)

    # --- Accumulation / Distribution thresholds ---
    # All acc_dist fields must be non-NaN for these checks
    def _is_valid_numeric(val: object) -> bool:
        """Return True if val is a non-NaN numeric value."""
        if val is None:
            return False
        try:
            return not math.isnan(float(val))
        except (TypeError, ValueError):
            return False

    if _is_valid_numeric(acc_dist_flag) and _is_valid_numeric(acc_dist_type):
        flag = float(acc_dist_flag)
        dtype = float(acc_dist_type)

        if flag == 1 and dtype == 1:
            signals.add(SignalType.ACCUMULATION)

            # ACCUMULATION_TEST_PASS requires additional score threshold
            if _is_valid_numeric(acc_dist_score):
                score_val = float(acc_dist_score)
                if score_val >= ACC_DIST_SCORE_THRESHOLD:
                    signals.add(SignalType.ACCUMULATION_TEST_PASS)

        elif flag == 1 and dtype == -1:
            signals.add(SignalType.DISTRIBUTION)

    return signals


# ---------------------------------------------------------------------------
# Generator Class
# ---------------------------------------------------------------------------

# Minimum rows required for valid VPA feature extraction
_MIN_VALID_ROWS: int = 50


class DailySignalGenerator:
    """Orchestrates daily VPA signal generation for a single ticker.

    Downloads recent OHLCV data, processes it through the VPA feature pipeline,
    classifies the latest candle, and returns actionable SignalRecords.
    """

    # Config path relative to working directory (matches Req 8.1)
    _CONFIG_PATH: str = str(Path("vpa") / "config" / "config.json")

    def __init__(
        self,
        output_dir: Path,
        lookback_days: int = 200,
        ticker: str = "SPY",
    ) -> None:
        """Initialise the generator.

        Args:
            output_dir: Directory for signal log output.
            lookback_days: Calendar days of OHLCV history to download.
            ticker: Ticker symbol to analyse (any yfinance-supported symbol).
        """
        self.output_dir = output_dir
        self.lookback_days = lookback_days
        self.ticker = ticker

    def run(self) -> list[SignalRecord]:
        """Execute the full signal generation pipeline.

        1. Load VPA config
        2. Download OHLCV data via yfinance
        3. Process through VPA rolling-window feature extraction
        4. Validate ≥50 valid rows
        5. Classify the final row's feature vector
        6. Build contrarian-inverted SignalRecords

        Returns:
            List of SignalRecord (may be empty if no signals fire).

        Raises:
            InsufficientDataError: If config is missing, yfinance returns
                insufficient data, or < 50 valid rows after processing.
        """
        # --- Step 1: Load configuration ---
        config_path = Path(self._CONFIG_PATH)
        if not config_path.exists():
            raise InsufficientDataError(
                f"Configuration file not found: {config_path}. "
                f"Ensure vpa/config/config.json exists in the working directory."
            )

        try:
            with open(config_path, encoding="utf-8") as f:
                config = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            raise InsufficientDataError(f"Failed to load configuration from {config_path}: {exc}") from exc

        period_one_length: int = config["PERIOD_ONE_LENGTH"]
        period_two_length: int = config["PERIOD_TWO_LENGTH"]
        period_three_length: int = config["PERIOD_THREE_LENGTH"]
        percentile_start: int = config["PERCENTILE_START"]
        percentile_increments: int = config["PERCENTILE_INCREMENTS"]

        # --- Step 2: Download OHLCV data ---
        end_date = datetime.datetime.now().date()
        start_date = end_date - datetime.timedelta(days=self.lookback_days)

        try:
            df = yf.download(
                self.ticker,
                start=start_date,
                end=end_date,
                auto_adjust=True,
                progress=False,
            )
        except Exception as exc:
            raise InsufficientDataError(f"Failed to download data for {self.ticker}: {exc}") from exc

        if df is None or df.empty:
            raise InsufficientDataError(
                f"No data returned from yfinance for ticker '{self.ticker}'. "
                f"The ticker may be invalid or the data source unavailable."
            )

        # Reset index so Date becomes a column
        df = df.reset_index()

        # Normalise column names (yfinance may return MultiIndex for single ticker)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] if col[1] == "" else col[0] for col in df.columns]

        # Handle case-insensitive column matching
        required_cols = ["Date", "Open", "High", "Low", "Close", "Volume"]
        col_map = {c.lower(): c for c in df.columns}
        rename_map = {}
        for rc in required_cols:
            if rc not in df.columns and rc.lower() in col_map:
                rename_map[col_map[rc.lower()]] = rc
        if rename_map:
            df = df.rename(columns=rename_map)

        # --- Step 3: Drop NaN rows in OHLCV columns ---
        ohlcv_cols = ["Open", "High", "Low", "Close", "Volume"]
        df = df.dropna(subset=ohlcv_cols)

        # Validate minimum rows BEFORE processing (Req 1.2)
        if len(df) < _MIN_VALID_ROWS:
            raise InsufficientDataError(
                f"Insufficient data for {self.ticker}: only {len(df)} valid rows "
                f"found after NaN removal (minimum {_MIN_VALID_ROWS} required)."
            )

        # --- Step 4: Sort by date ascending (Req 1.5) ---
        df = df.sort_values("Date").reset_index(drop=True)

        # --- Step 5: Process through VPA rolling-window logic ---
        # Instantiate extractor for access to internal methods
        extractor = VPAFeatureExtractor(
            config_path=str(config_path),
            ticker_symbol=self.ticker,
            enable_extraction=True,
        )

        deque_dictionary = {
            "period_one": deque(maxlen=period_one_length),
            "period_two": deque(maxlen=period_two_length),
            "period_three": deque(maxlen=period_three_length),
        }

        percentiles_store: dict[str, dict] = {"spread": {}, "volume": {}}
        feature_rows: list[dict] = []
        previous_close: float = 0

        for _, row in df.iterrows():
            # Create Candle (matching MarketAnalyzer open-price logic)
            if previous_close != 0:
                open_price = previous_close
            else:
                open_price = float(row["Open"])

            high = max(float(row["High"]), open_price)
            low = min(float(row["Low"]), open_price)

            this_candle = Candle(
                row["Date"],
                float(row["Volume"]),
                open_price,
                high,
                low,
                float(row["Close"]),
            )
            previous_close = this_candle.close

            # Add to all rolling windows
            for key in deque_dictionary:
                deque_dictionary[key].append(this_candle)

            # Skip until period_three is full (warm-up)
            if len(deque_dictionary["period_three"]) < period_three_length:
                continue

            # Update percentiles (replicates MarketAnalyzer.update_percentiles)
            props = ["spread", "volume"]
            for prop in props:
                for key in deque_dictionary:
                    stats_list = [getattr(item, prop) for item in deque_dictionary[key]]
                    percentiles_store[prop][key] = np.percentile(
                        stats_list,
                        list(range(percentile_start, 100, percentile_increments)),
                    )

            # Assign percentiles to candles in each deque
            for key in deque_dictionary:
                for candle in deque_dictionary[key]:
                    for prop in props:
                        upper_percentile = percentile_start
                        for step in percentiles_store[prop][key]:
                            if getattr(candle, prop) <= step:
                                upper_percentile += percentile_increments
                        if prop == "spread":
                            candle.spread_percentiles[key] = upper_percentile
                        elif prop == "volume":
                            candle.volume_percentiles[key] = upper_percentile

            # Detect signals
            signals = extractor._detect_signals(this_candle, deque_dictionary)

            # Calculate ADX
            adx_values = calculate_adx(list(deque_dictionary["period_three"]))

            # Identify accumulation/distribution
            acc_dist_result = identify_acc_or_dist(
                list(deque_dictionary["period_three"]),
                list(deque_dictionary["period_one"]),
            )

            # Extract feature vector
            feature_vector = extractor._extract_feature_vector(
                candle=this_candle,
                signals=signals,
                adx_values=adx_values,
                acc_dist_result=acc_dist_result,
                deque_dictionary=deque_dictionary,
            )

            # Add metadata
            date_val = row["Date"]
            if hasattr(date_val, "isoformat"):
                date_str = date_val.isoformat()
            else:
                date_str = str(date_val)

            feature_vector["date"] = date_str
            feature_vector["close"] = float(row["Close"])

            feature_rows.append(feature_vector)

        # --- Step 6: Validate feature extraction produced results (Req 2.5) ---
        if not feature_rows:
            raise InsufficientDataError(
                f"No valid feature rows could be extracted for {self.ticker}. "
                f"All rows were consumed by the warm-up period "
                f"({period_three_length} candles)."
            )

        result_df = pd.DataFrame(feature_rows)

        # --- Step 7: Classify the final row ---
        signal_types = classify_last_row(result_df)

        # --- Step 8: Determine signal date (latest date, Req 1.5) ---
        signal_date = result_df.iloc[-1]["date"]
        # Ensure it's a plain date string (YYYY-MM-DD)
        if hasattr(signal_date, "strftime"):
            signal_date = signal_date.strftime("%Y-%m-%d")
        else:
            signal_date = str(signal_date)[:10]

        # --- Step 9: Build contrarian-inverted signal records ---
        records = build_signal_records(self.ticker, signal_date, signal_types)

        return records


# ---------------------------------------------------------------------------
# Console Output
# ---------------------------------------------------------------------------


def print_signals(ticker: str, date: str, records: list[SignalRecord]) -> None:
    """Print signal records to stdout in a human-readable format.

    Always prints a header with the ticker and date. If records is non-empty,
    prints each record with labelled fields. If empty, prints a no-signal
    message including the ticker and date.

    Args:
        ticker: The ticker symbol (e.g. "SPY").
        date: ISO 8601 date string (YYYY-MM-DD) for the signal.
        records: List of SignalRecord to display (may be empty).
    """
    header = f"VPA Daily Signal \u2014 {ticker} ({date})"
    separator = "=" * 50

    print(header)
    print(separator)

    if not records:
        print("No high-conviction signal today")
        return

    for i, record in enumerate(records):
        print(f"  Signal Type:      {record.signal_type}")
        print(f"  Original Dir:     {record.original_direction}")
        print(f"  Adjusted Dir:     {record.adjusted_direction}")
        print(f"  Confidence:       {record.confidence_level}")
        print(f"  Hold Days:        {record.suggested_hold_days}")
        if i < len(records) - 1:
            print("-" * 50)


# ---------------------------------------------------------------------------
# CSV Logging
# ---------------------------------------------------------------------------


def append_to_log(records: list[SignalRecord], log_path: Path) -> None:
    """Append signal records to a persistent CSV log with deduplication.

    Creates the log file (with header) if it doesn't exist, or appends new
    records that don't already appear in the file. Deduplication is based on
    the (ticker, date, signal_type) composite key.

    Does nothing if records is empty.

    Args:
        records: List of SignalRecord to persist (may be empty).
        log_path: Path to the CSV log file. Parent directories are created
            if they don't exist.

    Raises:
        OSError: If file system operations fail (permissions, disk full, etc.).
            Errors are allowed to propagate to the caller.
    """
    if not records:
        return

    # Ensure parent directories exist (Req 6.7, 9.1)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Determine existing keys for deduplication (Req 6.1)
    existing_keys: set[tuple[str, str, str]] = set()
    if log_path.exists():
        with open(log_path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = (row["ticker"], row["date"], row["signal_type"])
                existing_keys.add(key)

    # Filter out duplicates
    new_records = [r for r in records if (r.ticker, r.date, r.signal_type) not in existing_keys]

    if not new_records:
        return

    # Write header if file doesn't exist, then append data (Req 6.3, 6.4, 9.4)
    file_exists = log_path.exists()
    with open(log_path, mode="a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(CSV_COLUMNS)
        for record in new_records:
            writer.writerow(
                [
                    record.ticker,
                    record.date,
                    record.signal_type,
                    record.original_direction,
                    record.adjusted_direction,
                    record.confidence_level,
                    record.suggested_hold_days,
                ]
            )


# ---------------------------------------------------------------------------
# CLI Argument Parsing
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for the daily signal generator.

    Args:
        argv: Argument list (defaults to sys.argv[1:] if None).

    Returns:
        Namespace with output_dir, lookback_days, and ticker attributes.

    Raises:
        SystemExit: With code 2 if arguments are invalid or --lookback-days
            is outside [70, 3650].
    """
    parser = argparse.ArgumentParser(
        description="Daily VPA Signal Generator — classify the latest candle and log actionable signals.",
    )
    parser.add_argument(
        "--output-dir",
        default="ml_validation_output",
        help="Directory for signal log output (default: ml_validation_output)",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=200,
        help="Calendar days of OHLCV history to download (default: 200, range: 70-3650)",
    )
    parser.add_argument(
        "--ticker",
        default="SPY",
        help="Ticker symbol to analyse (default: SPY)",
    )

    args = parser.parse_args(argv)

    # Validate lookback-days range (Req 7.3, 7.6)
    if args.lookback_days < 70 or args.lookback_days > 3650:
        print(
            f"Error: --lookback-days must be between 70 and 3650 (got {args.lookback_days})",
            file=sys.stderr,
        )
        sys.exit(2)

    return args


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the daily VPA signal generation pipeline from CLI arguments.

    Parses arguments, runs the signal generator, prints results to stdout,
    and appends to the CSV log. Exits with code 0 on success, 1 on fatal
    errors (data/config/IO), or 2 on invalid arguments.
    """
    args = parse_args()

    output_dir = Path(args.output_dir)
    log_path = output_dir / f"{args.ticker.lower()}_daily_signals.csv"

    try:
        generator = DailySignalGenerator(
            output_dir=output_dir,
            lookback_days=args.lookback_days,
            ticker=args.ticker,
        )
        records = generator.run()

        # Determine signal date for display
        signal_date = records[0].date if records else datetime.datetime.now().date().isoformat()

        print_signals(args.ticker, signal_date, records)
        append_to_log(records, log_path)

    except InsufficientDataError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except OSError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
