"""Unit tests for the SP-313 experiment record and result writer.

These are FAST tests: ``ExperimentRecord`` is a pure dataclass with
serialisation helpers and ``ResultWriter`` only touches the filesystem via the
``tmp_path`` fixture, so none of these carry the ``slow`` marker.

Coverage:

- **Serialisation round-trip (Req 1.2, 1.3, 10.6).** A complete record's
  ``to_dict()`` is JSON-serialisable, flattens ``scoring_params`` to the same
  flat dict as ``ScoringParams.as_dict()``, rounds numeric values to two
  decimal places, and preserves ``None`` as JSON ``null`` (the "unavailable"
  markers). ``to_summary_text()`` renders ``None`` as ``N/A``.
- **Req 1.5 pre-write guard.** ``ResultWriter.write()`` on an incomplete record
  (``run_completed=False`` or ``labelled_row_count <= 0``) raises
  :class:`InsufficientDataError` with a ticker-identifying message and writes no
  files.
- **Happy-path write.** A complete record writes the JSON artefact and the
  summary text file, and the JSON loads back to the expected dict.
- **Log-and-continue on write failure.** A disk ``OSError`` during the write of
  a complete record is logged (not raised).

# Feature: vpa-threshold-tuning-ml-revalidation, Requirements 1.2, 1.3, 1.5, 10.6
"""

import json
import logging

import pytest

from vpa.ml_validation.exceptions import InsufficientDataError
from vpa.ml_validation.tuning.record import ExperimentRecord, ResultWriter
from vpa.ml_validation.tuning.scoring_params import ScoringParams


def _complete_record(ticker: str = "SPY") -> ExperimentRecord:
    """Build a COMPLETE, writable record with representative values."""
    return ExperimentRecord(
        ticker=ticker,
        data_start="2014-01-02",
        data_end="2024-01-02",
        labelled_row_count=2461,
        seed=42,
        scoring_params=ScoringParams.default(),
        baseline_accuracy_pct=52.3456,
        ml_mean_accuracy_pct=50.5912,
        ml_std_accuracy_pct=3.0876,
        skipped_folds=[0, 3],
        top5_feature_importance=[
            {"name": "is_shooting_star", "score": 5.8123},
            {"name": "acc_dist_score", "score": 4.2001},
            {"name": "spread_pct_p3", "score": 3.9999},
        ],
        realized_volatility=0.012345,
        run_completed=True,
        error=None,
    )


# --- Serialisation round-trip (Req 1.2, 1.3, 10.6) -----------------------


class TestSerialisationRoundTrip:
    """``to_dict`` / ``to_summary_text`` serialisation behaviour."""

    def test_to_dict_is_json_serialisable(self):
        record = _complete_record()
        payload = record.to_dict()
        # json.dumps must not raise on the dict.
        dumped = json.dumps(payload)
        reloaded = json.loads(dumped)
        assert reloaded == payload

    def test_scoring_params_serialised_as_flat_dict(self):
        record = _complete_record()
        payload = record.to_dict()
        assert payload["scoring_params"] == ScoringParams.default().as_dict()
        # Flat dict: every value is a plain scalar, not a nested structure.
        for value in payload["scoring_params"].values():
            assert isinstance(value, int | float)

    def test_numeric_values_rounded_to_two_dp(self):
        record = _complete_record()
        payload = record.to_dict()
        assert payload["baseline_accuracy_pct"] == 52.35
        assert payload["ml_mean_accuracy_pct"] == 50.59
        assert payload["ml_std_accuracy_pct"] == 3.09
        assert payload["realized_volatility"] == 0.01
        # Feature-importance scores are rounded too; names are untouched.
        assert payload["top5_feature_importance"] == [
            {"name": "is_shooting_star", "score": 5.81},
            {"name": "acc_dist_score", "score": 4.2},
            {"name": "spread_pct_p3", "score": 4.0},
        ]

    def test_none_fields_preserved_as_json_null(self):
        record = _complete_record()
        record.ml_mean_accuracy_pct = None
        record.ml_std_accuracy_pct = None
        record.realized_volatility = None
        payload = record.to_dict()
        assert payload["ml_mean_accuracy_pct"] is None
        assert payload["ml_std_accuracy_pct"] is None
        assert payload["realized_volatility"] is None
        # Survives a JSON round-trip as null.
        reloaded = json.loads(json.dumps(payload))
        assert reloaded["ml_mean_accuracy_pct"] is None
        assert reloaded["realized_volatility"] is None

    def test_summary_text_renders_none_as_na(self):
        record = _complete_record()
        record.ml_mean_accuracy_pct = None
        record.realized_volatility = None
        text = record.to_summary_text()
        assert "ML mean accuracy:   N/A" in text
        assert "Realized vol:       N/A" in text
        # Present values still render numerically to 2dp.
        assert "Baseline accuracy:  52.35%" in text

    def test_summary_text_includes_ticker_and_params(self):
        record = _complete_record("AAPL")
        text = record.to_summary_text()
        assert "AAPL" in text
        # Every scoring param name appears in the thresholds section.
        for name in ScoringParams.default().as_dict():
            assert name in text


# --- Req 1.5 pre-write guard ---------------------------------------------


class TestPreWriteGuard:
    """``write`` refuses incomplete records and writes no partial artefact."""

    def test_run_not_completed_raises_and_writes_nothing(self, tmp_path):
        record = _complete_record("TSLA")
        record.run_completed = False
        writer = ResultWriter(tmp_path)

        with pytest.raises(InsufficientDataError) as exc_info:
            writer.write(record)

        # Ticker-identifying message.
        assert "TSLA" in str(exc_info.value)
        # No artefact files written.
        assert list(tmp_path.iterdir()) == []

    def test_zero_labelled_rows_raises_and_writes_nothing(self, tmp_path):
        record = _complete_record("MSFT")
        record.labelled_row_count = 0
        writer = ResultWriter(tmp_path)

        with pytest.raises(InsufficientDataError) as exc_info:
            writer.write(record)

        assert "MSFT" in str(exc_info.value)
        assert list(tmp_path.iterdir()) == []

    def test_negative_labelled_rows_raises_and_writes_nothing(self, tmp_path):
        record = _complete_record("NVDA")
        record.labelled_row_count = -5
        writer = ResultWriter(tmp_path)

        with pytest.raises(InsufficientDataError):
            writer.write(record)

        assert not (tmp_path / "NVDA_experiment_record.json").exists()
        assert not (tmp_path / "NVDA_experiment_summary.txt").exists()


# --- Happy-path write -----------------------------------------------------


class TestHappyPathWrite:
    """A complete record writes both artefacts into the output directory."""

    def test_writes_json_and_summary_files(self, tmp_path):
        record = _complete_record("SPY")
        writer = ResultWriter(tmp_path)
        writer.write(record)

        json_path = tmp_path / "SPY_experiment_record.json"
        summary_path = tmp_path / "SPY_experiment_summary.txt"
        assert json_path.exists()
        assert summary_path.exists()

    def test_json_loads_back_to_expected_dict(self, tmp_path):
        record = _complete_record("SPY")
        writer = ResultWriter(tmp_path)
        writer.write(record)

        json_path = tmp_path / "SPY_experiment_record.json"
        loaded = json.loads(json_path.read_text(encoding="utf-8"))
        assert loaded == record.to_dict()

    def test_creates_missing_output_dir(self, tmp_path):
        nested = tmp_path / "does" / "not" / "exist"
        writer = ResultWriter(nested)
        writer.write(_complete_record("SPY"))
        assert (nested / "SPY_experiment_record.json").exists()


# --- Log-and-continue on write failure -----------------------------------


class TestWriteFailureIsLoggedNotRaised:
    """A disk ``OSError`` for a complete record is logged, not raised."""

    def test_write_failure_does_not_raise_and_logs_error(self, tmp_path, caplog, monkeypatch):
        record = _complete_record("SPY")
        writer = ResultWriter(tmp_path)

        # Simulate a disk failure at the real call site: Path.write_text.
        def _boom(self, *args, **kwargs):
            raise OSError("simulated disk failure")

        monkeypatch.setattr("pathlib.Path.write_text", _boom)

        with caplog.at_level(logging.ERROR, logger="vpa.ml_validation.tuning.record"):
            # Must NOT raise despite the write failure.
            writer.write(record)

        # An error was logged describing the failure.
        assert any(rec.levelno == logging.ERROR for rec in caplog.records)
        assert "Failed to write" in caplog.text
