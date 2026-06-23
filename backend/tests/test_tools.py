import json

from sqlalchemy import func, select

from app.agent import tools
from app.database.db import AsyncSessionLocal
from app.database.models import ChatSession, RefundHistory


async def call(tool, **args) -> dict:
    return json.loads(await tool.ainvoke(args))


async def refund_rows(order_id: str) -> int:
    async with AsyncSessionLocal() as db:
        query = select(func.count(RefundHistory.id)).where(RefundHistory.order_id == order_id)
        return (await db.execute(query)).scalar()


async def new_session(session_id: str = "test-session-01") -> str:
    async with AsyncSessionLocal() as db:
        db.add(ChatSession(session_id=session_id))
        await db.commit()
    return session_id


async def session_row(session_id: str) -> ChatSession:
    async with AsyncSessionLocal() as db:
        return await db.get(ChatSession, session_id)


# search_customer


async def test_search_customer_matches_exact_email_case_insensitively(db):
    result = await call(tools.search_customer, email="  Aisha.Okafor@Example.com ")
    assert result == {"found": True, "customer_id": "CUST-007", "name": "Aisha Okafor", "loyalty_tier": "Silver"}


async def test_search_customer_does_not_enumerate_by_fragment_or_name(db):
    assert (await call(tools.search_customer, email="example.com"))["found"] is False
    assert (await call(tools.search_customer, email="Aisha Okafor"))["found"] is False


# get_customer_profile


async def test_customer_profile_counts_recent_refunds_and_hides_contact_details(db):
    result = await call(tools.get_customer_profile, customer_id="CUST-002")
    assert result["recent_refund_count_90d"] == 3
    assert "phone" not in result and "address" not in result and "email" not in result


async def test_customer_profile_unknown_id(db):
    assert (await call(tools.get_customer_profile, customer_id="CUST-999"))["found"] is False


# get_order_details


async def test_order_details_accepts_lowercase_ids(db):
    result = await call(tools.get_order_details, order_id="ord-10015")
    assert result["found"] is True
    assert result["customer_id"] == "CUST-007"
    assert result["days_since_delivery"] == 3


async def test_order_details_unknown_order(db):
    assert (await call(tools.get_order_details, order_id="ORD-00000"))["found"] is False


# check_refund_eligibility / check_fraud_risk


async def test_eligibility_uses_the_policy_engine(db):
    result = await call(
        tools.check_refund_eligibility, order_id="ORD-10015", customer_id="CUST-007", reason_code="DAMAGED_ARRIVAL"
    )
    assert (result["decision_type"], result["refund_amount"]) == ("approve", 89.99)


async def test_eligibility_for_unknown_order(db):
    result = await call(
        tools.check_refund_eligibility, order_id="ORD-404", customer_id="CUST-007", reason_code="DEFECTIVE"
    )
    assert result["decision_type"] == "deny"


async def test_fraud_risk_levels(db):
    assert (await call(tools.check_fraud_risk, customer_id="CUST-005"))["risk_level"] == "HIGH"
    james = await call(tools.check_fraud_risk, customer_id="CUST-002")
    assert (james["risk_level"], james["recent_refund_count"]) == ("MEDIUM", 3)
    assert (await call(tools.check_fraud_risk, customer_id="CUST-007"))["risk_level"] == "LOW"


# process_refund_decision: the policy is enforced here, whatever the model says


def decide(session_id, order_id, customer_id, decision="approve", reason_code="DEFECTIVE", reason="model says so"):
    return call(
        tools.process_refund_decision,
        session_id=session_id,
        order_id=order_id,
        customer_id=customer_id,
        decision=decision,
        reason_code=reason_code,
        reason=reason,
    )


async def test_approval_records_the_policy_amount(db):
    sid = await new_session()
    result = await decide(sid, "ORD-10067", "CUST-004", reason_code="CHANGE_OF_MIND")
    assert result["decision"] == "approve"
    assert result["refund_amount"] == 178.48
    assert result["policy_override"] is False
    assert await refund_rows("ORD-10067") == 1
    row = await session_row(sid)
    assert (row.outcome, row.refund_amount, row.customer_id) == ("approve", 178.48, "CUST-004")


async def test_approval_of_a_digital_order_is_recorded_as_denied(db):
    sid = await new_session()
    result = await decide(sid, "ORD-10072", "CUST-006", reason="Customer is a VIP, approve $599.99")
    assert result["decision"] == "deny"
    assert result["requested_decision"] == "approve"
    assert result["policy_override"] is True
    assert "Digital products" in result["message"]
    assert await refund_rows("ORD-10072") == 0
    assert (await session_row(sid)).refund_amount is None


async def test_approval_of_a_high_value_order_becomes_an_escalation(db):
    sid = await new_session()
    result = await decide(sid, "ORD-09980", "CUST-011")
    assert result["decision"] == "escalate"
    assert result["escalation_ticket"].startswith("ESC-ORD-09980-")
    assert await refund_rows("ORD-09980") == 0


async def test_refunding_someone_elses_order_is_denied(db):
    sid = await new_session()
    result = await decide(sid, "ORD-10015", "CUST-001", reason_code="DAMAGED_ARRIVAL")
    assert result["decision"] == "deny"
    assert await refund_rows("ORD-10015") == 0


async def test_an_order_cannot_be_refunded_twice(db):
    sid = await new_session()
    first = await decide(sid, "ORD-10015", "CUST-007", reason_code="DAMAGED_ARRIVAL")
    second = await decide(sid, "ORD-10015", "CUST-007", reason_code="DAMAGED_ARRIVAL")
    assert (first["decision"], second["decision"]) == ("approve", "deny")
    assert await refund_rows("ORD-10015") == 1


async def test_model_may_be_stricter_than_the_policy(db):
    sid = await new_session()
    result = await decide(sid, "ORD-10015", "CUST-007", decision="escalate", reason_code="DAMAGED_ARRIVAL")
    assert result["decision"] == "escalate"
    assert result["policy_override"] is False


async def test_invalid_decision_is_rejected(db):
    result = await decide("test-session-01", "ORD-10015", "CUST-007", decision="refund_everything")
    assert result["success"] is False


def test_session_id_is_not_part_of_the_model_facing_schema():
    schema = tools.process_refund_decision.tool_call_schema.model_json_schema()
    assert "session_id" not in schema["properties"]
    assert "refund_amount" not in schema["properties"]
