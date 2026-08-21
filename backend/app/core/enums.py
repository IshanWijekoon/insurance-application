"""Domain enumerations shared by models, schemas and the AI output contracts."""

from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    CUSTOMER = "CUSTOMER"
    AGENT = "AGENT"
    ADMIN = "ADMIN"


class ActorType(StrEnum):
    CUSTOMER = "CUSTOMER"
    AGENT = "AGENT"
    ADMIN = "ADMIN"
    SYSTEM = "SYSTEM"


class ClaimStatus(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PROCESSING = "PROCESSING"
    AI_ANALYZING = "AI_ANALYZING"
    MARKET_RESEARCH = "MARKET_RESEARCH"
    ESTIMATING = "ESTIMATING"
    AI_COMPLETED = "AI_COMPLETED"
    AGENT_REVIEW = "AGENT_REVIEW"
    MORE_INFORMATION_REQUIRED = "MORE_INFORMATION_REQUIRED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SETTLEMENT_PROCESSING = "SETTLEMENT_PROCESSING"
    COMPLETED = "COMPLETED"

    @property
    def is_terminal(self) -> bool:
        return self in {ClaimStatus.REJECTED, ClaimStatus.COMPLETED}

    @property
    def is_pipeline_stage(self) -> bool:
        return self in {
            ClaimStatus.PROCESSING,
            ClaimStatus.AI_ANALYZING,
            ClaimStatus.MARKET_RESEARCH,
            ClaimStatus.ESTIMATING,
        }


class ClaimPriority(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"


class ImageRole(StrEnum):
    FRONT = "FRONT"
    REAR = "REAR"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    DAMAGE_CLOSEUP = "DAMAGE_CLOSEUP"
    NUMBER_PLATE = "NUMBER_PLATE"
    INTERIOR = "INTERIOR"
    OTHER = "OTHER"


class ImageValidationStatus(StrEnum):
    PENDING = "PENDING"
    VALID = "VALID"
    WARNING = "WARNING"
    REJECTED = "REJECTED"


class AnnotationType(StrEnum):
    RECTANGLE = "RECTANGLE"
    POLYGON = "POLYGON"
    CIRCLE = "CIRCLE"
    FREEHAND = "FREEHAND"
    TEXT = "TEXT"


class DamageType(StrEnum):
    SCRATCH = "SCRATCH"
    DENT = "DENT"
    CRACK = "CRACK"
    BROKEN = "BROKEN"
    MISSING = "MISSING"
    DEFORMATION = "DEFORMATION"
    PAINT_DAMAGE = "PAINT_DAMAGE"
    GLASS_DAMAGE = "GLASS_DAMAGE"
    POSSIBLE_STRUCTURAL = "POSSIBLE_STRUCTURAL"
    UNKNOWN = "UNKNOWN"


class DamageSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    @property
    def rank(self) -> int:
        return {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}[self.value]


class RepairAction(StrEnum):
    REPAIR = "REPAIR"
    REPLACE = "REPLACE"
    INSPECT = "INSPECT"


class PartGrade(StrEnum):
    OEM = "OEM"
    AFTERMARKET = "AFTERMARKET"
    USED = "USED"
    REFURBISHED = "REFURBISHED"
    UNKNOWN = "UNKNOWN"


class DataStatus(StrEnum):
    """Whether a researched economic value could actually be obtained."""

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class LocationSource(StrEnum):
    EXIF_GPS = "EXIF_GPS"
    DEVICE_GPS = "DEVICE_GPS"
    CUSTOMER_SELECTED = "CUSTOMER_SELECTED"
    GEOCODED_FROM_TEXT = "GEOCODED_FROM_TEXT"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class MarketSourceType(StrEnum):
    API = "API"
    SCRAPE = "SCRAPE"
    DATASET = "DATASET"


class MarketSourceCategory(StrEnum):
    VEHICLE_VALUE = "VEHICLE_VALUE"
    PART_PRICE = "PART_PRICE"
    BOTH = "BOTH"


class NotificationChannel(StrEnum):
    IN_APP = "IN_APP"
    WEBSOCKET = "WEBSOCKET"
    EMAIL = "EMAIL"
    SMS = "SMS"
    PUSH = "PUSH"


class DeliveryStatus(StrEnum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    RETRYING = "RETRYING"


class AIStage(StrEnum):
    CUSTOMER_INPUT_EXTRACTION = "CUSTOMER_INPUT_EXTRACTION"
    VEHICLE_IDENTIFICATION = "VEHICLE_IDENTIFICATION"
    PLATE_OCR = "PLATE_OCR"
    DAMAGE_DETECTION = "DAMAGE_DETECTION"
    PART_NORMALIZATION = "PART_NORMALIZATION"
    MARKET_INTERPRETATION = "MARKET_INTERPRETATION"
    ESTIMATE_REASONING = "ESTIMATE_REASONING"
    CLAIM_SUMMARY = "CLAIM_SUMMARY"


class AICallStatus(StrEnum):
    SUCCESS = "SUCCESS"
    SCHEMA_ERROR = "SCHEMA_ERROR"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    SKIPPED = "SKIPPED"


class NoteVisibility(StrEnum):
    INTERNAL = "INTERNAL"
    CUSTOMER_VISIBLE = "CUSTOMER_VISIBLE"


class PolicyStatus(StrEnum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    SUSPENDED = "SUSPENDED"
