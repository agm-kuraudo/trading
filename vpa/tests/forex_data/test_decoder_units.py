"""Unit test for the zero-length feed buffer case (task 2.5).

``decode_feed`` decompresses its input before doing anything else. When the
*decompressed* buffer is empty, the decoder must treat it as "no data" and
return an empty list without raising (Requirement 2.4).

To exercise this deterministically, the input is ``gzip.compress(b"")`` — a
valid gzip stream that decompresses back to a zero-length buffer. This module
lives alongside, but distinct from, the decode property tests
(``test_decoder_properties.py``, ``test_decoder_malformed.py``).

Requirements: 2.4.
"""

import gzip

from vpa.forex_data.decoder import decode_feed


def test_zero_length_buffer_decodes_to_empty_list():
    """A gzipped empty buffer decodes to ``[]`` with no exception raised.

    ``gzip.compress(b"")`` decompresses to a zero-length buffer, which the
    decoder returns as an empty record list before any record-size check runs.
    No exception may be raised.

    Requirements: 2.4.
    """
    result = decode_feed(gzip.compress(b""), price_scale=100000, volume_scale=1)

    assert result == []
