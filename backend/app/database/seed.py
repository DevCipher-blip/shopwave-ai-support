"""Seed the database from data/crm_data.json"""

import asyncio
import json
from datetime import date, timedelta

from sqlalchemy import func, select

from app.config import settings
from app.database.db import AsyncSessionLocal, engine
from app.database.models import Base, Customer, Order, RefundHistory

# Dates in crm_data.json describe the store as of this day. Seeding moves
# every date forward by the same offset so the demo scenarios (inside the
# 30-day window, 72-hour damage reports, 3 refunds in 90 days) keep their
# meaning however long after this date the app is started.
DATA_AS_OF = date(2026, 6, 19)


def _shift(value: str | None, offset: timedelta) -> str | None:
    if not value:
        return value
    return (date.fromisoformat(value) + offset).isoformat()


async def seed(today: date | None = None) -> int:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        existing = (await session.execute(select(func.count(Customer.customer_id)))).scalar()
        if existing:
            return 0

        offset = timedelta(0)
        if settings.rebase_demo_dates:
            offset = (today or date.today()) - DATA_AS_OF

        crm_text = await asyncio.to_thread((settings.data_dir / "crm_data.json").read_text)
        crm_data = json.loads(crm_text)

        for profile in crm_data:
            session.add(
                Customer(
                    customer_id=profile["customer_id"],
                    name=profile["name"],
                    email=profile["email"].lower(),
                    phone=profile["phone"],
                    loyalty_tier=profile["loyalty_tier"],
                    account_created=_shift(profile["account_created"], offset),
                    total_orders=profile["total_orders"],
                    total_spent=profile["total_spent"],
                    fraud_flag=profile["fraud_flag"],
                    address=profile["address"],
                )
            )
            for order in profile.get("orders", []):
                session.add(
                    Order(
                        order_id=order["order_id"],
                        customer_id=profile["customer_id"],
                        date=_shift(order["date"], offset),
                        delivered_date=_shift(order.get("delivered_date"), offset),
                        status=order["status"],
                        total=order["total"],
                        shipping=order["shipping"],
                        is_international=order["is_international"],
                        items=order["items"],
                    )
                )
            for refund in profile.get("refund_history", []):
                session.add(
                    RefundHistory(
                        customer_id=profile["customer_id"],
                        order_id=refund["order_id"],
                        date=_shift(refund["date"], offset),
                        reason=refund["reason"],
                        amount=refund["amount"],
                        status=refund["status"],
                    )
                )

        await session.commit()

    return len(crm_data)


if __name__ == "__main__":
    print(f"Seeded {asyncio.run(seed())} customer profiles.")
