"""Property-based tests for the pure feed decoder (SP-309, task 2.3).

Exercises the decode round-trip guarantee of
:func:`vpa.forex_data.decoder.decode_feed`. The decoder is pure and offline: it
takes already-fetched gzipped bytes and returns decoded :class:`Record`
instances, so these tests drive it directly with synthetic ``.lb`` buffers built
by the shared :func:`vpa.tests.forex_data.helpers.encode_records` helper — no
socket is ever opened (Requirement 9.3).

Property 1 (decode round-trip) is the natural home for property-based testing:
``decode_feed`` is deterministic over a large input space (arbitrary Int32
fields, arbitrary record counts, either 24- or 28-byte record variant, arbitrary
positive price/volume scales) with a clear universal property — every source
field can be recovered from the decoded record via the documented derivations.

The malformed-buffer-length property (Property 2) lives in the separate
``test_decoder_malformed.py`` file owned by task 2.4, so it is deliberately not
duplicated here.
"""

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vpa.forex_data.decoder import EPOCH_BASE_MS, decode_feed
from vpa.tests.forex_data.helpers import encode_records

# Full signed Int32 range for the open/high/low/close/volume fields.
_INT32_MIN = -(2**31)
_INT32_MAX = 2**31 - 1
_int32 = st.integers(min_value=_INT32_MIN, max_value=_INT32_MAX)

# The time field is kept non-negative and modest so the derived millisecond
# timestamps stay in a sane, valid range (EPOCH_BASE_MS + time_field * 60000).
# ~5.6M minutes is well over a decade of M1 bars, which is plenty for the test.
_time_field = st.integers(min_value=0, max_value=5_600_000)


@st.composite
def _feed_inputs(draw):
    """Draw (records, size, price_scale, volume_scale) for a round-trip case.

    A single record size (24 or 28) is drawn per buffer, matching the decoder's
    per-feed (not per-record) size detection. Each record is a six-field Int32
    tuple ``(time_field, open_i, high_i, low_i, close_i, volume_i)`` accepted by
    ``encode_records`` at either size (a 28-byte buffer pads the spread to 0).

    Round-trip is only well defined for buffers the decoder can unambiguously
    resolve back to their source size. Because ``decode_feed`` checks the
    28-byte record shape before the 24-byte one, a 24-byte buffer whose byte
    length is also a multiple of 28 would be misread as 28-byte records
    (``24 * N`` is a multiple of 28 exactly when ``N`` is a multiple of 7).
    Such ambiguous counts are excluded for the 24-byte case; 28-byte buffers are
    always unambiguous because 28 is tried first.
    """
    size = draw(st.sampled_from([24, 28]))
    records = draw(
        st.lists(
            st.tuples(_time_field, _int32, _int32, _int32, _int32, _int32),
            min_size=1,
            max_size=50,
        )
    )
    if size == 24:
        # Drop trailing records until the count is not a multiple of 7, keeping
        # the buffer unambiguously a 24-byte feed (len not divisible by 28).
        while len(records) % 7 == 0:
            records = records[:-1]
    price_scale = draw(st.integers(min_value=1, max_value=1_000_000))
    volume_scale = draw(st.integers(min_value=1, max_value=1_000_000))
    return records, size, price_scale, volume_scale


# Feature: replace-selenium-forex-scraping, Property 1: Decode round-trip recovers field values
@settings(max_examples=200)
@given(_feed_inputs())
def test_decode_round_trip_recovers_field_values(feed_inputs):
    """Property 1: decoding an encoded feed recovers every source field value.

    For any list of synthetic Int32 field tuples encoded into a ``.lb`` buffer at
    either the 24- or 28-byte record size and gzipped, ``decode_feed`` yields
    records — in the same order and count as the source — whose
    ``timestamp_ms == 946684800000 + time_field * 60000``, whose
    ``open/high/low/close == field / price_scale``, and whose
    ``volume == ceil((volume_i or 1) / volume_scale)``.

    **Validates: Requirements 2.1, 2.2, 2.5, 2.6, 2.7, 2.8**
    """
    records, size, price_scale, volume_scale = feed_inputs

    buf = encode_records(records, size)
    decoded = decode_feed(buf, price_scale, volume_scale)

    # Count is preserved (Requirements 2.1, 2.5).
    assert len(decoded) == len(records)

    for source, result in zip(records, decoded):
        time_field, open_i, high_i, low_i, close_i, volume_i = source

        # Timestamp derivation (Requirements 2.2, 2.6).
        assert result.timestamp_ms == EPOCH_BASE_MS + time_field * 60000

        # Price derivations divide the raw field by the price scale (Requirement 2.7).
        assert result.open == pytest.approx(open_i / price_scale)
        assert result.high == pytest.approx(high_i / price_scale)
        assert result.low == pytest.approx(low_i / price_scale)
        assert result.close == pytest.approx(close_i / price_scale)

        # Volume: zero is treated as 1 before the ceil-division (Requirement 2.8).
        assert result.volume == math.ceil((volume_i or 1) / volume_scale)
