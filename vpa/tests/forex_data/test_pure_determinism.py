"""Property-based determinism test for the pure forex functions (SP-309, task 4.1).

Exercises the cross-cutting determinism guarantee of the two pure functions in
the browserless retriever: :func:`vpa.forex_data.decoder.decode_feed` and
:func:`vpa.forex_data.aggregator.aggregate_to_daily`. Both are pure and offline
— they take already-fetched gzipped bytes / already-decoded records and touch no
network or globals — so these tests drive them directly with synthetic ``.lb``
buffers built by the shared :func:`vpa.tests.forex_data.helpers.encode_records`
helper. No socket is ever opened (Requirement 9.3).

Property 9 is the universal determinism form: for any input byte buffer, two
invocations of ``decode_feed`` on the SAME bytes return equal record lists; and
for any set of decoded records, two invocations of ``aggregate_to_daily`` on the
SAME records return DataFrames identical in count, ordering, and per-bar field
values. ``Record`` is a frozen dataclass so ``==`` compares field-by-field, and
``pandas.testing.assert_frame_equal`` compares the two aggregated frames exactly.

The generators only vary inputs to widen the space over which repeated-call
determinism is demonstrated; each example encodes its own buffer, decodes it
twice, aggregates twice, and compares that example's two results — never across
examples.
"""

import pandas as pd
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from vpa.forex_data.aggregator import aggregate_to_daily
from vpa.forex_data.decoder import decode_feed
from vpa.tests.forex_data.helpers import encode_records

# Full signed Int32 range for the open/high/low/close/volume fields.
_INT32_MIN = -(2**31)
_INT32_MAX = 2**31 - 1
_int32 = st.integers(min_value=_INT32_MIN, max_value=_INT32_MAX)

# The time field is kept non-negative and modest so the derived millisecond
# timestamps stay in a sane, valid range (EPOCH_BASE_MS + time_field * 60000).
# ~5.6M minutes is well over a decade of M1 bars, which spans many UTC days.
# Keep decoded timestamps inside Pandas' supported nanosecond range. The
# decoder's epoch is 2000-01-01 and each unit is one minute.
_time_field = st.integers(min_value=0, max_value=1_000_000)


@st.composite
def _feed_inputs(draw):
    """Draw (buf, price_scale, volume_scale) for a determinism case.

    A single record size (24 or 28) is drawn per buffer, matching the decoder's
    per-feed (not per-record) size detection. Each record is a six-field Int32
    tuple ``(time_field, open_i, high_i, low_i, close_i, volume_i)`` accepted by
    ``encode_records`` at either size (a 28-byte buffer pads the spread to 0).
    The records are encoded into a single gzipped ``.lb`` buffer up front so both
    decode invocations operate on the exact same bytes.
    """
    size = draw(st.sampled_from([24, 28]))
    records = draw(
        st.lists(
            st.tuples(_time_field, _int32, _int32, _int32, _int32, _int32),
            min_size=1,
            max_size=50,
        )
    )
    price_scale = draw(st.integers(min_value=1, max_value=1_000_000))
    volume_scale = draw(st.integers(min_value=1, max_value=1_000_000))
    return encode_records(records, size), price_scale, volume_scale


# Feature: replace-selenium-forex-scraping, Property 9: Decode and aggregation are deterministic
@settings(max_examples=100)
@given(_feed_inputs())
def test_decode_and_aggregation_are_deterministic(feed_inputs):
    """Property 9: repeated decode and aggregation on identical inputs are identical.

    For any gzipped ``.lb`` buffer, invoking ``decode_feed`` twice on the SAME
    bytes yields equal record lists (``Record`` is a frozen dataclass, so list
    equality is a field-by-field comparison). Aggregating those records and
    invoking ``aggregate_to_daily`` twice on the SAME records yields DataFrames
    identical in count, ordering, and per-bar field values, as asserted by
    ``pandas.testing.assert_frame_equal``.

    **Validates: Requirements 9.1, 9.2**
    """
    buf, price_scale, volume_scale = feed_inputs

    # Two decode invocations on the SAME bytes return equal record lists (Req 9.1).
    decoded_first = decode_feed(buf, price_scale, volume_scale)
    decoded_second = decode_feed(buf, price_scale, volume_scale)
    assert decoded_first == decoded_second
    assume(all(0 <= record.timestamp_ms <= 9_000_000_000_000 for record in decoded_first))

    # Two aggregation invocations on the SAME records return identical frames in
    # count, ordering, and per-bar field values (Req 9.2).
    daily_first = aggregate_to_daily(decoded_first)
    daily_second = aggregate_to_daily(decoded_first)
    pd.testing.assert_frame_equal(daily_first, daily_second)
