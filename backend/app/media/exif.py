"""EXIF extraction.

The contract: report only what the file actually contains. If there is no EXIF block, the
result says so. Upload time is never presented as capture time, and a missing GPS tag is
never filled in from anywhere else at this layer.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from PIL import ExifTags, Image

from app.core.logging import get_logger

log = get_logger(__name__)

_TAGS = {v: k for k, v in ExifTags.TAGS.items()}
_GPS_TAGS = {v: k for k, v in ExifTags.GPSTAGS.items()}

# Values that are meaningless to store and would only pollute the JSONB column.
_SKIP_TAGS = {"MakerNote", "UserComment", "PrintImageMatching", "ImageDescription"}


@dataclass
class ExifData:
    has_exif: bool = False
    captured_at: datetime | None = None
    gps_latitude: float | None = None
    gps_longitude: float | None = None
    gps_altitude: float | None = None
    camera_make: str | None = None
    camera_model: str | None = None
    software: str | None = None
    orientation: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def has_gps(self) -> bool:
        return self.gps_latitude is not None and self.gps_longitude is not None


def _to_float(value: Any) -> float | None:
    try:
        if isinstance(value, (tuple, list)) and len(value) == 2 and not isinstance(value[0], (tuple, list)):
            return float(value[0]) / float(value[1]) if value[1] else None
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _as_ref(ref: Any) -> str | None:
    if ref is None:
        return None
    if isinstance(ref, bytes):
        return ref.decode("ascii", errors="ignore")
    return str(ref)


def _dms_to_degrees(dms: Any, ref: str | None) -> float | None:
    """Convert EXIF degrees/minutes/seconds into a signed decimal degree."""
    if dms is None:
        return None
    if isinstance(dms, (int, float)):
        decimal = float(dms)
    else:
        try:
            parts = list(dms)
        except TypeError:
            return None
        if len(parts) == 1:
            decimal = _to_float(parts[0])
            if decimal is None:
                return None
        elif len(parts) == 3:
            degrees, minutes, seconds = (_to_float(v) for v in parts)
            if degrees is None or minutes is None or seconds is None:
                return None
            decimal = degrees + minutes / 60 + seconds / 3600
        else:
            return None

    ref_s = _as_ref(ref)
    if ref_s and ref_s.upper()[:1] in {"S", "W"}:
        decimal = -abs(decimal)

    if not -180 <= decimal <= 180:
        return None
    return round(decimal, 7)


def _parse_datetime(raw: Any, offset: Any = None) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M"):
        try:
            parsed = datetime.strptime(raw.strip(), fmt)
        except ValueError:
            continue

        if isinstance(offset, str) and len(offset) >= 6:
            try:
                sign = 1 if offset[0] == "+" else -1
                hours, minutes = int(offset[1:3]), int(offset[4:6])
                from datetime import timedelta, timezone

                return parsed.replace(
                    tzinfo=timezone(sign * timedelta(hours=hours, minutes=minutes))
                )
            except (ValueError, IndexError):
                pass
        # No offset recorded: treat as UTC and let the UI label it as camera-local.
        return parsed.replace(tzinfo=UTC)
    return None


def _jsonable(value: Any) -> Any:
    if isinstance(value, bytes):
        return value[:64].hex()
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, (int, float, str, bool, type(None))):
        return value
    return str(value)[:200]


def extract_exif(data: bytes) -> ExifData:
    result = ExifData()

    try:
        image = Image.open(io.BytesIO(data))
        exif = image.getexif()
    except Exception as exc:  # noqa: BLE001 — a bad EXIF block must not fail an upload
        log.debug("exif.read_failed", error=str(exc))
        _apply_piexif_gps(result, data)
        return result

    if not exif:
        _apply_piexif_gps(result, data)
        return result

    result.has_exif = True
    tags = {ExifTags.TAGS.get(tag_id, str(tag_id)): value for tag_id, value in exif.items()}

    ifd_values: dict[str, Any] = {}
    try:
        exif_ifd = exif.get_ifd(_TAGS.get("ExifOffset", 0x8769))
        ifd_values = {
            ExifTags.TAGS.get(tag_id, str(tag_id)): value for tag_id, value in exif_ifd.items()
        }
    except (KeyError, AttributeError, OSError):
        ifd_values = {}

    merged = {**tags, **ifd_values}

    result.camera_make = str(merged.get("Make", "")).strip() or None
    result.camera_model = str(merged.get("Model", "")).strip() or None
    result.software = str(merged.get("Software", "")).strip() or None
    try:
        result.orientation = int(merged["Orientation"]) if "Orientation" in merged else None
    except (TypeError, ValueError):
        result.orientation = None

    result.captured_at = (
        _parse_datetime(merged.get("DateTimeOriginal"), merged.get("OffsetTimeOriginal"))
        or _parse_datetime(merged.get("DateTimeDigitized"), merged.get("OffsetTimeDigitized"))
        or _parse_datetime(merged.get("DateTime"), merged.get("OffsetTime"))
    )

    gps_ifd: dict[Any, Any] = {}
    for tag in (getattr(getattr(ExifTags, "IFD", None), "GPSInfo", None), _TAGS.get("GPSInfo", 0x8825)):
        if tag is None or gps_ifd:
            continue
        try:
            gps_ifd = dict(exif.get_ifd(tag))
        except (KeyError, AttributeError, OSError, TypeError, ValueError):
            gps_ifd = {}
    if not gps_ifd:
        raw_gps = exif.get(0x8825)
        gps_ifd = dict(raw_gps) if isinstance(raw_gps, dict) else {}

    _apply_gps(result, gps_ifd)

    result.raw.update(
        {k: _jsonable(v) for k, v in merged.items() if k not in _SKIP_TAGS}
    )

    if not result.has_gps:
        _apply_piexif_gps(result, data)
    return result


def _apply_gps(result: ExifData, gps_ifd: dict[Any, Any]) -> None:
    if not gps_ifd:
        return
    gps = {ExifTags.GPSTAGS.get(tag_id, str(tag_id)): value for tag_id, value in gps_ifd.items()}
    latitude = _dms_to_degrees(gps.get("GPSLatitude"), gps.get("GPSLatitudeRef"))
    longitude = _dms_to_degrees(gps.get("GPSLongitude"), gps.get("GPSLongitudeRef"))

    # A 0,0 fix is Null Island — almost always a sensor placeholder, not a real location.
    if latitude is not None and longitude is not None and (latitude, longitude) != (0.0, 0.0):
        result.gps_latitude = latitude
        result.gps_longitude = longitude

    altitude = _to_float(gps.get("GPSAltitude"))
    if altitude is not None:
        ref = gps.get("GPSAltitudeRef")
        below_sea_level = ref in (1, b"\x01")
        result.gps_altitude = -altitude if below_sea_level else altitude

    result.raw["gps"] = {k: _jsonable(v) for k, v in gps.items()}


def _apply_piexif_gps(result: ExifData, data: bytes) -> None:
    """Pillow misses GPS on some phone JPEGs; piexif reads the APP1 block directly."""
    try:
        import piexif
    except ImportError:
        return
    try:
        parsed = piexif.load(data)
    except Exception as exc:  # noqa: BLE001 — unreadable EXIF must not fail an upload
        log.debug("exif.piexif_failed", error=str(exc))
        return

    gps = parsed.get("GPS") or {}
    if not gps:
        return

    result.has_exif = True
    latitude = _dms_to_degrees(gps.get(piexif.GPSIFD.GPSLatitude), gps.get(piexif.GPSIFD.GPSLatitudeRef))
    longitude = _dms_to_degrees(gps.get(piexif.GPSIFD.GPSLongitude), gps.get(piexif.GPSIFD.GPSLongitudeRef))
    if latitude is not None and longitude is not None and (latitude, longitude) != (0.0, 0.0):
        result.gps_latitude = latitude
        result.gps_longitude = longitude

    altitude = _to_float(gps.get(piexif.GPSIFD.GPSAltitude))
    if altitude is not None:
        ref = gps.get(piexif.GPSIFD.GPSAltitudeRef)
        result.gps_altitude = -altitude if ref in (1, b"\x01") else altitude

    result.raw.setdefault("gps", {str(k): _jsonable(v) for k, v in gps.items()})
