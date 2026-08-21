"""Model registry.

Every model is imported here so `Base.metadata` is complete before Alembic autogenerate or
`create_all` runs. Missing an import here silently drops a table from migrations.
"""

from app.db.base import Base
from app.models.assessment import DamageAssessment, DamagedPart
from app.models.claim import Claim, ClaimLocation, ClaimNote, ClaimStatusEvent
from app.models.estimate import RepairEstimate, RepairEstimateLine
from app.models.image import (
    ClaimImage,
    CustomerDamageReport,
    ImageAnnotation,
    ImageMetadata,
)
from app.models.market import (
    MarketSource,
    PartPriceSource,
    PartPriceSummary,
    VehicleValuation,
    VehicleValuationSource,
)
from app.models.ops import AIAnalysisLog, AuditLog, FraudSignal, Notification
from app.models.user import Agent, Customer, RefreshSession, User
from app.models.vehicle import InsurancePolicy, Vehicle

__all__ = [
    "Base",
    "AIAnalysisLog",
    "Agent",
    "AuditLog",
    "Claim",
    "ClaimImage",
    "ClaimLocation",
    "ClaimNote",
    "ClaimStatusEvent",
    "Customer",
    "CustomerDamageReport",
    "DamageAssessment",
    "DamagedPart",
    "FraudSignal",
    "ImageAnnotation",
    "ImageMetadata",
    "InsurancePolicy",
    "MarketSource",
    "Notification",
    "PartPriceSource",
    "PartPriceSummary",
    "RefreshSession",
    "RepairEstimate",
    "RepairEstimateLine",
    "User",
    "Vehicle",
    "VehicleValuation",
    "VehicleValuationSource",
]
