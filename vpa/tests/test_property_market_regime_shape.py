"""Property-based test for the Market Regime section per-asset shape (SP-356, Task 7.2).

**Property 7: Market Regime reflects each configured asset exactly once.** For
any per-asset regime input over an arbitrary number N of configured assets, the
Consolidated_Daily_Report's Market Regime section SHALL:

- contain each configured asset exactly once;
- for a PRESENT asset, carry its fired records ordered highest-confidence first
  ("High" before "Medium-High" before "Low-Medium" before "Low");
- for an EMPTY asset (ran but fired nothing), show the no-high-conviction-signal
  indication (``available`` with no signals);
- for a MISSING asset (generator could not run), show the unavailable
  placeholder (not ``available``).

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**

The property is exercised through the real builder
``build_consolidated_report(report_date, scan_result, regime_result)``
(``vpa/reports/consolidated_builder.py``) and asserts on the resulting
``ConsolidatedReport.market_regime`` — no mocks, no I/O, no network. The regime
input is a tuple of ``RegimeAssetResult`` with DISTINCT asset identifiers over
arbitrary N, each randomly PRESENT (1+ ``SignalRecord`` already High-first),
EMPTY, or MISSING. The scan result is irrelevant to the Market Regime section,
so it is left ``None`` here (its own sections are covered by Properties 2-6).
"""

from __future__ import annotations

import datetime as dt

from hypothesis import given, settings
from hypothesis import strategies as st

from vpa.ml_validation.daily_signal import CONFIDENCE_ORDER, SignalRecord
from vpa.reports.consolidated_builder import build_consolidated_report
from vpa.reports.regime import RegimeAssetResult, RegimeAssetState

# The generator's confidence ordering: "High" first, then down to "Low".
_CONFIDENCE_LEVELS = tuple(CONFIDENCE_ORDER)


def _confidence_rank(level: str) -> int:
    """Sort rank for a confidence level — "High" is rank 0 (highest)."""
    return CONFIDENCE_ORDER.index(level)


@st.composite
def _signal_records(draw, ticker: str) -> tuple[SignalRecord, ...]:
    """1+ SignalRecords for a PRESENT asset, sorted High-first like the generator.

    The SP-315 generator returns its records already sorted confidence
    descending, so a PRESENT ``RegimeAssetResult`` always carries High-first
    records. We mirror that contract: draw random records then sort them by
    confidence rank so the generator's own ordering is what reaches the builder.
    """
    levels = draw(st.lists(st.sampled_from(_CONFIDENCE_LEVELS), min_size=1, max_size=5))
    records = [
        SignalRecord(
            ticker=ticker,
            date="2026-07-15",
            signal_type=draw(st.sampled_from(("distribution", "strong_bearish", "accumulation"))),
            original_direction=draw(st.sampled_from(("up", "down"))),
            adjusted_direction="BUY",
            confidence_level=level,
            suggested_hold_days=10,
        )
        for level in levels
    ]
    # High-first, matching the generator (stable sort preserves draw order on ties).
    records.sort(key=lambda r: _confidence_rank(r.confidence_level))
    return tuple(records)


@st.composite
def _regime_results(draw) -> tuple[RegimeAssetResult, ...]:
    """A tuple of RegimeAssetResult with DISTINCT assets over arbitrary N.

    Each asset is randomly PRESENT (with 1+ High-first records), EMPTY (ran but
    fired nothing), or MISSING (generator could not run). Distinct identifiers
    model the Configured_Assets list; N ranges from 0 up.
    """
    asset_names = draw(st.lists(st.text(min_size=1, max_size=6), min_size=0, max_size=6, unique=True))
    results: list[RegimeAssetResult] = []
    for name in asset_names:
        state = draw(st.sampled_from((RegimeAssetState.PRESENT, RegimeAssetState.EMPTY, RegimeAssetState.MISSING)))
        if state is RegimeAssetState.PRESENT:
            records = draw(_signal_records(name))
            results.append(RegimeAssetResult(asset=name, state=state, records=records))
        elif state is RegimeAssetState.EMPTY:
            results.append(RegimeAssetResult(asset=name, state=state))
        else:  # MISSING
            results.append(RegimeAssetResult(asset=name, state=state, detail="InsufficientDataError: too few bars"))
    return tuple(results)


# Feature: daily-market-report, Property 7: Market Regime reflects each configured asset exactly once
@settings(max_examples=200)
@given(
    report_date=st.dates(min_value=dt.date(2000, 1, 1), max_value=dt.date(2100, 12, 31)),
    regime_result=_regime_results(),
)
def test_market_regime_reflects_each_configured_asset_exactly_once(
    report_date: dt.date,
    regime_result: tuple[RegimeAssetResult, ...],
) -> None:
    """Each configured asset appears once; present High-first, empty/missing flagged.

    Validates: Requirements 3.1, 3.2, 3.3, 3.4
    """
    report = build_consolidated_report(report_date, None, regime_result)
    section = report.market_regime

    # Req 3.1/3.3: each configured asset appears in the section exactly once.
    section_assets = [entry.asset for entry in section.assets]
    expected_assets = [result.asset for result in regime_result]
    assert sorted(section_assets) == sorted(expected_assets)
    assert len(section_assets) == len(set(section_assets))

    entries_by_asset = {entry.asset: entry for entry in section.assets}

    for result in regime_result:
        entry = entries_by_asset[result.asset]

        if result.state is RegimeAssetState.PRESENT:
            # Req 3.1: a present asset shows its fired records.
            assert entry.available is True
            assert entry.no_high_conviction is False
            # The builder carries exactly the records it received, nothing added/dropped.
            assert len(entry.signals) == len(result.records)
            # Req 3.2: records ordered highest-confidence first (ranks non-decreasing).
            ranks = [_confidence_rank(signal.confidence_level) for signal in entry.signals]
            assert ranks == sorted(ranks)
            # The entry's records mirror the (High-first) generator records in order.
            assert [signal.confidence_level for signal in entry.signals] == [
                record.confidence_level for record in result.records
            ]

        elif result.state is RegimeAssetState.EMPTY:
            # Req 3.4: an asset that ran but fired nothing -> no-high-conviction.
            assert entry.available is True
            assert entry.signals == ()
            assert entry.no_high_conviction is True

        else:  # MISSING
            # Req 3.5 shape at the asset level: generator could not run -> unavailable.
            assert entry.available is False
            assert entry.signals == ()
            assert entry.no_high_conviction is False
