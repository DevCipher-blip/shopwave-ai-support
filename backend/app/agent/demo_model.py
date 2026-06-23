"""
A deterministic stand-in for the Groq model (LLM_PROVIDER=fake).

It walks the same tool workflow the system prompt asks of the real model:
order lookup, eligibility check, decision, reply. That lets the app,
screenshots and README examples run with no API key and no network.
"""
import json
import re
import uuid
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

ORDER_ID_RE = re.compile(r"\bORD-\d+\b", re.IGNORECASE)

REASON_KEYWORDS = (
    ("DAMAGED_ARRIVAL", ("damaged", "broken", "cracked", "smashed")),
    ("DEFECTIVE", ("defective", "stopped working", "not working", "doesn't work", "faulty")),
    ("WRONG_ITEM", ("wrong item", "wrong size", "wrong colour", "wrong color", "different item")),
    ("NOT_AS_DESCRIBED", ("not as described", "doesn't match", "looks different")),
    ("MISSING_PARTS", ("missing",)),
    ("SUBSCRIPTION_CANCEL", ("subscription",)),
    ("CHANGE_OF_MIND", ("changed my mind", "change of mind", "don't want", "no longer", "don't need",
                        "return")),
)


def detect_reason(text: str) -> str | None:
    lowered = text.lower()
    for code, keywords in REASON_KEYWORDS:
        if any(k in lowered for k in keywords):
            return code
    return None


def _tool_call(name: str, args: dict[str, Any]) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{uuid.uuid4().hex[:12]}"}])


def _reply(result: dict[str, Any], order: dict[str, Any]) -> str:
    item = ", ".join(i.get("name", "item") for i in order.get("items") or []) or "your order"
    decision = result.get("decision")
    if decision == "approve":
        return (
            f"Good news: your refund of **${result['refund_amount']:.2f}** for {item} "
            f"({order['order_id']}) is approved. It will reach your original payment method "
            f"in {result.get('processing_time', '5–7 business days')}."
        )
    if decision == "escalate":
        return (
            f"I've passed {order['order_id']} to a senior agent, ticket "
            f"**{result.get('escalation_ticket', '')}**. {result['message'].split('Reason: ', 1)[-1]} "
            "You'll hear back within one business day."
        )
    return (
        f"I'm sorry, I can't refund {order['order_id']}. "
        f"{result['message'].split('Reason: ', 1)[-1]}"
    )


class DemoChatModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "shopwave-demo"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "DemoChatModel":
        return self

    def _generate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None,
                  **kwargs: Any) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next(messages))])

    def _next(self, messages: list[BaseMessage]) -> AIMessage:
        human = [m.content for m in messages if isinstance(m, HumanMessage) and isinstance(m.content, str)]
        last_human = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
        results: dict[str, dict] = {}
        for m in messages[last_human + 1:]:
            if isinstance(m, ToolMessage):
                results[m.name or ""] = json.loads(m.content)

        order_ids = [o.upper() for text in human for o in ORDER_ID_RE.findall(text)]
        if not order_ids:
            return AIMessage(content="Which order is this about? Please share the order number, e.g. ORD-10021.")
        order_id = order_ids[-1]

        order = results.get("get_order_details")
        if order is None:
            return _tool_call("get_order_details", {"order_id": order_id})
        if not order.get("found"):
            return AIMessage(content=f"I couldn't find order {order_id}. Could you double-check the number?")

        reason = next((r for text in reversed(human) if (r := detect_reason(text))), None)
        if reason is None:
            items = ", ".join(i.get("name", "item") for i in order.get("items") or [])
            return AIMessage(content=f"I found {order_id} ({items}). What went wrong with it?")

        eligibility = results.get("check_refund_eligibility")
        if eligibility is None:
            return _tool_call("check_refund_eligibility", {
                "order_id": order_id, "customer_id": order["customer_id"], "reason_code": reason,
            })

        decision = results.get("process_refund_decision")
        if decision is None:
            explanation = next(
                (eligibility[k] for k in ("reason", "denial_reason", "escalation_reason") if k in eligibility), ""
            )
            return _tool_call("process_refund_decision", {
                "order_id": order_id,
                "customer_id": order["customer_id"],
                "decision": eligibility["decision_type"],
                "reason_code": reason,
                "reason": explanation,
            })

        return AIMessage(content=_reply(decision, order))
