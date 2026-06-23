"""
Agent tools — each tool is a pure async function that reads from the DB.
Tools are registered with @tool decorator for LangChain/LangGraph.
"""
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool
from sqlalchemy import select, func

from app.config import settings
from app.database.db import AsyncSessionLocal
from app.database.models import Customer, Order, RefundHistory


def _days_between(date_str: str) -> int:
    """Return days between a date string (YYYY-MM-DD) and today."""
    try:
        d = date.fromisoformat(date_str)
        return (date.today() - d).days
    except Exception:
        return -1


@tool
async def search_customer(query: str) -> str:
    """
    Search for a customer by name or email address.
    Returns a list of matching customers with their basic profile.
    Use this when the customer hasn't provided their customer ID.

    Args:
        query: Customer's name or email address
    """
    query_lower = query.lower().strip()
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Customer))
        customers = result.scalars().all()

    matches = []
    for c in customers:
        if query_lower in c.email.lower() or query_lower in c.name.lower():
            matches.append({
                "customer_id": c.customer_id,
                "name": c.name,
                "email": c.email,
                "loyalty_tier": c.loyalty_tier,
            })

    if not matches:
        return json.dumps({"found": False, "message": f"No customer found matching '{query}'"})

    return json.dumps({"found": True, "matches": matches})


@tool
async def get_customer_profile(customer_id: str) -> str:
    """
    Retrieve the full CRM profile for a customer including their order history
    and previous refund history. Always call this before making any refund decision.

    Args:
        customer_id: The customer's unique ID (e.g. CUST-001)
    """
    async with AsyncSessionLocal() as session:
        customer = await session.get(Customer, customer_id)
        if not customer:
            return json.dumps({"found": False, "error": f"Customer {customer_id} not found"})

        refund_result = await session.execute(
            select(RefundHistory).where(RefundHistory.customer_id == customer_id)
        )
        refund_history = refund_result.scalars().all()

        # Count refunds in last 90 days
        ninety_days_ago = (date.today() - timedelta(days=90)).isoformat()
        recent_refunds = [
            r for r in refund_history
            if r.date >= ninety_days_ago and r.status == "approved"
        ]

    return json.dumps({
        "found": True,
        "customer_id": customer.customer_id,
        "name": customer.name,
        "email": customer.email,
        "phone": customer.phone,
        "loyalty_tier": customer.loyalty_tier,
        "account_created": customer.account_created,
        "total_orders": customer.total_orders,
        "total_spent": customer.total_spent,
        "fraud_flag": customer.fraud_flag,
        "address": customer.address,
        "refund_history": [
            {
                "order_id": r.order_id,
                "date": r.date,
                "reason": r.reason,
                "amount": r.amount,
                "status": r.status
            }
            for r in refund_history
        ],
        "recent_refund_count_90d": len(recent_refunds),
    })


@tool
async def get_order_details(order_id: str) -> str:
    """
    Retrieve full details for a specific order including items, delivery date,
    and whether items are digital or final sale.

    Args:
        order_id: The order ID (e.g. ORD-10021)
    """
    async with AsyncSessionLocal() as session:
        order = await session.get(Order, order_id)
        if not order:
            return json.dumps({"found": False, "error": f"Order {order_id} not found"})

    days_since_delivery = _days_between(order.delivered_date) if order.delivered_date else -1

    return json.dumps({
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
    })


@tool
async def check_refund_eligibility(
    order_id: str,
    customer_id: str,
    reason_code: str,
) -> str:
    """
    The core policy engine. Validates whether a refund is eligible based on
    the ShopWave refund policy. MUST be called before making any refund decision.

    Args:
        order_id: The order being refunded
        customer_id: The customer requesting the refund
        reason_code: One of: WRONG_ITEM, DAMAGED_ARRIVAL, DEFECTIVE, CHANGE_OF_MIND,
                     NOT_AS_DESCRIBED, MISSING_PARTS, SUBSCRIPTION_CANCEL
    """
    async with AsyncSessionLocal() as session:
        order = await session.get(Order, order_id)
        customer = await session.get(Customer, customer_id)

        if not order or not customer:
            return json.dumps({
                "eligible": False,
                "decision_type": "deny",
                "denial_reason": "Order or customer not found in system."
            })

        # Load refund history for fraud check
        refund_result = await session.execute(
            select(RefundHistory).where(RefundHistory.customer_id == customer_id)
        )
        refund_history = refund_result.scalars().all()

    days_since_delivery = _days_between(order.delivered_date) if order.delivered_date else 999
    is_international = order.is_international
    return_window = 14 if is_international else 30
    items = order.items or []

    # ── RULE: Fraud flag ──────────────────────────────────────────────────────
    if customer.fraud_flag:
        return json.dumps({
            "eligible": False,
            "decision_type": "deny",
            "denial_reason": "Account has an active fraud flag. Refund cannot be processed.",
            "policy_section": "Section 7"
        })

    # ── RULE: 3+ refunds in 90 days ───────────────────────────────────────────
    ninety_days_ago = (date.today() - timedelta(days=90)).isoformat()
    recent_refunds = [r for r in refund_history if r.date >= ninety_days_ago and r.status == "approved"]
    if len(recent_refunds) >= 3:
        return json.dumps({
            "eligible": False,
            "decision_type": "escalate",
            "denial_reason": f"Customer has {len(recent_refunds)} approved refunds in the last 90 days. Fraud prevention escalation required.",
            "policy_section": "Section 7"
        })

    # ── RULE: Digital products ────────────────────────────────────────────────
    has_digital = any(item.get("is_digital", False) for item in items)
    if has_digital:
        return json.dumps({
            "eligible": False,
            "decision_type": "deny",
            "denial_reason": "Digital products and software licenses are non-refundable under all circumstances.",
            "policy_section": "Section 3.1"
        })

    # ── RULE: Final sale items ────────────────────────────────────────────────
    has_final_sale = any(item.get("is_final_sale", False) for item in items)
    if has_final_sale:
        return json.dumps({
            "eligible": False,
            "decision_type": "deny",
            "denial_reason": "Items marked as Final Sale are not eligible for returns or refunds.",
            "policy_section": "Section 3.2"
        })

    # ── RULE: High-value order escalation ────────────────────────────────────
    if order.total > 500:
        return json.dumps({
            "eligible": None,
            "decision_type": "escalate",
            "escalation_reason": f"Order total ${order.total:.2f} exceeds $500 threshold. Human agent review required.",
            "policy_section": "Section 8"
        })

    # ── RULE: Return window check ─────────────────────────────────────────────
    if days_since_delivery > return_window:
        # VIP exception?
        if customer.loyalty_tier in ("Gold", "Platinum"):
            if days_since_delivery <= return_window + 15:
                return json.dumps({
                    "eligible": None,
                    "decision_type": "escalate",
                    "escalation_reason": (
                        f"VIP customer ({customer.loyalty_tier}) is {days_since_delivery - return_window} days "
                        f"past the {return_window}-day window. Eligible for VIP exception review — "
                        "escalate to human agent for store credit consideration."
                    ),
                    "policy_section": "Section 6a"
                })
        return json.dumps({
            "eligible": False,
            "decision_type": "deny",
            "denial_reason": (
                f"Return window expired. Item was delivered {days_since_delivery} days ago. "
                f"{'International' if is_international else 'Domestic'} orders must be returned within {return_window} days."
            ),
            "policy_section": "Section 1"
        })

    # ── RULE: Reason-specific checks ──────────────────────────────────────────
    if reason_code == "DAMAGED_ARRIVAL":
        if days_since_delivery > 3:
            return json.dumps({
                "eligible": False,
                "decision_type": "deny",
                "denial_reason": f"Damaged arrival must be reported within 72 hours of delivery. This was reported {days_since_delivery} days after delivery.",
                "policy_section": "Section 2"
            })
        refund_amount = order.total
        return json.dumps({
            "eligible": True,
            "decision_type": "approve",
            "refund_amount": refund_amount,
            "refund_type": "full",
            "note": "Full refund approved. No return required if photo evidence provided.",
            "policy_section": "Section 2"
        })

    elif reason_code == "DEFECTIVE":
        days_since_order = _days_between(order.date)
        if days_since_order > 90:
            return json.dumps({
                "eligible": False,
                "decision_type": "deny",
                "denial_reason": f"Defect reported {days_since_order} days after purchase. 90-day warranty window has expired.",
                "policy_section": "Section 2"
            })
        return json.dumps({
            "eligible": True,
            "decision_type": "approve",
            "refund_amount": order.total,
            "refund_type": "full_or_replacement",
            "policy_section": "Section 2"
        })

    elif reason_code == "WRONG_ITEM":
        return json.dumps({
            "eligible": True,
            "decision_type": "approve",
            "refund_amount": order.total,
            "refund_type": "full",
            "note": "Free return label will be issued. No return required for orders under $50.",
            "policy_section": "Section 2"
        })

    elif reason_code == "NOT_AS_DESCRIBED":
        return json.dumps({
            "eligible": True,
            "decision_type": "approve",
            "refund_amount": order.total,
            "refund_type": "full",
            "note": "Free return label will be issued.",
            "policy_section": "Section 2"
        })

    elif reason_code == "MISSING_PARTS":
        return json.dumps({
            "eligible": True,
            "decision_type": "approve",
            "refund_amount": order.total,
            "refund_type": "full_or_parts_sent",
            "policy_section": "Section 2"
        })

    elif reason_code == "CHANGE_OF_MIND":
        restocking_fee = round(order.total * 0.15, 2)
        refund_amount = round(order.total - restocking_fee, 2)
        return json.dumps({
            "eligible": True,
            "decision_type": "approve",
            "refund_amount": refund_amount,
            "refund_type": "partial",
            "restocking_fee": restocking_fee,
            "note": f"15% restocking fee of ${restocking_fee:.2f} applies. Refund: ${refund_amount:.2f}.",
            "policy_section": "Section 2"
        })

    elif reason_code == "SUBSCRIPTION_CANCEL":
        days_since_charge = _days_between(order.date)
        if days_since_charge <= 1:
            return json.dumps({
                "eligible": True,
                "decision_type": "approve",
                "refund_amount": order.total,
                "refund_type": "full",
                "note": "Cancelled within 24 hours. Full refund approved.",
                "policy_section": "Section 5"
            })
        return json.dumps({
            "eligible": False,
            "decision_type": "deny",
            "denial_reason": "Subscription was not cancelled within the 24-hour window. Current billing period is non-refundable. Subscription will not auto-renew.",
            "policy_section": "Section 5"
        })

    else:
        return json.dumps({
            "eligible": False,
            "decision_type": "deny",
            "denial_reason": f"Unknown reason code '{reason_code}'. Please clarify the issue."
        })


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

        refund_result = await session.execute(
            select(RefundHistory).where(RefundHistory.customer_id == customer_id)
        )
        refund_history = refund_result.scalars().all()

    ninety_days_ago = (date.today() - timedelta(days=90)).isoformat()
    recent = [r for r in refund_history if r.date >= ninety_days_ago]
    total_refunded_90d = sum(r.amount or 0 for r in recent if r.status == "approved")

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

    return json.dumps({
        "customer_id": customer_id,
        "risk_level": risk_level,
        "risk_score": risk_score,
        "flags": flags,
        "recent_refund_count": len(recent),
        "total_refunded_90d": total_refunded_90d,
    })


@tool
async def process_refund_decision(
    session_id: str,
    order_id: str,
    customer_id: str,
    decision: str,
    refund_amount: Optional[float],
    reason: str,
) -> str:
    """
    Finalizes and records the refund decision. This MUST be the last tool call
    before responding to the customer. It persists the outcome to the database.

    Args:
        session_id: The current chat session ID
        order_id: The order being acted on
        customer_id: The customer ID
        decision: One of: approve | deny | escalate
        refund_amount: The approved refund amount (or null if denied/escalated)
        reason: The policy-based reason for this decision
    """
    from app.database.models import ChatSession, RefundHistory
    from datetime import datetime, timezone

    valid_decisions = {"approve", "deny", "escalate"}
    if decision not in valid_decisions:
        return json.dumps({"success": False, "error": f"Invalid decision '{decision}'. Must be: approve | deny | escalate"})

    async with AsyncSessionLocal() as db_session:
        # Update or create chat session outcome
        chat_session = await db_session.get(ChatSession, session_id)
        if chat_session:
            chat_session.outcome = decision
            chat_session.refund_amount = refund_amount
            chat_session.ended_at = datetime.now(timezone.utc)
            chat_session.customer_id = customer_id

        # If approved, record in refund history
        if decision == "approve" and refund_amount:
            new_refund = RefundHistory(
                customer_id=customer_id,
                order_id=order_id,
                date=date.today().isoformat(),
                reason=reason,
                amount=refund_amount,
                status="approved",
            )
            db_session.add(new_refund)

        await db_session.commit()

    result = {
        "success": True,
        "decision": decision,
        "order_id": order_id,
        "customer_id": customer_id,
    }

    if decision == "approve":
        result["refund_amount"] = refund_amount
        result["message"] = f"Refund of ${refund_amount:.2f} approved and recorded."
        result["processing_time"] = "5–7 business days"
    elif decision == "deny":
        result["message"] = f"Refund denied. Reason: {reason}"
    elif decision == "escalate":
        result["message"] = f"Case escalated to human agent. Reason: {reason}"
        result["escalation_ticket"] = f"ESC-{order_id}-{date.today().strftime('%Y%m%d')}"

    return json.dumps(result)


# All tools exported for graph registration
ALL_TOOLS = [
    search_customer,
    get_customer_profile,
    get_order_details,
    check_refund_eligibility,
    check_fraud_risk,
    process_refund_decision,
]
