"""
Agent tools registered with LangChain's @tool decorator.

Each tool returns a JSON string so the model sees exactly what the admin
dashboard logs.
"""

import json
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from langchain_core.tools import InjectedToolArg, tool
from sqlalchemy import select

from app.agent.policy import FRAUD_LOOKBACK_DAYS, evaluate_refund, normalize_reason, parse_date
from app.database.db import AsyncSessionLocal
from app.database.models import ChatSession, Customer, Order, RefundHistory


def today() -> date:
    return date.today()


async def _load_refunds(session, customer_id: str) -> list[RefundHistory]:
    result = await session.execute(select(RefundHistory).where(RefundHistory.customer_id == customer_id))
    return list(result.scalars().all())


@tool
async def search_customer(email: str) -> str:
    """
    Look up a customer by the exact email address on their account.
    Only use an email the customer has typed in this conversation.

    Args:
        email: The customer's email address
    """
    normalized = email.strip().lower()
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Customer).where(Customer.email == normalized))
        customer = result.scalar_one_or_none()

    if not customer:
        return json.dumps({"found": False, "message": "No customer found for that email address."})

    return json.dumps(
        {
            "found": True,
            "customer_id": customer.customer_id,
            "name": customer.name,
            "loyalty_tier": customer.loyalty_tier,
        }
    )


@tool
async def get_customer_profile(customer_id: str) -> str:
    """
    Retrieve the CRM profile for a customer including loyalty tier, fraud flag
    and previous refund history. Call this before making any refund decision.

    Args:
        customer_id: The customer's unique ID (e.g. CUST-001)
    """
    async with AsyncSessionLocal() as session:
        customer = await session.get(Customer, customer_id)
        if not customer:
            return json.dumps({"found": False, "error": f"Customer {customer_id} not found"})
        refunds = await _load_refunds(session, customer_id)

    cutoff = (today() - timedelta(days=FRAUD_LOOKBACK_DAYS)).isoformat()
    recent = [r for r in refunds if r.date >= cutoff and r.status == "approved"]

    return json.dumps(
        {
            "found": True,
            "customer_id": customer.customer_id,
            "name": customer.name,
            "loyalty_tier": customer.loyalty_tier,
            "account_created": customer.account_created,
            "total_orders": customer.total_orders,
            "total_spent": customer.total_spent,
            "fraud_flag": customer.fraud_flag,
            "refund_history": [
                {"order_id": r.order_id, "date": r.date, "reason": r.reason, "amount": r.amount, "status": r.status}
                for r in refunds
            ],
            "recent_refund_count_90d": len(recent),
        }
    )


@tool
async def get_order_details(order_id: str) -> str:
    """
    Retrieve full details for a specific order including items, delivery date,
    and whether items are digital or final sale.

    Args:
        order_id: The order ID (e.g. ORD-10021)
    """
    order_id = order_id.strip().upper()
    async with AsyncSessionLocal() as session:
        order = await session.get(Order, order_id)
        if not order:
            return json.dumps({"found": False, "error": f"Order {order_id} not found"})

    delivered = parse_date(order.delivered_date)
    days_since_delivery = (today() - delivered).days if delivered else -1

    return json.dumps(
        {
            "found": True,
            "order_id": order.order_id,
            "customer_id": order.customer_id,
            "order_date": order.date,
            "delivered_date": order.delivered_date,
            "days_since_delivery": days_since_delivery,
            "status": order.status,
            "total": order.total,
            "shipping": order.shipping,
            "is_international": order.is_international,
            "items": order.items,
        }
    )


async def _evaluate(order_id: str, customer_id: str, reason_code: str):
    async with AsyncSessionLocal() as session:
        order = await session.get(Order, order_id.strip().upper())
        customer = await session.get(Customer, customer_id.strip().upper())
        refunds = await _load_refunds(session, customer.customer_id) if customer else []
    return order, customer, evaluate_refund(order, customer, refunds, reason_code, today())


@tool
async def check_refund_eligibility(order_id: str, customer_id: str, reason_code: str) -> str:
    """
    The core policy engine. Validates whether a refund is eligible based on
    the ShopWave refund policy. MUST be called before making any refund decision.

    Args:
        order_id: The order being refunded
        customer_id: The customer requesting the refund
        reason_code: One of: WRONG_ITEM, DAMAGED_ARRIVAL, DEFECTIVE, CHANGE_OF_MIND,
                     NOT_AS_DESCRIBED, MISSING_PARTS, SUBSCRIPTION_CANCEL
    """
    _, _, result = await _evaluate(order_id, customer_id, reason_code)
    return json.dumps(result.to_dict())


@tool
async def check_fraud_risk(customer_id: str) -> str:
    """
    Performs a fraud risk assessment for a customer by analyzing their
    refund history patterns.

    Args:
        customer_id: The customer's unique ID
    """
    async with AsyncSessionLocal() as session:
        customer = await session.get(Customer, customer_id)
        if not customer:
            return json.dumps({"error": "Customer not found"})
        refunds = await _load_refunds(session, customer_id)

    cutoff = (today() - timedelta(days=FRAUD_LOOKBACK_DAYS)).isoformat()
    recent = [r for r in refunds if r.date >= cutoff]
    total_refunded_90d = round(sum(r.amount or 0 for r in recent if r.status == "approved"), 2)

    risk_score = 0
    flags = []
    if customer.fraud_flag:
        risk_score += 100
        flags.append("Account has a pre-existing fraud flag")
    if len(recent) >= 3:
        risk_score += 60
        flags.append(f"{len(recent)} refunds in last 90 days")
    if total_refunded_90d > 300:
        risk_score += 30
        flags.append(f"${total_refunded_90d:.2f} refunded in last 90 days")

    risk_level = "HIGH" if risk_score >= 80 else "MEDIUM" if risk_score >= 40 else "LOW"

    return json.dumps(
        {
            "customer_id": customer_id,
            "risk_level": risk_level,
            "risk_score": risk_score,
            "flags": flags,
            "recent_refund_count": len(recent),
            "total_refunded_90d": total_refunded_90d,
        }
    )


@tool
async def process_refund_decision(
    session_id: Annotated[str, InjectedToolArg],
    order_id: str,
    customer_id: str,
    decision: str,
    reason_code: str,
    reason: str,
) -> str:
    """
    Finalizes and records the refund decision. This MUST be the last tool call
    before responding to the customer. The refund amount is set by the policy
    engine; an "approve" the policy does not allow is recorded as the policy
    outcome instead.

    Args:
        order_id: The order being acted on
        customer_id: The customer ID
        decision: One of: approve | deny | escalate
        reason_code: The reason code passed to check_refund_eligibility
        reason: The policy-based reason for this decision
    """
    requested = decision.strip().lower()
    if requested not in {"approve", "deny", "escalate"}:
        return json.dumps(
            {
                "success": False,
                "error": f"Invalid decision '{decision}'. Must be: approve | deny | escalate",
            }
        )

    order, customer, policy = await _evaluate(order_id, customer_id, reason_code)

    final = requested
    if requested == "approve" and policy.decision != "approve":
        final = policy.decision
    refund_amount = policy.refund_amount if final == "approve" else None
    final_reason = reason if final == requested else policy.reason

    async with AsyncSessionLocal() as db:
        chat_session = await db.get(ChatSession, session_id)
        if chat_session:
            chat_session.outcome = final
            chat_session.refund_amount = refund_amount
            chat_session.ended_at = datetime.now(UTC)
            chat_session.customer_id = customer.customer_id if customer else None

        if final == "approve":
            db.add(
                RefundHistory(
                    customer_id=customer.customer_id,
                    order_id=order.order_id,
                    date=today().isoformat(),
                    reason=normalize_reason(reason_code),
                    amount=refund_amount,
                    status="approved",
                )
            )
        await db.commit()

    result = {
        "success": True,
        "decision": final,
        "requested_decision": requested,
        "policy_override": final != requested,
        "order_id": order.order_id if order else order_id,
        "customer_id": customer.customer_id if customer else customer_id,
        "policy_section": policy.policy_section,
    }
    if final == "approve":
        result["refund_amount"] = refund_amount
        result["message"] = f"Refund of ${refund_amount:.2f} approved and recorded."
        result["processing_time"] = "5–7 business days"
    elif final == "deny":
        result["message"] = f"Refund denied. Reason: {final_reason}"
    else:
        result["message"] = f"Case escalated to human agent. Reason: {final_reason}"
        result["escalation_ticket"] = f"ESC-{result['order_id']}-{today().strftime('%Y%m%d')}"

    return json.dumps(result)


ALL_TOOLS = [
    search_customer,
    get_customer_profile,
    get_order_details,
    check_refund_eligibility,
    check_fraud_risk,
    process_refund_decision,
]
