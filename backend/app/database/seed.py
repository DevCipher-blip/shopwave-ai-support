"""Seed the database from data/crm_data.json"""
import json
import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession
from app.database.db import engine, AsyncSessionLocal
from app.database.models import Base, Customer, Order, RefundHistory
from app.config import settings


async def seed():
    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    crm_path = settings.data_dir / "crm_data.json"
    with open(crm_path) as f:
        crm_data = json.load(f)

    async with AsyncSessionLocal() as session:
        for profile in crm_data:
            # Upsert customer
            customer = Customer(
                customer_id=profile["customer_id"],
                name=profile["name"],
                email=profile["email"],
                phone=profile["phone"],
                loyalty_tier=profile["loyalty_tier"],
                account_created=profile["account_created"],
                total_orders=profile["total_orders"],
                total_spent=profile["total_spent"],
                fraud_flag=profile["fraud_flag"],
                address=profile["address"],
            )
            await session.merge(customer)

            # Orders
            for order in profile.get("orders", []):
                db_order = Order(
                    order_id=order["order_id"],
                    customer_id=profile["customer_id"],
                    date=order["date"],
                    delivered_date=order.get("delivered_date"),
                    status=order["status"],
                    total=order["total"],
                    shipping=order["shipping"],
                    is_international=order["is_international"],
                    items=order["items"],
                )
                await session.merge(db_order)

            # Refund history
            for rh in profile.get("refund_history", []):
                exists = RefundHistory(
                    customer_id=profile["customer_id"],
                    order_id=rh["order_id"],
                    date=rh["date"],
                    reason=rh["reason"],
                    amount=rh["amount"],
                    status=rh["status"],
                )
                session.add(exists)

        await session.commit()

    print(f"Seeded {len(crm_data)} customer profiles.")


if __name__ == "__main__":
    asyncio.run(seed())
