"""Server-side rendering of customer annotations onto a copy of the image.

The frontend draws on a canvas, but the rendered overlay is produced here so the stored
annotated image is reproducible from the coordinates and cannot be replaced with an
arbitrary picture uploaded by the client.
"""

from __future__ import annotations

import io
from collections.abc import Sequence

from PIL import Image, ImageDraw, ImageFont

from app.core.enums import AnnotationType

DEFAULT_COLOR = "#EF4444"


def _hex_to_rgb(value: str | None) -> tuple[int, int, int]:
    raw = (value or DEFAULT_COLOR).lstrip("#")
    if len(raw) != 6:
        raw = DEFAULT_COLOR.lstrip("#")
    try:
        return tuple(int(raw[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return (239, 68, 68)


def _points(region: dict) -> list[tuple[float, float]]:
    return [(float(p[0]), float(p[1])) for p in region.get("points", []) if len(p) == 2]


def render_annotated_image(data: bytes, regions: Sequence[dict]) -> bytes:
    """Draw every region onto the image and return JPEG bytes."""
    base = Image.open(io.BytesIO(data)).convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    try:
        font = ImageFont.truetype("DejaVuSans.ttf", max(14, base.width // 60))
    except OSError:
        font = ImageFont.load_default()

    for region in regions:
        points = _points(region)
        if not points:
            continue

        rgb = _hex_to_rgb(region.get("color"))
        stroke = int(region.get("stroke_width") or 3)
        outline = (*rgb, 255)
        fill = (*rgb, 48)
        kind = region.get("annotation_type")

        if kind == AnnotationType.RECTANGLE and len(points) >= 2:
            (x1, y1), (x2, y2) = points[0], points[1]
            draw.rectangle(
                [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)],
                outline=outline, fill=fill, width=stroke,
            )
        elif kind == AnnotationType.CIRCLE and len(points) >= 2:
            (cx, cy), (px, py) = points[0], points[1]
            radius = ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5
            draw.ellipse(
                [cx - radius, cy - radius, cx + radius, cy + radius],
                outline=outline, fill=fill, width=stroke,
            )
        elif kind == AnnotationType.POLYGON and len(points) >= 3:
            draw.polygon(points, outline=outline, fill=fill)
            draw.line([*points, points[0]], fill=outline, width=stroke)
        elif kind == AnnotationType.FREEHAND and len(points) >= 2:
            draw.line(points, fill=outline, width=stroke, joint="curve")
        elif kind == AnnotationType.TEXT:
            draw.text(points[0], str(region.get("text_content") or ""), fill=outline, font=font)

        label = region.get("label")
        if label and kind != AnnotationType.TEXT:
            anchor = min(points, key=lambda p: (p[1], p[0]))
            text = str(label).replace("_", " ")
            box = draw.textbbox((0, 0), text, font=font)
            pad = 4
            draw.rectangle(
                [
                    anchor[0], max(0, anchor[1] - (box[3] - box[1]) - pad * 2),
                    anchor[0] + (box[2] - box[0]) + pad * 2, anchor[1],
                ],
                fill=(*rgb, 220),
            )
            draw.text(
                (anchor[0] + pad, max(0, anchor[1] - (box[3] - box[1]) - pad)),
                text, fill=(255, 255, 255, 255), font=font,
            )

    composed = Image.alpha_composite(base, overlay).convert("RGB")
    buffer = io.BytesIO()
    composed.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def annotation_coverage(regions: Sequence[dict], width: int, height: int) -> float:
    """Rough fraction of the image the customer marked, used as a sanity signal.

    A customer circling 90 % of the photo is not localising damage, and the pipeline
    treats that annotation as weak evidence rather than a precise region.
    """
    if not width or not height:
        return 0.0

    total = 0.0
    for region in regions:
        points = _points(region)
        if len(points) < 2:
            continue
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        total += max(0.0, (max(xs) - min(xs))) * max(0.0, (max(ys) - min(ys)))

    return min(1.0, total / (width * height))
