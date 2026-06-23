from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.agent.policy import evaluate_refund

TODAY = date(2026, 6, 19)


def days_ago(n: int) -> str:
    return (TODAY - timedelta(days=n)).isoformat()


def order(**overrides):
    base = dict(
        order_id="ORD-1",
        customer_id="CUST-1",
        date=days_ago(12),
        delivered_date=days_ago(10),
        total=100.0,
        is_international=False,
        items=[{"name": "Kettle", "is_digital": False, "is_final_sale": False}],
    )
    return SimpleNamespace(**{**base, **overrides})


def customer(**overrides):
    base = dict(customer_id="CUST-1", loyalty_tier="None", fraud_flag=False)
    return SimpleNamespace(**{**base, **overrides})


def refund(order_id="ORD-OLD", ago=10, status="approved"):
    return SimpleNamespace(order_id=order_id, date=days_ago(ago), status=status)


def evaluate(o=None, c=None, refunds=(), reason="CHANGE_OF_MIND"):
    return evaluate_refund(order() if o is None else o, customer() if c is None else c, list(refunds), reason, TODAY)


def test_unknown_order_is_denied():
    result = evaluate_refund(None, customer(), [], "DEFECTIVE", TODAY)
    assert result.decision == "deny"
    assert "not found" in result.reason


def test_unknown_customer_is_denied():
    result = evaluate_refund(order(), None, [], "DEFECTIVE", TODAY)
    assert result.decision == "deny"


def test_order_belonging_to_someone_else_is_denied():
    result = evaluate(c=customer(customer_id="CUST-2"))
    assert result.decision == "deny"
    assert "does not belong" in result.reason


def test_unknown_reason_code_is_denied():
    assert evaluate(reason="BECAUSE_I_SAID_SO").decision == "deny"


@pytest.mark.parametrize("reason", ["damaged arrival", "damaged-arrival", " Damaged_Arrival "])
def test_reason_code_is_normalized(reason):
    result = evaluate(o=order(delivered_date=days_ago(1)), reason=reason)
    assert result.decision == "approve"


def test_fraud_flag_denies_even_a_valid_request():
    result = evaluate(c=customer(fraud_flag=True), reason="DEFECTIVE")
    assert (result.decision, result.policy_section) == ("deny", "Section 7")


def test_already_refunded_order_is_denied():
    result = evaluate(refunds=[refund(order_id="ORD-1", ago=400)])
    assert result.decision == "deny"
    assert "already been refunded" in result.reason


def test_rejected_earlier_refund_does_not_block():
    assert evaluate(refunds=[refund(order_id="ORD-1", status="denied")]).decision == "approve"


def test_three_recent_refunds_escalate():
    result = evaluate(refunds=[refund("A", 10), refund("B", 40), refund("C", 89)])
    assert (result.decision, result.policy_section) == ("escalate", "Section 7")


def test_refunds_older_than_ninety_days_do_not_count():
    assert evaluate(refunds=[refund("A", 10), refund("B", 40), refund("C", 91)]).decision == "approve"


def test_digital_items_are_never_refundable():
    o = order(items=[{"name": "License", "is_digital": True}])
    assert evaluate(o=o, reason="DEFECTIVE").decision == "deny"


def test_final_sale_items_are_never_refundable():
    o = order(items=[{"name": "Mat", "is_final_sale": True}])
    assert evaluate(o=o, reason="WRONG_ITEM").decision == "deny"


@pytest.mark.parametrize(("total", "decision"), [(500.0, "approve"), (500.01, "escalate")])
def test_high_value_threshold(total, decision):
    assert evaluate(o=order(total=total)).decision == decision


@pytest.mark.parametrize(
    ("international", "days", "decision"),
    [(False, 30, "approve"), (False, 31, "deny"), (True, 14, "approve"), (True, 15, "deny")],
)
def test_return_window(international, days, decision):
    o = order(is_international=international, delivered_date=days_ago(days), date=days_ago(days + 2))
    assert evaluate(o=o).decision == decision


@pytest.mark.parametrize(("days", "decision"), [(45, "escalate"), (46, "deny")])
def test_vip_grace_period_escalates_but_never_approves(days, decision):
    o = order(delivered_date=days_ago(days), date=days_ago(days + 2))
    result = evaluate(o=o, c=customer(loyalty_tier="Gold"))
    assert result.decision == decision


@pytest.mark.parametrize(("days", "decision"), [(3, "approve"), (4, "deny")])
def test_damage_must_be_reported_within_72_hours(days, decision):
    o = order(delivered_date=days_ago(days))
    assert evaluate(o=o, reason="DAMAGED_ARRIVAL").decision == decision


@pytest.mark.parametrize(("days", "decision"), [(90, "approve"), (91, "deny")])
def test_defect_warranty_runs_from_purchase(days, decision):
    o = order(date=days_ago(days), delivered_date=days_ago(min(days, 20)))
    assert evaluate(o=o, reason="DEFECTIVE").decision == decision


def test_change_of_mind_deducts_restocking_fee():
    result = evaluate(o=order(total=209.98))
    assert result.decision == "approve"
    assert result.restocking_fee == 31.5
    assert result.refund_amount == 178.48


@pytest.mark.parametrize("reason", ["WRONG_ITEM", "NOT_AS_DESCRIBED", "MISSING_PARTS", "DAMAGED_ARRIVAL"])
def test_full_refund_reasons_pay_the_order_total(reason):
    result = evaluate(o=order(total=89.99, delivered_date=days_ago(2)), reason=reason)
    assert (result.decision, result.refund_amount) == ("approve", 89.99)


@pytest.mark.parametrize(("days", "decision"), [(1, "approve"), (2, "deny")])
def test_subscription_cancel_window(days, decision):
    o = order(date=days_ago(days), delivered_date=None)
    assert evaluate(o=o, reason="SUBSCRIPTION_CANCEL").decision == decision


def test_undelivered_order_cannot_be_returned_yet():
    assert evaluate(o=order(delivered_date=None)).decision == "deny"


def test_unreadable_dates_escalate_instead_of_passing():
    assert evaluate(o=order(date="not-a-date")).decision == "escalate"


def test_to_dict_keeps_the_tool_contract():
    body = evaluate(c=customer(fraud_flag=True)).to_dict()
    assert body["eligible"] is False
    assert body["decision_type"] == "deny"
    assert "denial_reason" in body
