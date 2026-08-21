"""Image validation, hashing and quality scoring.

Runs before anything is stored. A rejected image never reaches the AI stage, and a
low-quality one is flagged so the assessment can say *why* it is uncertain rather than
quietly producing a weak result.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field

import cv2
import imagehash
import numpy as np
from PIL import Image, UnidentifiedImageError

from app.core.config import settings
from app.core.enums import ImageValidationStatus


@dataclass
class ImageInspection:
    status: ImageValidationStatus
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    width: int | None = None
    height: int | None = None
    sha256: str = ""
    perceptual_hash: str | None = None
    blur_score: float | None = None
    brightness_score: float | None = None
    quality_score: float | None = None

    @property
    def is_rejected(self) -> bool:
        return self.status is ImageValidationStatus.REJECTED

    @property
    def all_messages(self) -> list[str]:
        return [*self.errors, *self.warnings]


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _blur_score(gray: np.ndarray) -> float:
    """Variance of the Laplacian. Low variance means few sharp edges, i.e. a blurry photo."""
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _brightness_score(gray: np.ndarray) -> float:
    return float(np.mean(gray))


def inspect_image(data: bytes, content_type: str, filename: str = "") -> ImageInspection:
    result = ImageInspection(status=ImageValidationStatus.VALID, sha256=sha256_of(data))

    if content_type not in settings.allowed_image_types:
        result.status = ImageValidationStatus.REJECTED
        result.errors.append(
            f"Unsupported file type '{content_type}'. Upload a JPG, PNG or WEBP image."
        )
        return result

    if len(data) > settings.max_image_bytes:
        result.status = ImageValidationStatus.REJECTED
        result.errors.append(
            f"File is {len(data) / 1024 / 1024:.1f} MB; the limit is {settings.max_image_mb} MB."
        )
        return result

    if not data:
        result.status = ImageValidationStatus.REJECTED
        result.errors.append("The uploaded file is empty.")
        return result

    try:
        image = Image.open(io.BytesIO(data))
        image.verify()  # structural check; consumes the file object
        image = Image.open(io.BytesIO(data))
        rgb = image.convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError):
        result.status = ImageValidationStatus.REJECTED
        result.errors.append(
            "The file could not be read as an image. It may be corrupted or misnamed."
        )
        return result

    result.width, result.height = rgb.size

    if rgb.width < settings.min_image_width or rgb.height < settings.min_image_height:
        result.status = ImageValidationStatus.REJECTED
        result.errors.append(
            f"Image is {rgb.width}×{rgb.height}. At least "
            f"{settings.min_image_width}×{settings.min_image_height} is needed to assess damage."
        )
        return result

    try:
        result.perceptual_hash = str(imagehash.phash(rgb))
    except Exception:  # noqa: BLE001 — a missing hash must not block an upload
        result.perceptual_hash = None

    array = np.array(rgb)
    gray = cv2.cvtColor(array, cv2.COLOR_RGB2GRAY)
    result.blur_score = _blur_score(gray)
    result.brightness_score = _brightness_score(gray)

    if result.blur_score < settings.blur_score_threshold:
        result.status = ImageValidationStatus.WARNING
        result.warnings.append(
            "This photo looks blurry. Damage detection will be less reliable — "
            "consider retaking it with the camera held still."
        )
    if result.brightness_score < 45:
        result.status = ImageValidationStatus.WARNING
        result.warnings.append("This photo is very dark. Try again in better lighting.")
    elif result.brightness_score > 225:
        result.status = ImageValidationStatus.WARNING
        result.warnings.append("This photo is overexposed; detail in bright areas is lost.")

    result.quality_score = _quality_score(result)
    return result


def _quality_score(inspection: ImageInspection) -> float:
    """A 0–1 usability score combining sharpness, exposure and resolution."""
    blur = min(1.0, (inspection.blur_score or 0) / (settings.blur_score_threshold * 4))

    brightness = inspection.brightness_score or 0
    # Peaks at mid-grey (~128) and falls off toward pure black or pure white.
    exposure = max(0.0, 1.0 - abs(brightness - 128) / 128)

    pixels = (inspection.width or 0) * (inspection.height or 0)
    resolution = min(1.0, pixels / (1920 * 1080))

    return round(0.5 * blur + 0.3 * exposure + 0.2 * resolution, 3)


def to_jpeg_bytes(data: bytes, max_edge: int = 1600, quality: int = 85) -> bytes:
    """Downscale for provider upload.

    Vision providers charge by pixels and most cap the input anyway. The original is kept
    in storage untouched; only this derived copy is transmitted.
    """
    image = Image.open(io.BytesIO(data)).convert("RGB")
    if max(image.size) > max_edge:
        scale = max_edge / max(image.size)
        image = image.resize(
            (int(image.width * scale), int(image.height * scale)), Image.LANCZOS
        )
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()


def crop_normalised(data: bytes, box: dict[str, float], padding: float = 0.06) -> bytes:
    """Crop using a normalised 0–1 box, with a little context around it."""
    image = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = image.size
    x = max(0.0, box.get("x", 0) - padding)
    y = max(0.0, box.get("y", 0) - padding)
    x2 = min(1.0, box.get("x", 0) + box.get("w", 0) + padding)
    y2 = min(1.0, box.get("y", 0) + box.get("h", 0) + padding)
    cropped = image.crop((int(x * w), int(y * h), int(x2 * w), int(y2 * h)))
    buffer = io.BytesIO()
    cropped.save(buffer, format="JPEG", quality=92)
    return buffer.getvalue()


def hamming_distance(hash_a: str, hash_b: str) -> int | None:
    """Perceptual-hash distance; 0 is identical, under ~8 is visually the same photo."""
    try:
        return imagehash.hex_to_hash(hash_a) - imagehash.hex_to_hash(hash_b)
    except (ValueError, TypeError):
        return None
