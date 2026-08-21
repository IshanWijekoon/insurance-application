"""Number plate detection and reading.

Pipeline: locate plate-shaped candidate regions with OpenCV → crop → read the crop with the
vision model (a tight crop reads far more accurately than a full vehicle photo) → optionally
cross-check with local Tesseract.

Every stage is allowed to fail. A plate that cannot be read produces a low confidence and a
request for the customer to confirm the registration, which is the honest outcome — plates
are frequently obscured, angled, dirty or simply outside the frame.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import cv2
import numpy as np

from app.core.logging import get_logger

log = get_logger(__name__)

# Plates are wide rectangles. These bounds are deliberately generous to cover angled shots
# and the different aspect ratios used across markets.
_MIN_ASPECT = 1.8
_MAX_ASPECT = 6.5
_MIN_AREA_FRACTION = 0.0008
_MAX_AREA_FRACTION = 0.25

_PLATE_CHARS = re.compile(r"[^A-Z0-9\- ]")


@dataclass
class PlateCandidate:
    box: dict[str, float]  # normalised x, y, w, h
    score: float


def find_plate_candidates(image_bytes: bytes, limit: int = 3) -> list[PlateCandidate]:
    """Locate plate-shaped bright rectangles, best first."""
    try:
        array = np.frombuffer(image_bytes, dtype=np.uint8)
        image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    except Exception as exc:  # noqa: BLE001
        log.debug("ocr.decode_failed", error=str(exc))
        return []

    if image is None:
        return []

    height, width = image.shape[:2]
    total_area = float(height * width)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 11, 17, 17)

    # A blackhat transform makes dark characters on a light plate pop out of the background.
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 7))
    blackhat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, kernel)

    gradient = cv2.Sobel(blackhat, ddepth=cv2.CV_32F, dx=1, dy=0, ksize=-1)
    gradient = np.absolute(gradient)
    span = gradient.max() - gradient.min()
    if span <= 0:
        return []
    gradient = (255 * ((gradient - gradient.min()) / span)).astype("uint8")

    gradient = cv2.GaussianBlur(gradient, (5, 5), 0)
    gradient = cv2.morphologyEx(gradient, cv2.MORPH_CLOSE, kernel)
    _, threshold = cv2.threshold(gradient, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    threshold = cv2.dilate(threshold, None, iterations=2)

    contours, _ = cv2.findContours(threshold, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidates: list[PlateCandidate] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if h == 0:
            continue

        aspect = w / h
        area_fraction = (w * h) / total_area

        if not (_MIN_ASPECT <= aspect <= _MAX_ASPECT):
            continue
        if not (_MIN_AREA_FRACTION <= area_fraction <= _MAX_AREA_FRACTION):
            continue

        # Prefer regions in the lower half of the frame — where plates almost always sit —
        # and penalise implausibly extreme aspect ratios.
        vertical_bias = 1.0 if (y + h / 2) > height * 0.4 else 0.6
        aspect_fit = 1.0 - min(1.0, abs(aspect - 3.2) / 3.2)
        score = round(aspect_fit * vertical_bias * min(1.0, area_fraction * 200), 3)

        candidates.append(
            PlateCandidate(
                box={"x": x / width, "y": y / height, "w": w / width, "h": h / height},
                score=score,
            )
        )

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[:limit]


def read_with_tesseract(image_bytes: bytes) -> tuple[str | None, float]:
    """Local OCR cross-check. Returns ``(text, confidence)``.

    Used to corroborate the vision model, not to replace it. When both agree the confidence
    is raised; when they disagree neither is trusted and the customer is asked to confirm.
    """
    try:
        import pytesseract
        from PIL import Image
        import io
    except ImportError:
        return None, 0.0

    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("L")
        data = pytesseract.image_to_data(
            image,
            config="--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789- ",
            output_type=pytesseract.Output.DICT,
        )
    except Exception as exc:  # noqa: BLE001 — tesseract may not be installed
        log.debug("ocr.tesseract_unavailable", error=str(exc))
        return None, 0.0

    words: list[str] = []
    confidences: list[float] = []
    for text, confidence in zip(data.get("text", []), data.get("conf", []), strict=False):
        cleaned = _PLATE_CHARS.sub("", (text or "").upper()).strip()
        try:
            value = float(confidence)
        except (TypeError, ValueError):
            continue
        if cleaned and value > 0:
            words.append(cleaned)
            confidences.append(value)

    if not words:
        return None, 0.0

    reading = " ".join(words).strip()
    if len(reading) < 3:
        return None, 0.0

    return reading, round(sum(confidences) / len(confidences) / 100, 3)


def normalise_plate(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = _PLATE_CHARS.sub("", value.upper())
    cleaned = " ".join(cleaned.split())
    return cleaned if 2 <= len(cleaned) <= 32 else None


def reconcile_readings(
    vision_text: str | None,
    vision_confidence: float,
    tesseract_text: str | None,
    tesseract_confidence: float,
) -> tuple[str | None, float, str]:
    """Combine the two readings into one answer plus a note explaining the confidence."""
    vision = normalise_plate(vision_text)
    tesseract = normalise_plate(tesseract_text)

    if vision and tesseract:
        compact_vision = vision.replace(" ", "").replace("-", "")
        compact_tesseract = tesseract.replace(" ", "").replace("-", "")

        if compact_vision == compact_tesseract:
            return (
                vision,
                round(min(0.97, max(vision_confidence, tesseract_confidence) + 0.12), 3),
                "Two independent readers produced the same registration.",
            )

        return (
            vision,
            round(min(vision_confidence, 0.5), 3),
            f"The two readers disagreed ('{vision}' and '{tesseract}'). "
            "Ask the customer to confirm the registration.",
        )

    if vision:
        return vision, vision_confidence, "Read by the vision model only."
    if tesseract:
        return (
            tesseract,
            round(tesseract_confidence * 0.8, 3),
            "Read by local OCR only; the vision model could not read the plate.",
        )

    return None, 0.0, "No registration could be read from the supplied photographs."
