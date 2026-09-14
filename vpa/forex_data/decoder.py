"""Pure decoder for the gzipped Dukascopy binary feed.

Decompresses a ``.lb.gz`` feed, detects the record size (24 or 28 bytes),
and decodes the little-endian Int32 fields into immutable :class:`Record`
instances. This module is pure and deterministic: no network, no globals,
identical output for identical input (Requirements 9.1, 9.3).
"""

import gzip
import math
import struct
from dataclasses import dataclass

from vpa.forex_data.errors import FeedDecodeError

# Check the 28-byte spread-record shape first, matching forexsb's own app.js.
RECORD_SIZES = (28, 24)
# Epoch base = 2000-01-01T00:00:00Z, in milliseconds since the Unix epoch.
EPOCH_BASE_MS = 946684800000

# The six leading little-endian Int32 fields shared by both record sizes.
_FIELD_STRUCT = struct.Struct("<6i")


@dataclass(frozen=True)
class Record:
    """A single decoded intraday bar."""

    timestamp_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: int


def decode_feed(
    raw_gz_bytes: bytes,
    price_scale: int,
    volume_scale: int,
) -> list[Record]:
    """Decode a gzipped Dukascopy binary feed into intraday records.

    Decompresses ``raw_gz_bytes``, detects the record size, and decodes the
    leading six little-endian Int32 fields of each record. Pure and
    deterministic — no network, no globals.

    Args:
        raw_gz_bytes: The raw gzipped feed bytes.
        price_scale: Per-symbol divisor for open/high/low/close.
        volume_scale: Per-symbol divisor for volume.

    Returns:
        Records in file order (already chronological). An empty buffer
        yields an empty list.

    Raises:
        FeedDecodeError: If the bytes cannot be decompressed (Requirement
            6.4) or the decompressed length is not a multiple of a supported
            record size (Requirement 2.3).
    """
    # 1. Decompress; any gzip failure is a decode failure (Requirement 6.4).
    try:
        buf = gzip.decompress(raw_gz_bytes)
    except Exception as exc:
        raise FeedDecodeError(f"Failed to decompress feed: {exc}") from exc

    # 2. Empty buffer -> no records, no error (Requirement 2.4).
    if len(buf) == 0:
        return []

    # 3. Detect record size, 28 first then 24 (Requirements 2.2, 2.3).
    for size in RECORD_SIZES:
        if len(buf) % size == 0:
            record_size = size
            break
    else:
        raise FeedDecodeError(
            f"Decompressed feed length {len(buf)} is not a multiple of a "
            f"supported record size {RECORD_SIZES}"
        )

    # 4. Decode each record's leading six Int32 fields (Requirement 2.5).
    records: list[Record] = []
    for offset in range(0, len(buf), record_size):
        time_field, open_i, high_i, low_i, close_i, volume_i = _FIELD_STRUCT.unpack_from(
            buf, offset
        )
        records.append(
            Record(
                timestamp_ms=EPOCH_BASE_MS + time_field * 60000,  # Requirement 2.6
                open=open_i / price_scale,  # Requirement 2.7
                high=high_i / price_scale,
                low=low_i / price_scale,
                close=close_i / price_scale,
                volume=math.ceil((volume_i or 1) / volume_scale),  # Requirement 2.8
            )
        )

    # 5. Records are already in chronological file order.
    return records
