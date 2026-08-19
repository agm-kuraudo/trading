"""VPA Signal-Conditional Analysis module.

Isolates high-conviction VPA signal events and measures their directional
hit rate over 3, 5, and 10 trading-day forward-return horizons across
multiple tickers.
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats

from vpa.ml_validation.exceptions import InsufficientDataError


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SignalType(Enum):
    """High-conviction VPA signal event categories."""

    STRONG_BULLISH = "strong_bullish"
    STRONG_BEARISH = "strong_bearish"
    ACCUMULATION = "accumulation"
    DISTRIBUTION = "distribution"
    ACCUMULATION_TEST_PASS = "accumulation_test_pass"


class SignalDirection(Enum):
    """Expected price direction for a signal type."""

    UP = "up"
    DOWN = "down"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SIGNAL_DIRECTIONS: dict[SignalType, SignalDirection] = {
    SignalType.STRONG_BULLISH: SignalDirection.UP,
    SignalType.STRONG_BEARISH: SignalDirection.DOWN,
    SignalType.ACCUMULATION: SignalDirection.UP,
    SignalType.DISTRIBUTION: SignalDirection.DOWN,
    SignalType.ACCUMULATION_TEST_PASS: SignalDirection.UP,
}

FORWARD_HORIZONS: list[int] = [3, 5, 10]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SignalMetrics:
    """Per-signal-type, per-horizon metrics for a single ticker."""

    signal_type: SignalType
    horizon_days: int
    event_count: int
    hit_rate: Optional[float]
    base_rate: Optional[float]
    p_value: Optional[float]
    ci_lower: Optional[float]
    ci_upper: Optional[float]
    avg_win: Optional[float]
    avg_loss: Optional[float]
    profit_factor: Optional[float]
    signals_per_year: Optional[float]


@dataclass(frozen=True)
class CrossTickerSummary:
    """Aggregated metrics across all tickers for a signal type and horizon."""

    signal_type: SignalType
    horizon_days: int
    median_hit_rate: Optional[float]
    mean_hit_rate: Optional[float]
    significant_ticker_count: int
    total_ticker_count: int
    median_profit_factor: Optional[float]
    best_ticker: Optional[str]
    best_hit_rate: Optional[float]
    worst_ticker: Optional[str]
    worst_hit_rate: Optional[float]
    conclusion: str


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


class SignalConditionalAnalyzer:
    """Signal-conditional statistical analysis pipeline.

    Processes feature datasets for each ticker in the universe, applies signal
    filters, computes forward returns and hit-rate metrics, performs statistical
    significance testing, and writes structured output artefacts.
    """

    TICKER_UNIVERSE: list[str] = [
        "SPY", "AAPL", "MSFT", "NVDA", "TSLA",
        "AMD", "KO", "JNJ", "CAT", "BA", "XOM",
    ]
    COMPOSITE_THRESHOLD: float = 15.0
    ACC_DIST_SCORE_THRESHOLD: float = 15.0
    MIN_EVENTS_FOR_STATS: int = 5
    MIN_ROWS_FOR_ANALYSIS: int = 2
    BOOTSTRAP_RESAMPLES: int = 10000
    BOOTSTRAP_SEED: int = 42

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = Path(output_dir)

    def load_dataset(self, ticker: str) -> pd.DataFrame:
        """Load and clean a ticker's feature dataset.

        Reads the CSV, sorts by date ascending, drops rows with NaN close,
        and raises InsufficientDataError if fewer than MIN_ROWS_FOR_ANALYSIS
        rows remain.
        """
        if ticker == "SPY":
            csv_path = self.output_dir / f"{ticker}_vpa_features.csv"
        else:
            csv_path = self.output_dir / ticker / f"{ticker}_vpa_features.csv"

        df = pd.read_csv(csv_path)
        df = df.sort_values("date", ascending=True).reset_index(drop=True)
        df = df.dropna(subset=["close"]).reset_index(drop=True)

        if len(df) < self.MIN_ROWS_FOR_ANALYSIS:
            raise InsufficientDataError(
                f"Ticker {ticker} has {len(df)} usable rows "
                f"(minimum {self.MIN_ROWS_FOR_ANALYSIS} required)"
            )

        return df

    def classify_signals(self, df: pd.DataFrame) -> dict[SignalType, list[int]]:
        """Apply signal filters to each row and return matched indices per type.

        NaN fields cause the row to be excluded from filters that depend on
        them. A single row may appear in multiple signal type lists.
        """
        result: dict[SignalType, list[int]] = {st: [] for st in SignalType}

        # Pre-compute notna masks for relevant columns
        composite_valid = df["composite_score"].notna()
        acc_flag_valid = df["acc_dist_flag"].notna()
        acc_type_valid = df["acc_dist_type"].notna()
        acc_score_valid = df["acc_dist_score"].notna()

        # Strong Bullish: composite_score >= threshold (NaN excluded)
        strong_bullish_mask = composite_valid & (
            df["composite_score"] >= self.COMPOSITE_THRESHOLD
        )
        result[SignalType.STRONG_BULLISH] = df.index[strong_bullish_mask].tolist()

        # Strong Bearish: composite_score <= -threshold (NaN excluded)
        strong_bearish_mask = composite_valid & (
            df["composite_score"] <= -self.COMPOSITE_THRESHOLD
        )
        result[SignalType.STRONG_BEARISH] = df.index[strong_bearish_mask].tolist()

        # Accumulation: acc_dist_flag == 1 AND acc_dist_type == 1
        acc_base_mask = (
            acc_flag_valid
            & acc_type_valid
            & (df["acc_dist_flag"] == 1)
            & (df["acc_dist_type"] == 1)
        )
        result[SignalType.ACCUMULATION] = df.index[acc_base_mask].tolist()

        # Distribution: acc_dist_flag == 1 AND acc_dist_type == -1
        dist_mask = (
            acc_flag_valid
            & acc_type_valid
            & (df["acc_dist_flag"] == 1)
            & (df["acc_dist_type"] == -1)
        )
        result[SignalType.DISTRIBUTION] = df.index[dist_mask].tolist()

        # Accumulation Test Pass: accumulation conditions + acc_dist_score >= threshold
        acc_test_pass_mask = (
            acc_base_mask
            & acc_score_valid
            & (df["acc_dist_score"] >= self.ACC_DIST_SCORE_THRESHOLD)
        )
        result[SignalType.ACCUMULATION_TEST_PASS] = df.index[
            acc_test_pass_mask
        ].tolist()

        return result

    def compute_forward_returns(
        self, df: pd.DataFrame, indices: list[int], horizon: int
    ) -> np.ndarray:
        """Compute forward returns for signal events at the given horizon.

        Excludes events with insufficient future data or zero close price.
        Returns array of float forward returns: close[t+N] / close[t] - 1.
        """
        if not indices:
            return np.array([], dtype=np.float64)

        close = df["close"].values
        n = len(close)

        # Convert to numpy array for vectorized filtering
        idx = np.array(indices, dtype=np.intp)

        # Filter: index + horizon < len(df) (sufficient future data)
        valid_mask = (idx + horizon) < n

        # Filter: close[t] != 0 (avoid division by zero)
        valid_mask &= close[idx] != 0

        # Filter: close[t+horizon] is not NaN
        # Only check future close for indices that still pass prior filters
        future_idx = idx + horizon
        # Clamp future_idx for safe indexing (filtered out by valid_mask anyway)
        safe_future_idx = np.where(future_idx < n, future_idx, 0)
        valid_mask &= ~np.isnan(close[safe_future_idx])

        # Apply mask and compute returns vectorized
        valid_idx = idx[valid_mask]
        if len(valid_idx) == 0:
            return np.array([], dtype=np.float64)

        returns = close[valid_idx + horizon] / close[valid_idx] - 1.0
        return returns

    def compute_base_rate(self, df: pd.DataFrame, horizon: int) -> float:
        """Compute unconditional base rate of positive forward returns.

        Uses ALL rows in the dataset (not just signal rows) that have
        sufficient future data for the given horizon.
        """
        close_arr = df["close"].values
        n = len(close_arr)

        if n <= horizon:
            return 0.5

        fwd_returns = close_arr[horizon:] / close_arr[: n - horizon] - 1
        positive_count = np.sum(fwd_returns > 0)
        total_count = len(fwd_returns)

        if total_count == 0:
            return 0.5

        return float(positive_count / total_count)

    def compute_metrics(
        self,
        returns: np.ndarray,
        signal_type: SignalType,
        horizon: int,
        base_rate: float,
        dataset_years: float,
    ) -> SignalMetrics:
        """Compute hit rate, avg win/loss, profit factor, and stats for a signal set.

        If fewer than MIN_EVENTS_FOR_STATS events, statistical fields are set
        to None/NaN.
        """
        event_count = len(returns)

        # Zero events: insufficient data, all metric fields None
        if event_count == 0:
            return SignalMetrics(
                signal_type=signal_type,
                horizon_days=horizon,
                event_count=0,
                hit_rate=None,
                base_rate=base_rate,
                p_value=None,
                ci_lower=None,
                ci_upper=None,
                avg_win=None,
                avg_loss=None,
                profit_factor=None,
                signals_per_year=0.0,
            )

        # Determine hit/miss based on signal direction
        direction = SIGNAL_DIRECTIONS[signal_type]
        if direction == SignalDirection.UP:
            hits_mask = returns > 0
        else:
            hits_mask = returns < 0

        # Hit rate
        hit_count = int(hits_mask.sum())
        hit_rate = hit_count / event_count

        # Avg win: mean of absolute values of winning returns
        winning_returns = returns[hits_mask]
        avg_win: float | None = (
            float(np.mean(np.abs(winning_returns)))
            if len(winning_returns) > 0
            else None
        )

        # Avg loss: mean of absolute values of losing returns
        losing_returns = returns[~hits_mask]
        avg_loss: float | None = (
            float(np.mean(np.abs(losing_returns)))
            if len(losing_returns) > 0
            else None
        )

        # Profit factor
        sum_wins = float(np.sum(np.abs(winning_returns)))
        sum_losses = float(np.sum(np.abs(losing_returns)))

        if len(losing_returns) == 0:
            # All hits, no losses
            profit_factor: float = float("inf")
        elif len(winning_returns) == 0:
            # All misses, no wins
            profit_factor = 0.0
        else:
            profit_factor = sum_wins / sum_losses

        # Signals per year
        signals_per_year = event_count / dataset_years if dataset_years > 0 else 0.0

        # Statistical testing: only if sufficient events
        p_value: float | None = None
        ci_lower: float | None = None
        ci_upper: float | None = None

        if event_count >= self.MIN_EVENTS_FOR_STATS:
            p_value = self.binomial_test(hit_count, event_count, base_rate)
            hit_miss_array = hits_mask.astype(np.float64)
            ci_result = self.bootstrap_ci(hit_miss_array)
            if ci_result is not None:
                ci_lower, ci_upper = ci_result

        return SignalMetrics(
            signal_type=signal_type,
            horizon_days=horizon,
            event_count=event_count,
            hit_rate=hit_rate,
            base_rate=base_rate,
            p_value=p_value,
            ci_lower=ci_lower,
            ci_upper=ci_upper,
            avg_win=avg_win,
            avg_loss=avg_loss,
            profit_factor=profit_factor,
            signals_per_year=signals_per_year,
        )

    def binomial_test(self, hits: int, n: int, base_rate: float) -> float:
        """Perform two-sided binomial test, returning p-value."""
        result = stats.binomtest(hits, n, base_rate, alternative='two-sided')
        return float(result.pvalue)

    def bootstrap_ci(self, hit_miss_array: np.ndarray) -> tuple[float, float]:
        """Compute 95% bootstrap confidence interval on hit rate.

        Uses 10000 resamples with seed 42 for reproducibility.
        Returns (ci_lower, ci_upper) as 2.5th and 97.5th percentiles.
        """
        rng = np.random.RandomState(self.BOOTSTRAP_SEED)
        n = len(hit_miss_array)
        means = np.empty(self.BOOTSTRAP_RESAMPLES)
        for i in range(self.BOOTSTRAP_RESAMPLES):
            sample = rng.choice(hit_miss_array, size=n, replace=True)
            means[i] = sample.mean()
        ci_lower = float(np.percentile(means, 2.5))
        ci_upper = float(np.percentile(means, 97.5))
        return (ci_lower, ci_upper)

    def analyse_ticker(self, ticker: str) -> list[SignalMetrics]:
        """Run the full analysis pipeline for a single ticker.

        Returns a list of SignalMetrics (one per signal_type per horizon).
        Loads the dataset, classifies signals, then computes forward returns
        and metrics for every (signal_type, horizon) combination.
        """
        df = self.load_dataset(ticker)
        signals = self.classify_signals(df)

        # Calculate dataset span in years for signals_per_year
        dates = pd.to_datetime(df["date"])
        dataset_days = (dates.iloc[-1] - dates.iloc[0]).days
        dataset_years = dataset_days / 365.25 if dataset_days > 0 else 1.0

        results: list[SignalMetrics] = []
        for signal_type in SignalType:
            indices = signals[signal_type]
            for horizon in FORWARD_HORIZONS:
                returns = self.compute_forward_returns(df, indices, horizon)
                base_rate = self.compute_base_rate(df, horizon)
                metrics = self.compute_metrics(
                    returns, signal_type, horizon, base_rate, dataset_years
                )
                results.append(metrics)

        return results

    def compute_cross_ticker_summary(
        self, all_metrics: dict[str, list[SignalMetrics]]
    ) -> list[CrossTickerSummary]:
        """Aggregate per-ticker metrics into cross-ticker summaries.

        Computes median/mean hit rates, significance counts, best/worst
        tickers, and interpretation conclusions for each (signal_type, horizon)
        combination.

        Args:
            all_metrics: Mapping of ticker -> list of 15 SignalMetrics
                (5 signal types x 3 horizons).

        Returns:
            List of 15 CrossTickerSummary entries (5 signal types x 3 horizons).
        """
        summaries: list[CrossTickerSummary] = []

        for signal_type in SignalType:
            for horizon in FORWARD_HORIZONS:
                # Collect per-ticker hit rates and p-values for this combo
                hit_rates: list[tuple[str, float]] = []  # (ticker, hit_rate)
                p_values: list[float] = []
                profit_factors: list[float] = []

                for ticker, metrics_list in all_metrics.items():
                    # Find the matching metric for this signal_type/horizon
                    metric = None
                    for m in metrics_list:
                        if (
                            m.signal_type == signal_type
                            and m.horizon_days == horizon
                        ):
                            metric = m
                            break

                    if metric is None:
                        continue

                    # Only include tickers with sufficient data (non-None hit_rate)
                    if metric.hit_rate is not None:
                        hit_rates.append((ticker, metric.hit_rate))
                        if metric.p_value is not None:
                            p_values.append(metric.p_value)
                        if (
                            metric.profit_factor is not None
                            and metric.profit_factor != float("inf")
                        ):
                            profit_factors.append(metric.profit_factor)

                total_ticker_count = len(hit_rates)

                # No tickers with data for this combination
                if total_ticker_count == 0:
                    summaries.append(
                        CrossTickerSummary(
                            signal_type=signal_type,
                            horizon_days=horizon,
                            median_hit_rate=None,
                            mean_hit_rate=None,
                            significant_ticker_count=0,
                            total_ticker_count=0,
                            median_profit_factor=None,
                            best_ticker=None,
                            best_hit_rate=None,
                            worst_ticker=None,
                            worst_hit_rate=None,
                            conclusion="Inconclusive \u2014 insufficient statistical evidence",
                        )
                    )
                    continue

                # Compute median and mean hit rates
                hr_values = np.array([hr for _, hr in hit_rates])
                median_hit_rate = float(np.median(hr_values))
                mean_hit_rate = float(np.mean(hr_values))

                # Count significant tickers
                significant_count_05 = sum(1 for p in p_values if p < 0.05)
                significant_count_01 = sum(1 for p in p_values if p < 0.01)

                # Median profit factor
                median_profit_factor: float | None = (
                    float(np.median(profit_factors))
                    if profit_factors
                    else None
                )

                # Best and worst tickers by hit rate
                best_ticker, best_hit_rate = max(hit_rates, key=lambda x: x[1])
                worst_ticker, worst_hit_rate = min(hit_rates, key=lambda x: x[1])

                # Apply interpretation logic
                conclusion = self.interpret(
                    median_hit_rate,
                    significant_count_05,
                    significant_count_01,
                    total_ticker_count,
                )

                # Note insufficient ticker coverage per Req 5.5
                if total_ticker_count < 3:
                    conclusion += " (insufficient ticker coverage)"

                summaries.append(
                    CrossTickerSummary(
                        signal_type=signal_type,
                        horizon_days=horizon,
                        median_hit_rate=median_hit_rate,
                        mean_hit_rate=mean_hit_rate,
                        significant_ticker_count=significant_count_05,
                        total_ticker_count=total_ticker_count,
                        median_profit_factor=median_profit_factor,
                        best_ticker=best_ticker,
                        best_hit_rate=best_hit_rate,
                        worst_ticker=worst_ticker,
                        worst_hit_rate=worst_hit_rate,
                        conclusion=conclusion,
                    )
                )

        return summaries

    def interpret(
        self,
        median_hit_rate: float,
        significant_count_05: int,
        significant_count_01: int,
        total_count: int,
    ) -> str:
        """Apply hit-rate band interpretation logic.

        Returns one of the predefined conclusion strings based on
        median hit rate and statistical significance counts.

        Args:
            median_hit_rate: Median hit rate across tickers (0.0 to 1.0).
            significant_count_05: Number of tickers with p < 0.05.
            significant_count_01: Number of tickers with p < 0.01.
            total_count: Number of tickers with sufficient data.

        Precedence: contrarian (< 45%) takes priority over noise.
        """
        # Criterion 4 (takes precedence): Contrarian indicator
        if median_hit_rate < 0.45 and significant_count_05 >= 1:
            return "Reliable contrarian indicator \u2014 invert the signal"

        # Criterion 1: Noise
        nonsig_count = total_count - significant_count_05
        if median_hit_rate <= 0.55 and nonsig_count > total_count / 2:
            return "Signal is noise \u2014 remove or reduce signal weight"

        # Criterion 3: Strong signal (requires p < 0.01)
        if median_hit_rate >= 0.60 and significant_count_01 >= 1:
            return "Strong signal \u2014 build trading strategy around this event type"

        # Criterion 2: Weak edge
        if 0.55 < median_hit_rate < 0.60 and significant_count_05 >= 1:
            return "Weak but real edge \u2014 keep signal, consider as filter only"

        # Criterion 6: Fallback
        return "Inconclusive \u2014 insufficient statistical evidence"

    @staticmethod
    def _fmt_float(value: Optional[float], decimals: int) -> str:
        """Format a float value for CSV output.

        Returns empty string for None, formatted string otherwise.
        """
        if value is None:
            return ""
        return f"{value:.{decimals}f}"

    @staticmethod
    def _fmt_profit_factor(value: Optional[float]) -> str:
        """Format profit_factor for CSV output.

        Returns empty string for None, 'inf' for infinity, formatted 4dp otherwise.
        """
        if value is None:
            return ""
        if value == float("inf"):
            return "inf"
        return f"{value:.4f}"

    def write_per_ticker_csv(self, ticker: str, metrics: list[SignalMetrics]) -> None:
        """Write per-ticker detail CSV to output directory.

        Writes one row per (signal_type, horizon) combination with formatted
        numeric fields. None values are written as empty strings.
        Float fields use 4 decimal places, signals_per_year uses 1 decimal.
        """
        import csv

        self.output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = self.output_dir / f"{ticker}_signal_analysis.csv"

        headers = [
            "signal_type", "horizon_days", "event_count", "hit_rate",
            "base_rate", "p_value", "ci_lower", "ci_upper",
            "avg_win", "avg_loss", "profit_factor", "signals_per_year",
        ]

        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)

            for m in metrics:
                row = [
                    m.signal_type.value,
                    m.horizon_days,
                    m.event_count,
                    self._fmt_float(m.hit_rate, 4),
                    self._fmt_float(m.base_rate, 4),
                    self._fmt_float(m.p_value, 4),
                    self._fmt_float(m.ci_lower, 4),
                    self._fmt_float(m.ci_upper, 4),
                    self._fmt_float(m.avg_win, 4),
                    self._fmt_float(m.avg_loss, 4),
                    self._fmt_profit_factor(m.profit_factor),
                    self._fmt_float(m.signals_per_year, 1),
                ]
                writer.writerow(row)

    def write_comparison_csv(self, summaries: list[CrossTickerSummary]) -> None:
        """Write cross-ticker comparison summary CSV.

        Writes one row per (signal_type, horizon) combination with formatted
        numeric fields. None values are written as empty strings.
        """
        import csv

        self.output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = self.output_dir / "signal_comparison_summary.csv"

        headers = [
            "signal_type", "horizon_days", "median_hit_rate", "mean_hit_rate",
            "significant_ticker_count", "total_ticker_count",
            "median_profit_factor", "best_ticker", "best_hit_rate",
            "worst_ticker", "worst_hit_rate",
        ]

        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)

            for s in summaries:
                row = [
                    s.signal_type.value,
                    s.horizon_days,
                    self._fmt_float(s.median_hit_rate, 4),
                    self._fmt_float(s.mean_hit_rate, 4),
                    s.significant_ticker_count,
                    s.total_ticker_count,
                    self._fmt_float(s.median_profit_factor, 4),
                    s.best_ticker if s.best_ticker is not None else "",
                    self._fmt_float(s.best_hit_rate, 4),
                    s.worst_ticker if s.worst_ticker is not None else "",
                    self._fmt_float(s.worst_hit_rate, 4),
                ]
                writer.writerow(row)

    def write_summary_text(self, summaries: list[CrossTickerSummary]) -> None:
        """Write summary text file with interpretations and rankings.

        Contains an interpretation table, per-horizon ranked lists of signal
        types by median hit rate descending, and the conclusion for each.
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)
        txt_path = self.output_dir / "signal_analysis_summary.txt"

        lines: list[str] = []
        lines.append("VPA Signal-Conditional Analysis Summary")
        lines.append("=======================================")
        lines.append("")
        lines.append("Interpretation Table:")
        lines.append("| Hit Rate Band | Conclusion |")
        lines.append("|---|---|")
        lines.append(
            "| < 45% (p < 0.05) | Reliable contrarian indicator"
            " \u2014 invert the signal |"
        )
        lines.append(
            "| <= 55% (majority p >= 0.05) | Signal is noise"
            " \u2014 remove or reduce signal weight |"
        )
        lines.append(
            "| 55-60% (p < 0.05) | Weak but real edge"
            " \u2014 keep signal, consider as filter only |"
        )
        lines.append(
            "| >= 60% (p < 0.01) | Strong signal"
            " \u2014 build trading strategy around this event type |"
        )
        lines.append("")
        lines.append("Results by Horizon:")

        for horizon in FORWARD_HORIZONS:
            lines.append("")
            lines.append(f"=== {horizon}-Day Forward Returns ===")

            # Filter summaries for this horizon and sort by median hit rate descending
            horizon_summaries = [
                s for s in summaries if s.horizon_days == horizon
            ]
            # Sort by median_hit_rate descending; None values go last
            horizon_summaries.sort(
                key=lambda s: s.median_hit_rate if s.median_hit_rate is not None else -1.0,
                reverse=True,
            )

            for s in horizon_summaries:
                if s.median_hit_rate is not None:
                    hr_pct = f"{s.median_hit_rate * 100:.1f}%"
                else:
                    hr_pct = "N/A"
                lines.append(
                    f"Signal: {s.signal_type.value}"
                    f" | Median Hit Rate: {hr_pct}"
                    f" | Conclusion: {s.conclusion}"
                )

        lines.append("")  # trailing newline

        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def run(self) -> None:
        """Execute the full multi-ticker analysis pipeline.

        Loads each ticker, runs analysis, produces all output artefacts.
        Prints progress to stdout.
        """
        total = len(self.TICKER_UNIVERSE)
        all_metrics: dict[str, list[SignalMetrics]] = {}

        for n, ticker in enumerate(self.TICKER_UNIVERSE, start=1):
            try:
                metrics = self.analyse_ticker(ticker)
                # Count unique signal events (use the first horizon event counts)
                signal_count = sum(
                    m.event_count for m in metrics
                    if m.horizon_days == FORWARD_HORIZONS[0]
                )
                print(
                    f"Processing {ticker} ({n}/{total})..."
                    f" {signal_count} signal events found"
                )
                all_metrics[ticker] = metrics
                self.write_per_ticker_csv(ticker, metrics)
            except FileNotFoundError:
                print(
                    f"Warning: Feature dataset not found for {ticker}, skipping"
                )
            except (pd.errors.ParserError, pd.errors.EmptyDataError) as e:
                print(
                    f"Warning: Could not parse dataset for {ticker}: {e},"
                    " skipping"
                )
            except InsufficientDataError as e:
                print(f"Warning: {e}, skipping {ticker}")

        if not all_metrics:
            raise InsufficientDataError("No valid ticker datasets loaded")

        # Cross-ticker summary
        summaries = self.compute_cross_ticker_summary(all_metrics)
        self.write_comparison_csv(summaries)
        self.write_summary_text(summaries)

        print(f"\nAnalysis complete. {len(all_metrics)}/{total} tickers processed.")
        print(f"Output written to: {self.output_dir}")
