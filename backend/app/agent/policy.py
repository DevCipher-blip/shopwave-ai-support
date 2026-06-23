"""
Refund policy engine (data/refund_policy.md) as a pure function.

The LLM never decides eligibility or amounts on its own: both
check_refund_eligibility and process_refund_decision call evaluate_refund,
so a prompt that talks the model into "approving" something cannot get past
these rules.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any, Literal, Protocol

Decision = Literal["approve", "deny", "escalate"]

REASON_CODES = frozenset(
    {
        "WRONG_ITEM",
        "DAMAGED_ARRIVAL",
        "DEFECTIVE",
        "CHANGE_OF_MIND",
        "NOT_AS_DESCRIBED",
        "MISSING_PARTS",
        "SUBSCRIPTION_CANCEL",
    }
)

DOMESTIC_WINDOW_DAYS = 30
INTERNATIONAL_WINDOW_DAYS = 14
VIP_GRACE_DAYS = 15
VIP_TIERS = ("Gold", "Platinum")
DAMAGE_REPORT_DAYS = 3
WARRANTY_DAYS = 90
SUBSCRIPTION_CANCEL_DAYS = 1
HIGH_VALUE_THRESHOLD = 500.0
RESTOCKING_FEE_RATE = 0.15
FRAUD_LOOKBACK_DAYS = 90
FRAUD_REFUND_COUNT = 3


class OrderLike(Protocol):
    order_id: str
    customer_id: str
    date: str
    delivered_date: str | None
    total: float
    is_international: bool
    items: list[dict] | None


class CustomerLike(Protocol):
    customer_id: str
    loyalty_tier: str | None
    fraud_flag: bool


class RefundLike(Protocol):
    order_id: str
    date: str
    status: str | None


@dataclass(frozen=True)
class PolicyResult:
    decision: Decision
    reason: str
    policy_section: str | None = None
    refund_amount: float | None = None
    refund_type: str | None = None
    restocking_fee: float | None = None
    note: str | None = None

    @property
    def eligible(self) -> bool | None:
        return {"approve": True, "deny": False, "escalate": None}[self.decision]

    def to_dict(self) -> dict[str, Any]:
        body = {k: v for k, v in asdict(self).items() if v is not None}
        body.pop("decision")
        reason_key = {"approve": "reason", "deny": "denial_reason", "escalate": "escalation_reason"}
        body[reason_key[self.decision]] = body.pop("reason")
        return {"eligible": self.eligible, "decision_type": self.decision, **body}


def _deny(reason: str, section: str | None = None) -> PolicyResult:
    return PolicyResult("deny", reason, section)


def _escalate(reason: str, section: str | None = None) -> PolicyResult:
    return PolicyResult("escalate", reason, section)


def _approve(amount: float, refund_type: str, reason: str, **extra: Any) -> PolicyResult:
    return PolicyResult("approve", reason, "Section 2", round(amount, 2), refund_type, **extra)


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def normalize_reason(reason_code: str | None) -> str:
    return (reason_code or "").strip().upper().replace(" ", "_").replace("-", "_")


def evaluate_refund(
    order: OrderLike | None,
    customer: CustomerLike | None,
    refunds: Sequence[RefundLike],
    reason_code: str | None,
    today: date,
) -> PolicyResult:
    if order is None:
        return _deny("Order not found in system.")
    if customer is None:
        return _deny("Customer not found in system.")
    if order.customer_id != customer.customer_id:
        return _deny("This order does not belong to the customer on this request.")

    reason = normalize_reason(reason_code)
    if reason not in REASON_CODES:
        return _deny(f"Unknown reason code '{reason_code}'. Please clarify the issue.")

    if customer.fraud_flag:
        return _deny("Account has an active fraud flag. Refund cannot be processed.", "Section 7")

    if any(r.order_id == order.order_id and r.status == "approved" for r in refunds):
        return _deny(f"Order {order.order_id} has already been refunded.", "Section 7")

    cutoff = today - timedelta(days=FRAUD_LOOKBACK_DAYS)
    recent = [r for r in refunds if r.status == "approved" and (parse_date(r.date) or date.min) >= cutoff]
    if len(recent) >= FRAUD_REFUND_COUNT:
        return _escalate(
            f"Customer has {len(recent)} approved refunds in the last {FRAUD_LOOKBACK_DAYS} days. "
            "Fraud prevention escalation required.",
            "Section 7",
        )

    items = order.items or []
    if any(item.get("is_digital") for item in items):
        return _deny(
            "Digital products and software licenses are non-refundable under all circumstances.",
            "Section 3.1",
        )
    if any(item.get("is_final_sale") for item in items):
        return _deny("Items marked as Final Sale are not eligible for returns or refunds.", "Section 3.2")

    if order.total > HIGH_VALUE_THRESHOLD:
        return _escalate(
            f"Order total ${order.total:.2f} exceeds ${HIGH_VALUE_THRESHOLD:.0f} threshold. "
            "Human agent review required.",
            "Section 8",
        )

    order_date = parse_date(order.date)
    if order_date is None:
        return _escalate("Order date is missing or unreadable; a human agent must review it.")

    if reason == "SUBSCRIPTION_CANCEL":
        if (today - order_date).days <= SUBSCRIPTION_CANCEL_DAYS:
            return PolicyResult(
                "approve",
                "Cancelled within 24 hours. Full refund approved.",
                "Section 5",
                round(order.total, 2),
                "full",
            )
        return _deny(
            "Subscription was not cancelled within the 24-hour window. Current billing period is "
            "non-refundable. Subscription will not auto-renew.",
            "Section 5",
        )

    delivered = parse_date(order.delivered_date)
    if delivered is None:
        return _deny("Order has not been delivered yet. Returns open once it arrives.", "Section 1")

    days_since_delivery = (today - delivered).days
    window = INTERNATIONAL_WINDOW_DAYS if order.is_international else DOMESTIC_WINDOW_DAYS
    if days_since_delivery > window:
        days_over = days_since_delivery - window
        if customer.loyalty_tier in VIP_TIERS and days_over <= VIP_GRACE_DAYS:
            return _escalate(
                f"VIP customer ({customer.loyalty_tier}) is {days_over} days past the {window}-day "
                "window. Eligible for VIP exception review: escalate to a human agent for store "
                "credit consideration.",
                "Section 6a",
            )
        scope = "International" if order.is_international else "Domestic"
        return _deny(
            f"Return window expired. Item was delivered {days_since_delivery} days ago. "
            f"{scope} orders must be returned within {window} days.",
            "Section 1",
        )

    if reason == "DAMAGED_ARRIVAL":
        if days_since_delivery > DAMAGE_REPORT_DAYS:
            return _deny(
                "Damaged arrival must be reported within 72 hours of delivery. This was reported "
                f"{days_since_delivery} days after delivery.",
                "Section 2",
            )
        return _approve(
            order.total,
            "full",
            "Damaged on arrival, reported within 72 hours.",
            note="No return required if photo evidence is provided.",
        )

    if reason == "DEFECTIVE":
        days_since_order = (today - order_date).days
        if days_since_order > WARRANTY_DAYS:
            return _deny(
                f"Defect reported {days_since_order} days after purchase. 90-day warranty window has expired.",
                "Section 2",
            )
        return _approve(order.total, "full_or_replacement", "Defect within the 90-day warranty.")

    if reason == "CHANGE_OF_MIND":
        fee = round(order.total * RESTOCKING_FEE_RATE, 2)
        amount = round(order.total - fee, 2)
        return _approve(
            amount,
            "partial",
            "Change of mind within the return window.",
            restocking_fee=fee,
            note=f"15% restocking fee of ${fee:.2f} applies. Refund: ${amount:.2f}.",
        )

    if reason == "WRONG_ITEM":
        return _approve(
            order.total,
            "full",
            "Wrong item received.",
            note="Free return label will be issued. No return required for orders under $50.",
        )
    if reason == "NOT_AS_DESCRIBED":
        return _approve(order.total, "full", "Item not as described.", note="Free return label will be issued.")
    return _approve(order.total, "full_or_parts_sent", "Item arrived with missing parts.")
