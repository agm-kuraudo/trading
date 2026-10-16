"""Property-based test for the Opportunities section ordering (SP-356, Task 2.3).

**Property 3: Opportunities ordering is deterministic and total.** For any VPA
scan result, the Consolidated_Daily_Report's Opportunities section SHALL:

- list exactly the qualifying opportunity tickers from the scan result — none
  added, none dropped (total membership);
- in a deterministic order that is independent of the input row ordering
  (permuting the scan rows yields an identical Opportunities section);
- with each listed opportunity carrying its drawdown and momentum values.

**Validates: Requirements 2.2, 5.1, 5.3**

The property is exercised through the real builder
``build_consolidated_report(report_date, scan_result, regime_result)``
(``vpa/reports/consolidated_builder.py``) and asserts on the resulting
``ConsolidatedReport.opportunities`` — no mocks, no I/O, no network. The scan
rows are generated with random ``opportunity_status`` (some ``"qualifies"``),
random ``drawdown_pct``/``momentum_pct`` and random ``report_ticker``, then a
``DailyReport`` is built from the SAME rows in two DIFFERENT orders (a
permutation) so determinism-under-permutation can be asserted directly. The
regime input is irrelevant to the Opportunities section, so it is left empty
here (its shape is covered by Property 7).
"""

from __future__ import annotations

import datetime as dt

from hypothesis import given, settings
from hypothesis import strategies as st

from vpa.reports.consolidated_builder import build_consolidated_report
from vpa.reports.models import DailyReport, TickerScanResult

_OPPORTUNITY_STATUSES = ("qualifies", "does_not_qualify", "disabled", "unavailable")


@st.composite
def _scan_rows(draw) -> list[TickerScanResult]:
    """A list of TickerScanResult rows with DISTINCT tickers.

    Each row gets a random ``opportunity_status`` (some ``"qualifies"``), random
    ``drawdown_pct``/``momentum_pct`` (``None`` allowed, mirroring real scan
    rows), and a distinct ``report_ticker``. Distinct tickers keep the
    deterministic sort key ``(drawdown_pct or 0, report_ticker)`` total so the
    expected ordering is unambiguous.
    """
    tickers = draw(st.lists(st.text(min_size=1, max_size=6), min_size=0, max_size=8, unique=True))
    floats = st.one_of(
        st.none(),
        st.floats(min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    )
    rows: list[TickerScanResult] = []
    for ticker in tickers:
        rows.append(
            TickerScanResult(
                source_ticker=ticker,
                report_ticker=ticker,
                status="success",
                signal_score=draw(st.one_of(st.none(), st.floats(min_value=-50, max_value=50, allow_nan=False))),
                opportunity_status=draw(st.sampled_from(_OPPORTUNITY_STATUSES)),
                drawdown_pct=draw(floats),
                momentum_pct=draw(floats),
            )
        )
    return rows


def _opportunities_section(rows: list[TickerScanResult]):
    """Build the report from ``rows`` and return its Opportunities section."""
    report = DailyReport(
        report_date=dt.date(2026, 7, 15),
        results=tuple(rows),
        opportunity_filter_enabled=True,
    )
    consolidated = build_consolidated_report(dt.date(2026, 7, 15), report, ())
    return consolidated.opportunities


# Feature: daily-market-report, Property 3: Opportunities ordering is deterministic and total
@settings(max_examples=200)
@given(
    rows=_scan_rows(),
    permutation=st.randoms(use_true_random=False),
)
def test_opportunities_ordering_is_deterministic_and_total(
    rows: list[TickerScanResult],
    permutation,
) -> None:
    """Opportunities = the qualifying rows, in a permutation-independent order.

    Validates: Requirements 2.2, 5.1, 5.3
    """
    # Build the section from the rows as generated, and again from a shuffled
    # copy of the SAME rows (same membership, different input order).
    shuffled = list(rows)
    permutation.shuffle(shuffled)

    section = _opportunities_section(rows)
    section_shuffled = _opportunities_section(shuffled)

    # Req 5.1: deterministic order independent of input row ordering — permuting
    # the input rows yields an identical Opportunities section.
    assert section == section_shuffled

    # Req 2.2 / 5.1: total membership — exactly the qualifying tickers, none
    # added, none dropped.
    qualifying_tickers = {row.report_ticker for row in rows if row.opportunity_status == "qualifies"}
    section_tickers = {opp.ticker for opp in section.opportunities}
    assert section_tickers == qualifying_tickers
    assert len(section.opportunities) == len(qualifying_tickers)

    # The order matches the DailyReport's deterministic sort key
    # (drawdown_pct or 0, report_ticker) — the documented Opportunities order.
    expected_order = [
        row.report_ticker
        for row in sorted(
            (r for r in rows if r.opportunity_status == "qualifies"),
            key=lambda r: (r.drawdown_pct if r.drawdown_pct is not None else 0, r.report_ticker),
        )
    ]
    assert [opp.ticker for opp in section.opportunities] == expected_order

    # Req 5.3: each listed opportunity carries its drawdown and momentum values
    # from the originating scan row (None normalised to 0.0 by the builder).
    rows_by_ticker = {row.report_ticker: row for row in rows}
    for opp in section.opportunities:
        row = rows_by_ticker[opp.ticker]
        assert opp.drawdown_pct == (row.drawdown_pct if row.drawdown_pct is not None else 0.0)
        assert opp.momentum_pct == (row.momentum_pct if row.momentum_pct is not None else 0.0)
