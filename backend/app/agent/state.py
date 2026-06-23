from typing import Annotated, Any
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


class AgentState(TypedDict):
    # Conversation messages
    messages: Annotated[list[BaseMessage], add_messages]

    # Session context
    session_id: str

    # Resolved entities
    customer_id: str | None
    order_id: str | None
    customer_profile: dict | None
    order_details: dict | None

    # Refund request data
    refund_reason: str | None      # e.g. DEFECTIVE, CHANGE_OF_MIND
    refund_amount: float | None

    # Policy check results
    policy_result: dict | None     # {eligible, reason, decision_type}

    # Final decision
    decision: str | None           # approve | deny | escalate | pending

    # Reasoning trace emitted to admin dashboard
    reasoning_steps: list[dict]
