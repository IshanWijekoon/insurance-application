"""Customer profile, vehicles and policies."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select

from app.api.deps import CurrentCustomer, CurrentUser, CustomerUser, DbSession
from app.core.errors import ConflictError, NotFoundError
from app.models.vehicle import InsurancePolicy, Vehicle
from app.schemas.auth import CustomerProfile, CustomerProfileUpdate, MeResponse, UserProfile
from app.schemas.common import MessageResponse, Page
from app.schemas.vehicle import (
    PolicyCreate,
    PolicyResponse,
    VehicleCreate,
    VehicleResponse,
    VehicleUpdate,
)
from app.services import audit

router = APIRouter(tags=["vehicles"])


@router.get("/customers/me", response_model=MeResponse)
def get_profile(user: CustomerUser, customer: CurrentCustomer):
    return MeResponse(
        user=UserProfile.model_validate(user),
        customer=CustomerProfile.model_validate(customer),
    )


@router.patch("/customers/me", response_model=MeResponse)
def update_profile(
    payload: CustomerProfileUpdate, db: DbSession, user: CustomerUser, customer: CurrentCustomer
):
    data = payload.model_dump(exclude_unset=True)
    for field in ("full_name", "phone"):
        if field in data and data[field] is not None:
            setattr(user, field, data[field])
    for field in ("national_id", "address", "city", "preferred_language"):
        if field in data and data[field] is not None:
            setattr(customer, field, data[field])

    db.flush()
    audit.record(db, action="customer.update", entity_type="customer", entity_id=customer.id, actor=user)
    return MeResponse(
        user=UserProfile.model_validate(user),
        customer=CustomerProfile.model_validate(customer),
    )


@router.get("/vehicles", response_model=Page[VehicleResponse])
def list_vehicles(
    db: DbSession,
    customer: CurrentCustomer,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    base = select(Vehicle).where(
        Vehicle.customer_id == customer.id, Vehicle.deleted_at.is_(None)
    )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    vehicles = db.scalars(
        base.order_by(Vehicle.is_primary.desc(), Vehicle.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Page[VehicleResponse](
        items=[VehicleResponse.model_validate(v) for v in vehicles],
        total=total, page=page, page_size=page_size,
    )


@router.post("/vehicles", response_model=VehicleResponse, status_code=status.HTTP_201_CREATED)
def create_vehicle(
    payload: VehicleCreate, db: DbSession, user: CustomerUser, customer: CurrentCustomer
):
    if payload.registration_number:
        duplicate = db.scalar(
            select(Vehicle).where(
                Vehicle.customer_id == customer.id,
                Vehicle.registration_number == payload.registration_number,
                Vehicle.deleted_at.is_(None),
            )
        )
        if duplicate:
            raise ConflictError("A vehicle with that registration is already in your garage.")

    vehicle = Vehicle(customer_id=customer.id, **payload.model_dump())
    db.add(vehicle)
    db.flush()

    if vehicle.is_primary:
        _demote_other_primaries(db, customer.id, vehicle.id)

    audit.record(
        db, action="vehicle.create", entity_type="vehicle", entity_id=vehicle.id,
        actor=user, after={"registration": vehicle.registration_number},
    )
    return VehicleResponse.model_validate(vehicle)


@router.get("/vehicles/{vehicle_id}", response_model=VehicleResponse)
def get_vehicle(vehicle_id: uuid.UUID, db: DbSession, customer: CurrentCustomer):
    return VehicleResponse.model_validate(_owned_vehicle(db, vehicle_id, customer.id))


@router.patch("/vehicles/{vehicle_id}", response_model=VehicleResponse)
def update_vehicle(
    vehicle_id: uuid.UUID,
    payload: VehicleUpdate,
    db: DbSession,
    user: CustomerUser,
    customer: CurrentCustomer,
):
    vehicle = _owned_vehicle(db, vehicle_id, customer.id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(vehicle, field, value)
    db.flush()

    if vehicle.is_primary:
        _demote_other_primaries(db, customer.id, vehicle.id)

    audit.record(
        db, action="vehicle.update", entity_type="vehicle", entity_id=vehicle.id, actor=user
    )
    return VehicleResponse.model_validate(vehicle)


@router.delete("/vehicles/{vehicle_id}", response_model=MessageResponse)
def delete_vehicle(
    vehicle_id: uuid.UUID, db: DbSession, user: CustomerUser, customer: CurrentCustomer
):
    from datetime import UTC, datetime

    vehicle = _owned_vehicle(db, vehicle_id, customer.id)
    # Soft delete: existing claims must keep resolving the vehicle they were filed against.
    vehicle.deleted_at = datetime.now(UTC)
    db.flush()
    audit.record(
        db, action="vehicle.delete", entity_type="vehicle", entity_id=vehicle.id, actor=user
    )
    return MessageResponse(message="Vehicle removed from your garage.")


@router.get("/policies", response_model=list[PolicyResponse])
def list_policies(db: DbSession, customer: CurrentCustomer):
    policies = db.scalars(
        select(InsurancePolicy).where(
            InsurancePolicy.customer_id == customer.id, InsurancePolicy.deleted_at.is_(None)
        )
    ).all()
    return [PolicyResponse.model_validate(p) for p in policies]


@router.post("/policies", response_model=PolicyResponse, status_code=status.HTTP_201_CREATED)
def create_policy(
    payload: PolicyCreate, db: DbSession, user: CustomerUser, customer: CurrentCustomer
):
    _owned_vehicle(db, payload.vehicle_id, customer.id)

    if db.scalar(
        select(InsurancePolicy).where(InsurancePolicy.policy_number == payload.policy_number)
    ):
        raise ConflictError("That policy number is already registered.")

    policy = InsurancePolicy(customer_id=customer.id, **payload.model_dump())
    db.add(policy)
    db.flush()
    audit.record(
        db, action="policy.create", entity_type="insurance_policy", entity_id=policy.id, actor=user
    )
    return PolicyResponse.model_validate(policy)


def _owned_vehicle(db, vehicle_id: uuid.UUID, customer_id: uuid.UUID) -> Vehicle:
    vehicle = db.scalar(
        select(Vehicle).where(
            Vehicle.id == vehicle_id,
            Vehicle.customer_id == customer_id,
            Vehicle.deleted_at.is_(None),
        )
    )
    if vehicle is None:
        raise NotFoundError("Vehicle not found.")
    return vehicle


def _demote_other_primaries(db, customer_id: uuid.UUID, keep_id: uuid.UUID) -> None:
    others = db.scalars(
        select(Vehicle).where(
            Vehicle.customer_id == customer_id,
            Vehicle.id != keep_id,
            Vehicle.is_primary.is_(True),
        )
    ).all()
    for other in others:
        other.is_primary = False
