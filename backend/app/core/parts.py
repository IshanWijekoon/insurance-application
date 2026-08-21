"""Canonical vehicle part taxonomy.

Web sources, customers and vision models all name the same physical component
differently ("front bumper", "front bumper cover", "bumper assembly", "front bumper shell").
Everything in the system is reduced to a code from this table before it is compared,
priced or aggregated.

`aliases` drives deterministic matching; the AI normalisation prompt is only consulted for
titles this table cannot resolve. Deterministic first, model second — it is cheaper, and it
is reproducible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.enums import DamageType


@dataclass(frozen=True)
class PartDefinition:
    code: str
    display_name: str
    group: str
    material: str  # PLASTIC | METAL | GLASS | COMPOSITE | RUBBER | MIXED
    paint_panels: float  # panels needing refinish when this part is worked on
    base_labour_hours: float  # hours for a straightforward replacement
    structural: bool = False
    repairable_damage: frozenset[DamageType] = field(default_factory=frozenset)
    aliases: tuple[str, ...] = ()


_PLASTIC_REPAIRABLE = frozenset(
    {DamageType.SCRATCH, DamageType.PAINT_DAMAGE, DamageType.DENT, DamageType.CRACK}
)
_METAL_REPAIRABLE = frozenset(
    {DamageType.SCRATCH, DamageType.PAINT_DAMAGE, DamageType.DENT, DamageType.DEFORMATION}
)
_NOT_REPAIRABLE: frozenset[DamageType] = frozenset()


PARTS: tuple[PartDefinition, ...] = (
    PartDefinition(
        "FRONT_BUMPER", "Front bumper", "FRONT", "PLASTIC", 1.0, 2.5,
        repairable_damage=_PLASTIC_REPAIRABLE,
        aliases=("front bumper", "front bumper cover", "front bumper assembly",
                 "front bumper shell", "bumper front", "f bumper", "front fascia"),
    ),
    PartDefinition(
        "REAR_BUMPER", "Rear bumper", "REAR", "PLASTIC", 1.0, 2.5,
        repairable_damage=_PLASTIC_REPAIRABLE,
        aliases=("rear bumper", "rear bumper cover", "back bumper",
                 "rear bumper assembly", "rear fascia"),
    ),
    PartDefinition(
        "BONNET", "Bonnet / hood", "FRONT", "METAL", 1.0, 2.0,
        repairable_damage=_METAL_REPAIRABLE,
        aliases=("bonnet", "hood", "engine hood", "bonnet panel", "hood panel"),
    ),
    PartDefinition(
        "GRILLE", "Front grille", "FRONT", "PLASTIC", 0.0, 1.0,
        repairable_damage=frozenset({DamageType.SCRATCH}),
        aliases=("grille", "grill", "front grille", "radiator grille"),
    ),
    PartDefinition(
        "HEADLIGHT_LEFT", "Left headlight", "FRONT", "GLASS", 0.0, 1.0,
        repairable_damage=frozenset({DamageType.SCRATCH}),
        aliases=("left headlight", "headlight left", "lh headlight", "front left headlight",
                 "left head lamp", "headlamp lh", "driver side headlight"),
    ),
    PartDefinition(
        "HEADLIGHT_RIGHT", "Right headlight", "FRONT", "GLASS", 0.0, 1.0,
        repairable_damage=frozenset({DamageType.SCRATCH}),
        aliases=("right headlight", "headlight right", "rh headlight", "front right headlight",
                 "right head lamp", "headlamp rh", "passenger side headlight"),
    ),
    PartDefinition(
        "TAILLIGHT_LEFT", "Left tail light", "REAR", "GLASS", 0.0, 0.8,
        aliases=("left tail light", "left taillight", "lh tail lamp", "rear left light"),
    ),
    PartDefinition(
        "TAILLIGHT_RIGHT", "Right tail light", "REAR", "GLASS", 0.0, 0.8,
        aliases=("right tail light", "right taillight", "rh tail lamp", "rear right light"),
    ),
    PartDefinition(
        "FENDER_LEFT", "Left front fender", "SIDE", "METAL", 1.0, 2.0,
        repairable_damage=_METAL_REPAIRABLE,
        aliases=("left fender", "lh fender", "front left fender", "left wing", "left mudguard"),
    ),
    PartDefinition(
        "FENDER_RIGHT", "Right front fender", "SIDE", "METAL", 1.0, 2.0,
        repairable_damage=_METAL_REPAIRABLE,
        aliases=("right fender", "rh fender", "front right fender", "right wing", "right mudguard"),
    ),
    PartDefinition(
        "DOOR_FRONT_LEFT", "Front left door", "SIDE", "METAL", 1.0, 2.5,
        repairable_damage=_METAL_REPAIRABLE,
        aliases=("front left door", "fl door", "lh front door", "driver door"),
    ),
    PartDefinition(
        "DOOR_FRONT_RIGHT", "Front right door", "SIDE", "METAL", 1.0, 2.5,
        repairable_damage=_METAL_REPAIRABLE,
        aliases=("front right door", "fr door", "rh front door", "passenger door"),
    ),
    PartDefinition(
        "DOOR_REAR_LEFT", "Rear left door", "SIDE", "METAL", 1.0, 2.5,
        repairable_damage=_METAL_REPAIRABLE,
        aliases=("rear left door", "rl door", "lh rear door", "back left door"),
    ),
    PartDefinition(
        "DOOR_REAR_RIGHT", "Rear right door", "SIDE", "METAL", 1.0, 2.5,
        repairable_damage=_METAL_REPAIRABLE,
        aliases=("rear right door", "rr door", "rh rear door", "back right door"),
    ),
    PartDefinition(
        "MIRROR_LEFT", "Left side mirror", "SIDE", "MIXED", 0.0, 0.7,
        aliases=("left mirror", "left side mirror", "lh wing mirror", "left door mirror"),
    ),
    PartDefinition(
        "MIRROR_RIGHT", "Right side mirror", "SIDE", "MIXED", 0.0, 0.7,
        aliases=("right mirror", "right side mirror", "rh wing mirror", "right door mirror"),
    ),
    PartDefinition(
        "QUARTER_PANEL_LEFT", "Left quarter panel", "REAR", "METAL", 1.5, 4.0, structural=True,
        repairable_damage=_METAL_REPAIRABLE,
        aliases=("left quarter panel", "lh quarter panel", "rear left panel", "left rear wing"),
    ),
    PartDefinition(
        "QUARTER_PANEL_RIGHT", "Right quarter panel", "REAR", "METAL", 1.5, 4.0, structural=True,
        repairable_damage=_METAL_REPAIRABLE,
        aliases=("right quarter panel", "rh quarter panel", "rear right panel", "right rear wing"),
    ),
    PartDefinition(
        "BOOT_LID", "Boot lid / trunk", "REAR", "METAL", 1.0, 2.0,
        repairable_damage=_METAL_REPAIRABLE,
        aliases=("boot", "boot lid", "trunk", "trunk lid", "tailgate", "rear door hatch"),
    ),
    PartDefinition(
        "ROOF", "Roof panel", "TOP", "METAL", 1.5, 4.0, structural=True,
        repairable_damage=_METAL_REPAIRABLE,
        aliases=("roof", "roof panel", "vehicle roof"),
    ),
    PartDefinition(
        "WINDSHIELD_FRONT", "Front windshield", "GLASS", "GLASS", 0.0, 1.5,
        aliases=("windshield", "windscreen", "front windshield", "front windscreen", "front glass"),
    ),
    PartDefinition(
        "WINDSHIELD_REAR", "Rear windshield", "GLASS", "GLASS", 0.0, 1.5,
        aliases=("rear windshield", "rear windscreen", "back glass", "rear glass"),
    ),
    PartDefinition(
        "WINDOW_SIDE", "Side window glass", "GLASS", "GLASS", 0.0, 1.0,
        aliases=("side window", "door glass", "window glass", "side glass"),
    ),
    PartDefinition(
        "WHEEL", "Wheel / rim", "WHEEL", "METAL", 0.0, 0.5,
        repairable_damage=frozenset({DamageType.SCRATCH}),
        aliases=("wheel", "rim", "alloy wheel", "wheel rim", "alloy rim"),
    ),
    PartDefinition(
        "TIRE", "Tire", "WHEEL", "RUBBER", 0.0, 0.4,
        aliases=("tire", "tyre", "wheel tyre"),
    ),
    PartDefinition(
        "RADIATOR", "Radiator", "FRONT", "METAL", 0.0, 2.0,
        aliases=("radiator", "radiator core", "cooling radiator"),
    ),
    PartDefinition(
        "CONDENSER", "A/C condenser", "FRONT", "METAL", 0.0, 1.8,
        aliases=("condenser", "ac condenser", "air conditioning condenser"),
    ),
    PartDefinition(
        "NUMBER_PLATE", "Number plate", "OTHER", "METAL", 0.0, 0.2,
        aliases=("number plate", "license plate", "licence plate", "registration plate"),
    ),
    PartDefinition(
        "FOG_LIGHT_LEFT", "Left fog light", "FRONT", "GLASS", 0.0, 0.6,
        aliases=("left fog light", "lh fog lamp", "front left fog light"),
    ),
    PartDefinition(
        "FOG_LIGHT_RIGHT", "Right fog light", "FRONT", "GLASS", 0.0, 0.6,
        aliases=("right fog light", "rh fog lamp", "front right fog light"),
    ),
    PartDefinition(
        "SIDE_SKIRT", "Side skirt", "SIDE", "PLASTIC", 0.5, 1.2,
        repairable_damage=_PLASTIC_REPAIRABLE,
        aliases=("side skirt", "rocker panel", "sill cover"),
    ),
    PartDefinition(
        "CHASSIS_FRAME", "Chassis / structural frame", "STRUCTURE", "METAL", 0.0, 8.0,
        structural=True,
        aliases=("chassis", "frame", "chassis frame", "structural frame", "crossmember"),
    ),
)

PARTS_BY_CODE: dict[str, PartDefinition] = {p.code: p for p in PARTS}

_ALIAS_INDEX: dict[str, str] = {}
for _part in PARTS:
    _ALIAS_INDEX[_part.display_name.lower()] = _part.code
    _ALIAS_INDEX[_part.code.lower().replace("_", " ")] = _part.code
    for _alias in _part.aliases:
        _ALIAS_INDEX[_alias] = _part.code

_NOISE = re.compile(
    r"\b(oem|genuine|original|aftermarket|used|refurbished|new|brand|for|fits|"
    r"replacement|assembly|assy|complete|set|part|auto|car)\b"
)
_NON_ALNUM = re.compile(r"[^a-z0-9\s]")
_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    lowered = _NON_ALNUM.sub(" ", text.lower())
    return _WS.sub(" ", _NOISE.sub(" ", lowered)).strip()


def normalize_part_name(raw: str) -> str | None:
    """Resolve a free-text part name to a canonical code, or ``None`` if ambiguous.

    Returning ``None`` is a legitimate, common outcome — the caller escalates to the AI
    normalisation prompt or flags the price row for manual verification. Guessing a
    canonical part here would silently attach a wrong price to a claim.
    """
    if not raw or not raw.strip():
        return None

    text = _clean(raw)
    if not text:
        return None

    if text in _ALIAS_INDEX:
        return _ALIAS_INDEX[text]

    # Longest alias contained in the string wins, so "front bumper cover" is not
    # captured by the shorter "bumper" style aliases of another part.
    best: tuple[int, str] | None = None
    for alias, code in _ALIAS_INDEX.items():
        if alias in text and (best is None or len(alias) > best[0]):
            best = (len(alias), code)

    if best is None:
        return None

    # A side-specific part must not be inferred from a name that never states a side.
    code = best[1]
    if code.endswith(("_LEFT", "_RIGHT")) and not re.search(
        r"\b(left|right|lh|rh|driver|passenger)\b", text
    ):
        return None
    return code


def part_display_name(code: str) -> str:
    part = PARTS_BY_CODE.get(code)
    return part.display_name if part else code.replace("_", " ").title()


def is_structural(code: str) -> bool:
    part = PARTS_BY_CODE.get(code)
    return bool(part and part.structural)
