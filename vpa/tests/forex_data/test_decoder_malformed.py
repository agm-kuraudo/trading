"""Property test for malformed feed buffer length rejection (Property 2).

``decode_feed`` decompresses its input first, then requires the *decompressed*
length to be a positive multiple of a supported record size (28 or 24 bytes).
A decompressed buffer whose length is greater than zero but not divisible by
either 24 or 28 is malformed: the decoder must raise :class:`FeedDecodeError`
and emit no records.

This module deliberately lives in a separate file from the decode round-trip
property test (``test_decoder_properties.py``, task 2.3) to avoid collision.

Requirements: 2.3.
"""

import gzip

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vpa.forex_data.decoder import decode_feed
from vpa.forex_data.errors import FeedDecodeError

# Positive integer lengths that are malformed: greater than zero and divisible
# by neither 24 nor 28. The assume() rejects the (few) valid multiples so every
# generated length is a genuine malformed case.
_MALFORMED_LENGTH = st.integers(min_value=1, max_value=2000).filter(
    lambda length: length % 24 != 0 and length % 28 != 0
)


# Feature: replace-selenium-forex-scraping, Property 2: Malformed buffer length is rejected
@settings(max_examples=100)
@given(
    length=_MALFORMED_LENGTH,
    price_scale=st.integers(min_value=1, max_value=100000),
    volume_scale=st.integers(min_value=1, max_value=100000),
)
def test_malformed_buffer_length_is_rejected(length, price_scale, volume_scale):
    """Property 2: a decompressed buffer whose length is > 0 and not a multiple
    of 24 or 28 causes ``decode_feed`` to raise ``FeedDecodeError`` and emit no
    records.

    The synthetic payload is a raw byte buffer of the malformed length, gzipped
    with ``gzip.compress`` so that ``decode_feed`` decompresses it back to the
    malformed length before the record-size check runs. The ``pytest.raises``
    guard also proves no record list is returned.

    **Validates: Requirements 2.3**
    """
    payload = b"\x00" * length
    assert len(payload) % 24 != 0 and len(payload) % 28 != 0

    with pytest.raises(FeedDecodeError):
        decode_feed(gzip.compress(payload), price_scale, volume_scale)
