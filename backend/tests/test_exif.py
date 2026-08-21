"""EXIF GPS must come from the file itself, never from a guessed location."""

from __future__ import annotations

import io

import piexif
import pytest
from PIL import Image

from app.media.exif import extract_exif


def _jpeg_with_gps(lat: float = 6.9270786, lng: float = 79.861243) -> bytes:
    image = Image.new("RGB", (640, 480), (30, 40, 50))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)

    def dms(value: float) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]]:
        absolute = abs(value)
        degrees = int(absolute)
        minutes_full = (absolute - degrees) * 60
        minutes = int(minutes_full)
        seconds = round((minutes_full - minutes) * 60 * 10_000)
        return ((degrees, 1), (minutes, 1), (seconds, 10_000))

    exif_bytes = piexif.dump(
        {
            "0th": {piexif.ImageIFD.Make: b"TestCam", piexif.ImageIFD.Model: b"Fixture"},
            "Exif": {},
            "GPS": {
                piexif.GPSIFD.GPSLatitudeRef: b"N" if lat >= 0 else b"S",
                piexif.GPSIFD.GPSLatitude: dms(lat),
                piexif.GPSIFD.GPSLongitudeRef: b"E" if lng >= 0 else b"W",
                piexif.GPSIFD.GPSLongitude: dms(lng),
            },
            "1st": {},
            "thumbnail": None,
        }
    )
    out = io.BytesIO()
    piexif.insert(exif_bytes, buffer.getvalue(), out)
    return out.getvalue()


def test_extracts_gps_from_jpeg_exif():
    data = _jpeg_with_gps()
    result = extract_exif(data)
    assert result.has_exif is True
    assert result.has_gps is True
    assert result.gps_latitude == pytest.approx(6.9270786, abs=1e-5)
    assert result.gps_longitude == pytest.approx(79.861243, abs=1e-5)


def test_plain_jpeg_has_no_invented_gps():
    buffer = io.BytesIO()
    Image.new("RGB", (320, 240), "white").save(buffer, format="JPEG")
    result = extract_exif(buffer.getvalue())
    assert result.gps_latitude is None
    assert result.gps_longitude is None
    assert result.has_gps is False
