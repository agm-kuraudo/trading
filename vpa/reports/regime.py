"""Asset-neutral, in-memory regime wrapper around ``DailySignalGenerator``.

This module adapts the SP-315 daily signal generator into the consolidated
daily report's Market Regime input. It is **not** a file reader: for each
configured asset it invokes ``DailySignalGenerator(ticker=asset).run()`` in
process and normalises the result.

Per-asset isolation: each asset is generated inside its own ``try/except`` so
that one asset failing (e.g. ``InsufficientDataError``) cannot stop the others,
and each failure yields exactly one log entry.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from vpa.ml_validation.daily_signal import DailySignalGenerator, SignalRecord
from vpa.ml_validation.exceptions import InsufficientDataError

logger = logging.getLogger(__name__)


class RegimeAssetState(Enum):
    """Classification of a single asset's regime-generation outcome."""

    PRESENT = "present"  # generator ran; one or more fired records
    EMPTY = "empty"  # generator ran; no fired records ("no high-conviction signal")
    MISSING = "missing"  # generator could not run for this asset (error)


@dataclass(frozen=True)
class RegimeAssetResult:
    """Normalised outcome of running the regime generator for one asset."""

    asset: str
    state: RegimeAssetState
    records: tuple[SignalRecord, ...] = field(default_factory=tuple)  # High-first; empty unless PRESENT
    detail: str = ""  # reason text for logging on MISSING


def collect_regime(
    assets: Sequence[str],
    *,
    output_dir: Path,
    lookback_days: int = 200,
    generator_factory=DailySignalGenerator,  # injectable for tests
) -> tuple[RegimeAssetResult, ...]:
    """Run the SP-315 generator per configured asset and normalise each result.

    ``assets`` is the resolved Configured_Assets list — an arbitrary number N of
    assets supplied by external configuration (the orchestrator reads it from
    config/env, default ``["SPY"]``). The wrapper is agnostic to N: it simply
    iterates whatever list it is handed, so adding assets is a configuration
    change, not a code change.

    For each asset: build
    ``generator_factory(output_dir=..., lookback_days=..., ticker=asset)`` and
    call ``.run()``. A non-empty list -> ``PRESENT``; an empty list -> ``EMPTY``
    ("no high-conviction signal"); an ``InsufficientDataError`` or any other
    exception -> ``MISSING`` with the reason captured in ``detail`` and logged.
    Exactly one ``RegimeAssetResult`` is returned per configured asset.

    Args:
        assets: The resolved Configured_Assets list (arbitrary length N).
        output_dir: Directory passed through to each generator.
        lookback_days: Calendar days of OHLCV history each generator downloads.
        generator_factory: Factory producing a generator with a ``.run()``
            method; injectable so tests pass a fake and never touch yfinance.

    Returns:
        One ``RegimeAssetResult`` per configured asset, in input order.
    """
    results: list[RegimeAssetResult] = []
    for asset in assets:
        try:
            generator = generator_factory(output_dir=output_dir, lookback_days=lookback_days, ticker=asset)
            records = tuple(generator.run())
        except InsufficientDataError as exc:
            detail = f"{type(exc).__name__}: {exc}"
            logger.warning("Regime generation unavailable for asset %s: %s", asset, detail)
            results.append(RegimeAssetResult(asset=asset, state=RegimeAssetState.MISSING, detail=detail))
            continue
        except Exception as exc:  # noqa: BLE001 - per-asset isolation: one asset must not stop the others
            detail = f"{type(exc).__name__}: {exc}"
            logger.warning("Regime generation failed for asset %s: %s", asset, detail)
            results.append(RegimeAssetResult(asset=asset, state=RegimeAssetState.MISSING, detail=detail))
            continue

        if records:
            results.append(RegimeAssetResult(asset=asset, state=RegimeAssetState.PRESENT, records=records))
        else:
            results.append(RegimeAssetResult(asset=asset, state=RegimeAssetState.EMPTY))

    return tuple(results)
