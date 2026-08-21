"""Idempotent development seed: staff accounts, a sample garage, and market-source whitelist."""

from __future__ import annotations

from sqlalchemy import select

from app.core.enums import MarketSourceCategory, MarketSourceType, PolicyStatus, UserRole
from app.core.security import hash_password
from app.db.session import session_scope
from app.models.market import MarketSource
from app.models.user import Agent, Customer, User
from app.models.vehicle import InsurancePolicy, Vehicle

DEMO_PASSWORD = "ChangeMe123!"

STAFF = [
    {
        "email": "admin@insure.local",
        "full_name": "Platform Admin",
        "role": UserRole.ADMIN,
    },
    {
        "email": "agent@insure.local",
        "full_name": "Nimal Perera",
        "role": UserRole.AGENT,
        "employee_code": "AG-0001",
        "branch": "Colombo",
        "region": "Western",
    },
]

CUSTOMER = {
    "email": "customer@insure.local",
    "full_name": "Ayesha Fernando",
    "phone": "+94771234567",
}

SOURCES = [
    {
        "name": "ikman.lk",
        "base_url": "https://ikman.lk",
        "category": MarketSourceCategory.VEHICLE_VALUE,
        "reliability_weight": 0.75,
        "notes": "Sri Lanka classifieds — vehicle listings. Respect robots.txt.",
    },
    {
        "name": "riyasewana.com",
        "base_url": "https://riyasewana.com",
        "category": MarketSourceCategory.VEHICLE_VALUE,
        "reliability_weight": 0.7,
        "notes": "Sri Lanka vehicle marketplace.",
    },
    {
        "name": "patpat.lk",
        "base_url": "https://www.patpat.lk",
        "category": MarketSourceCategory.BOTH,
        "reliability_weight": 0.65,
        "notes": "General marketplace; may list vehicles and spare parts.",
    },
    {
        "name": "autolanka.lk",
        "base_url": "https://autolanka.lk",
        "category": MarketSourceCategory.PART_PRICE,
        "reliability_weight": 0.6,
        "notes": "Spare-parts listings. Enable only if robots.txt permits the paths used.",
    },
]


def seed() -> None:
    with session_scope() as db:
        for row in STAFF:
            existing = db.scalar(select(User).where(User.email == row["email"]))
            if existing:
                continue
            user = User(
                email=row["email"],
                password_hash=hash_password(DEMO_PASSWORD),
                full_name=row["full_name"],
                role=row["role"],
            )
            db.add(user)
            db.flush()
            if row["role"] is UserRole.AGENT:
                db.add(
                    Agent(
                        user_id=user.id,
                        employee_code=row["employee_code"],
                        branch=row["branch"],
                        region=row["region"],
                    )
                )

        customer_user = db.scalar(select(User).where(User.email == CUSTOMER["email"]))
        if customer_user is None:
            customer_user = User(
                email=CUSTOMER["email"],
                password_hash=hash_password(DEMO_PASSWORD),
                full_name=CUSTOMER["full_name"],
                phone=CUSTOMER["phone"],
                role=UserRole.CUSTOMER,
            )
            db.add(customer_user)
            db.flush()
            customer = Customer(user_id=customer_user.id, city="Colombo", country="LK")
            db.add(customer)
            db.flush()
        else:
            customer = db.scalar(select(Customer).where(Customer.user_id == customer_user.id))

        if customer is not None:
            vehicle = db.scalar(
                select(Vehicle).where(
                    Vehicle.customer_id == customer.id,
                    Vehicle.registration_number == "WP ABC-1234",
                )
            )
            if vehicle is None:
                vehicle = Vehicle(
                    customer_id=customer.id,
                    registration_number="WP ABC-1234",
                    make="Toyota",
                    model="Prius",
                    variant="S",
                    year=2018,
                    vehicle_type="HATCHBACK",
                    color="Silver",
                    is_primary=True,
                )
                db.add(vehicle)
                db.flush()
                db.add(
                    InsurancePolicy(
                        vehicle_id=vehicle.id,
                        customer_id=customer.id,
                        policy_number="POL-2018-000441",
                        insurer_name="Demo Motor Insurance",
                        policy_type="Comprehensive",
                        coverage_amount=8_000_000,
                        deductible=50_000,
                        currency="LKR",
                        status=PolicyStatus.ACTIVE,
                    )
                )

        for source in SOURCES:
            existing = db.scalar(select(MarketSource).where(MarketSource.name == source["name"]))
            if existing:
                continue
            db.add(
                MarketSource(
                    name=source["name"],
                    base_url=source["base_url"],
                    source_type=MarketSourceType.SCRAPE,
                    category=source["category"],
                    country="LK",
                    currency="LKR",
                    reliability_weight=source["reliability_weight"],
                    is_enabled=True,
                    notes=source["notes"],
                )
            )

    print("Seed complete.")
    print(f"  Admin:    admin@insure.local / {DEMO_PASSWORD}")
    print(f"  Agent:    agent@insure.local / {DEMO_PASSWORD}")
    print(f"  Customer: customer@insure.local / {DEMO_PASSWORD}")


if __name__ == "__main__":
    seed()
