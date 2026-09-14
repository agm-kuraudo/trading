"""Shared test helpers for the ``vpa.forex_data`` feature tests (SP-309).

Provides :func:`encode_records`, the inverse of
:func:`vpa.forex_data.decoder.decode_feed`'s on-the-wire format. It packs raw
INT32 field values into a little-endian ``.lb`` buffer (24- or 28-byte records)
and gzips them, so decode round-trip and other property tests (tasks 2.3, 2.4)
can generate valid feed inputs without touching the network.

Dependency-free: only stdlib ``struct`` and ``gzip`` are used.
"""

import gzip
import struct
from collections.abc import Iterable

# The six leading little-endian Int32 fields shared by both record sizes:
# (time, open, high, low, close, volume).
_FIELD_STRUCT = struct.Struct("<6i")
# The trailing spread Int32 present only in 28-byte "spread record" variants.
_SPREAD_STRUCT = struct.Struct("<i")

# Supported on-the-wire record sizes, matching decoder.RECORD_SIZES.
_SUPPORTED_SIZES = (24, 28)


def encode_records(records: Iterable[tuple[int, ...]], size: int) -> bytes:
    """Encode raw INT32 field tuples into a gzipped ``.lb`` feed buffer.

    This is the inverse of :func:`vpa.forex_data.decoder.decode_feed`'s
    on-the-wire format, so round-trip property tests can generate valid inputs.
    Each record is packed as little-endian Int32 fields, all records are
    concatenated in order, and the concatenated buffer is gzipped (because
    ``decode_feed`` expects raw gzipped bytes).

    Args:
        records: An iterable of tuples of **raw INT32 field values**
            (pre-scaling). For ``size == 24`` each tuple is
            ``(time_field, open_i, high_i, low_i, close_i, volume_i)``. For
            ``size == 28`` each tuple is the same six fields plus a trailing
            ``spread_i`` (7th field). A 6-tuple is always accepted; when
            ``size == 28`` a missing spread is padded with ``0``.
        size: The record size in bytes. Must be ``24`` or ``28``.

    Returns:
        The gzipped little-endian ``.lb`` buffer, ready to pass straight to
        ``decode_feed``.

    Raises:
        ValueError: If ``size`` is not 24 or 28, or if a record tuple does not
            have a field count compatible with ``size``.
    """
    if size not in _SUPPORTED_SIZES:
        raise ValueError(f"Unsupported record size {size!r}; expected one of {_SUPPORTED_SIZES}")

    chunks: list[bytes] = []
    for index, record in enumerate(records):
        fields = tuple(record)

        if size == 24:
            if len(fields) not in (6, 7):
                raise ValueError(
                    f"Record {index} has {len(fields)} fields; size 24 expects 6 "
                    f"(a trailing spread is ignored for 24-byte records)"
                )
            chunks.append(_FIELD_STRUCT.pack(*fields[:6]))
        else:  # size == 28
            if len(fields) == 6:
                six_fields, spread = fields, 0
            elif len(fields) == 7:
                six_fields, spread = fields[:6], fields[6]
            else:
                raise ValueError(
                    f"Record {index} has {len(fields)} fields; size 28 expects 6 "
                    f"(spread padded to 0) or 7 (with trailing spread)"
                )
            chunks.append(_FIELD_STRUCT.pack(*six_fields) + _SPREAD_STRUCT.pack(spread))

    return gzip.compress(b"".join(chunks))
