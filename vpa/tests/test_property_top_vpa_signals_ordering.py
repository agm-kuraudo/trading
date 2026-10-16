"""Property-based test for the Top VPA Signals section ordering and cap (SP-356, Task 2.2).

**Property 2: Top VPA Signals ordering and cap.** For any all-shares
``DailyReport``, the Consolidated_Daily_Report's Top VPA Signals section SHALL:

- contain at most 5 signals (Req 4.1);
- be ordered by signal score from highest to lowest, with equally-scored
  tickers ordered alphabetically by ticker symbol ascending (Req 4.2, 4.3);
- carry only the strongest signals: every listed score is >= every omitted
  successful score (the direct consequence of taking the top 5 of a
  score-descending ordering).

**Validates: Requirements 4.1, 4.2, 4.3**

The property is exercised through the real builder
``build_consolidated_report(report_date, scan_result, regime_result)``
(``vpa/reports/consolidated_builder.py``) and asserts on the resulting
``ConsolidatedReport.top_vpa_signals.signals`` — no mocks, no I/O, no network.

The scan input is a ``DailyReport`` whose rows are a random mix of statuses
("success"/"failed"), random ``signal_score`` (including ``None``, which the
builder treats as 0), and random ``report_ticker``. Only the successful rows
feed the Top VPA Signals section; a failed row never appears. The builder slices
the first five of ``DailyReport.successful_results``, which is already sorted
``(-(signal_score or 0), report_ticker)`` — so the expected top-5 is derived
from that same ordering and compared directly. The regime input is irrelevant to
this section, so an empty list is passed (its sections are covered by the other
properties).
"""

from __future__ import annotations

import datetime as dt

from hypothesis import given, settings
from hypothesis import strategies as st

from vpa.reports.consolidated_builder import build_consolidated_report
from vpa.reports.models import DailyReport, TickerScanResult

# At most this many signals appear in the Top VPA Signals section (Req 4.1).
_TOP_VPA_LIMIT = 5

# Finite signal scores (no NaN / inf): NaN would break the total ordering the
# ranking relies on and is not valid scan data anyway. ``None`` is drawn
# separately and treated as 0 by the builder.
_SCORES = st.one_of(
    st.none(),
    st.floats(allow_nan=False, allow_infinity=False, min_value=-1000, max_value=1000, width=64),
)

# Short ticker symbols from a small alphabet so ties on signal_score are common
# (that is where the alphabetical tie-break matters most).
_TICKERS = st.text(alphabet="ABCDE", min_size=1, max_size=3)


@st.composite
def _ticker_scan_results(draw) -> tuple[TickerScanResult, ...]:
    """A random list of scan rows: mixed status, random score (incl. None), random ticker."""
    rows = draw(
        st.lists(
            st.builds(
                TickerScanResult,
                source_ticker=_TICKERS,
                report_ticker=_TICKERS,
                status=st.sampled_from(("success", "failed")),
                signal_score=_SCORES,
            ),
            max_size=12,
        )
    )
    return tuple(rows)


@st.composite
def _daily_reports(draw) -> DailyReport:
    return DailyReport(
        report_date=draw(st.dates(min_value=dt.date(2000, 1, 1), max_value=dt.date(2100, 12, 31))),
        results=draw(_ticker_scan_results()),
        opportunity_filter_enabled=draw(st.booleans()),
    )


def _score_key(result: TickerScanResult) -> tuple[float, str]:
    """The builder/model ordering key: score descending, ticker ascending."""
    return (-(result.signal_score or 0), result.report_ticker)


# Feature: daily-market-report, Property 2: Top VPA Signals ordering and cap
@settings(max_examples=200)
@given(report=_daily_reports())
def test_top_vpa_signals_ordering_and_cap(report: DailyReport) -> None:
    """Section is capped at 5, score-desc with alphabetical tie-break, strongest-only.

    Validates: Requirements 4.1, 4.2, 4.3
    """
    consolidated = build_consolidated_report(report.report_date, report, [])
    listed = consolidated.top_vpa_signals.signals

    # Req 4.1: at most 5 signals in the section.
    assert len(listed) <= _TOP_VPA_LIMIT

    # Expected top-5 derived from the model's own score-desc / ticker-asc ordering.
    successful = report.successful_results  # already sorted (-(score or 0), ticker)
    expected = successful[:_TOP_VPA_LIMIT]

    # The section lists exactly those rows, as (ticker, score-with-None-as-0).
    assert [signal.ticker for signal in listed] == [result.report_ticker for result in expected]
    assert [signal.signal_score for signal in listed] == [(result.signal_score or 0.0) for result in expected]

    # Req 4.2/4.3: the listed order is non-increasing by score with ties broken
    # alphabetically by ticker ascending — i.e. each adjacent pair is correctly
    # ordered by the (score desc, ticker asc) key.
    for earlier, later in zip(listed, listed[1:], strict=False):
        assert (-earlier.signal_score, earlier.ticker) <= (-later.signal_score, later.ticker)

    # Strongest-only: every listed score is >= every omitted successful score
    # (None omitted score counts as 0, matching the builder's treatment).
    if listed:
        omitted = successful[_TOP_VPA_LIMIT:]
        min_listed_score = min(signal.signal_score for signal in listed)
        for result in omitted:
            assert min_listed_score >= (result.signal_score or 0.0)
