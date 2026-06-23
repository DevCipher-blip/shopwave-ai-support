"""
LangGraph refund agent.

    START -> triage -> (answered without the LLM) -> END
                    -> agent <-> tools
                       agent -> finalize -> END

Each step is logged to the database and pushed onto an asyncio.Queue that
the chat and admin SSE streams read from.
"""

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from sqlalchemy import select

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.state import AgentState
from app.agent.tools import ALL_TOOLS, get_order_details
from app.config import settings
from app.database.db import AsyncSessionLocal
from app.database.models import AgentLog, Customer

MAX_ITERATIONS = 10
TOOLS_BY_NAME = {t.name: t for t in ALL_TOOLS}
ASK_FOR_IDENTIFIER = (
    "Please share your order number or the email address on the order, and tell me what you need help with."
)
GAVE_UP_RESPONSE = "I apologize, I was unable to process your request. Please try again or contact support."

Emit = Callable[[str, str, dict], Awaitable[None]]


ORDER_ID_RE = re.compile(r"\bORD-\d+\b", re.IGNORECASE)
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
GREETING_RE = re.compile(r"^\s*(hi|hello|hey|good morning|good afternoon|good evening)\b[!.?\s]*$", re.IGNORECASE)
# Matches "I'm John Smith", "I am Priya Nair", "my name is ...", "this is ..."
NAME_INTRO_RE = re.compile(
    r"(?:i(?:'m| am)|my name is|this is)\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){1,3})",
    re.IGNORECASE,
)
OUT_OF_SCOPE_HINTS = (
    "weather",
    "temperature",
    "forecast",
    "sports",
    "score",
    "news",
    "politics",
    "stock",
    "bitcoin",
    "recipe",
    "joke",
    "translate",
    "code",
    "python",
    "javascript",
    "movie",
)


def _extract_order_id(text: str) -> str | None:
    match = ORDER_ID_RE.search(text or "")
    return match.group(0).upper() if match else None


def _extract_email(text: str) -> str | None:
    match = EMAIL_RE.search(text or "")
    return match.group(0).lower() if match else None


def _extract_name_intro(text: str) -> str | None:
    """Extract a customer name from an intro phrase like 'I'm Priya Nair'."""
    match = NAME_INTRO_RE.search(text or "")
    if not match:
        return None
    name = match.group(1).strip().title()
    # Skip generic words mistaken for names
    if name.lower() in {"shopwave", "aria", "an agent", "a customer", "here", "back"}:
        return None
    return name


def _has_hard_identifier(user_message: str, history: list[dict]) -> bool:
    """True only when a verifiable identifier (email or order ID) appears in the
    current message OR in recent assistant-confirmed turns.  Does NOT count
    order IDs that appeared while discussing a *different* customer."""
    # Current message always counts.
    if ORDER_ID_RE.search(user_message or "") or EMAIL_RE.search(user_message or ""):
        return True
    # Check only the last 4 messages in history (2 turns).
    for msg in history[-4:]:
        content = msg.get("content", "")
        if ORDER_ID_RE.search(content or "") or EMAIL_RE.search(content or ""):
            return True
    return False


def _is_greeting_only(user_message: str) -> bool:
    return bool(GREETING_RE.fullmatch(user_message or ""))


def _is_out_of_scope_request(user_message: str) -> bool:
    normalized = (user_message or "").lower()
    if _is_greeting_only(normalized):
        return False
    if ORDER_ID_RE.search(normalized) or EMAIL_RE.search(normalized):
        return False
    return any(hint in normalized for hint in OUT_OF_SCOPE_HINTS)


def _is_order_details_request(user_message: str) -> bool:
    normalized = (user_message or "").lower()
    keywords = (
        "order details",
        "order detail",
        "details for my order",
        "show my order",
        "what's in my order",
        "whats in my order",
        "status of my order",
        "track my order",
        "want order details",
        "wnat order details",
    )
    return any(keyword in normalized for keyword in keywords)


async def _load_last_session_order_id(session_id: str) -> str | None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AgentLog)
            .where(AgentLog.session_id == session_id, AgentLog.event_type == "tool_result")
            .order_by(AgentLog.id.desc())
        )
        for log in result.scalars():
            content = log.content or {}
            tool_result = content.get("result") if isinstance(content, dict) else None
            if isinstance(tool_result, dict):
                order_id = tool_result.get("order_id")
                if isinstance(order_id, str) and order_id:
                    return order_id.upper()
    return None


def _format_order_details(order: dict) -> str:
    items = order.get("items") or []
    item_summary = (
        ", ".join(f"{item.get('name', 'Item')} x{item.get('quantity', 1)}" for item in items) or "No line items found."
    )
    shipping_scope = "international" if order.get("is_international") else "domestic"
    delivered_date = order.get("delivered_date") or "Not delivered yet"
    return (
        f"Here are the details for order {order['order_id']}:\n"
        f"- Status: {order.get('status', 'unknown')}\n"
        f"- Order date: {order.get('order_date', 'unknown')}\n"
        f"- Delivered: {delivered_date}\n"
        f"- Total: ${order.get('total', 0):.2f}\n"
        f"- Shipping: {order.get('shipping', 'unknown')} ({shipping_scope})\n"
        f"- Items: {item_summary}"
    )


async def _lookup_customer_by_email(email: str) -> Customer | None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Customer).where(Customer.email == email.lower()))
        return result.scalar_one_or_none()


async def _lookup_customer_by_name(name: str) -> Customer | None:
    name_lower = name.lower()
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Customer))
        for customer in result.scalars().all():
            if name_lower in customer.name.lower() or customer.name.lower() in name_lower:
                return customer
    return None


def _email_in_conversation(user_message: str, history: list[dict]) -> str | None:
    """Return the most recent email found in the current conversation."""
    for text in [user_message, *[m.get("content", "") for m in reversed(history[-10:])]]:
        email = _extract_email(text)
        if email:
            return email
    return None


def _name_in_conversation(user_message: str, history: list[dict]) -> str | None:
    for text in [user_message, *[m.get("content", "") for m in history[-8:] if m.get("role") == "user"]]:
        name = _extract_name_intro(text)
        if name:
            return name
    return None


async def _maybe_handle_without_llm(
    session_id: str,
    user_message: str,
    history: list[dict],
) -> str | None:
    if _is_out_of_scope_request(user_message):
        return (
            "I can only help with ShopWave order support such as refunds, returns, "
            "delivery status, and order details. If you need help with an order, "
            "please share the order number or the email address on the order."
        )

    # ── Name-intro without a matching email → ask for email verification ────
    name_intro = _extract_name_intro(user_message)
    email_in_msg = _extract_email(user_message)
    order_in_msg = _extract_order_id(user_message)

    if name_intro and not email_in_msg and not order_in_msg:
        # Check if the email was already confirmed in this conversation.
        conv_email = _email_in_conversation("", history)  # skip current message
        if conv_email:
            # Email is already in history — verify it matches the claimed name.
            customer = await _lookup_customer_by_email(conv_email)
            if customer and name_intro.lower() in customer.name.lower():
                # Identity confirmed — let the LLM continue.
                return None
            elif customer:
                return (
                    f"The name {name_intro!r} doesn't match the account for that email. "
                    "Please share the email address registered on your ShopWave account."
                )
        # No email in conversation yet — ask the customer to verify.
        customer = await _lookup_customer_by_name(name_intro)
        if customer:
            first = customer.name.split()[0]
            return (
                f"Hi {first}! To keep your account secure, please confirm the "
                f"email address registered on your ShopWave account before I can "
                f"access any order details."
            )
        return (
            "I couldn't find a ShopWave account under that name. "
            "Please share the email address on the order or the order number directly."
        )

    # ── Email provided → verify identity if a name was also introduced ──────
    if email_in_msg:
        conv_name = _name_in_conversation(user_message, history)
        if conv_name:
            customer = await _lookup_customer_by_email(email_in_msg)
            if customer and conv_name.lower() in customer.name.lower():
                # Verified — let the LLM continue (it now has email context).
                return None
            elif customer:
                return "The name and email address don't match our records. Please double-check and try again."
        # Email without a prior name claim — pass through to LLM normally.
        return None

    if _is_order_details_request(user_message):
        order_id = _extract_order_id(user_message)
        if not order_id:
            for msg in reversed(history[-6:]):
                order_id = _extract_order_id(msg.get("content", ""))
                if order_id:
                    break
        if not order_id:
            order_id = await _load_last_session_order_id(session_id)

        if not order_id:
            return "Please share the order number you want details for, or the email address on the order."

        order_raw = await get_order_details.ainvoke({"order_id": order_id})
        try:
            order = json.loads(order_raw) if isinstance(order_raw, str) else order_raw
        except Exception:
            order = None

        if not isinstance(order, dict) or not order.get("found"):
            return (
                f"I couldn't find order {order_id}. "
                "Please check the order number or share the email address on the order."
            )

        return _format_order_details(order)

    if not _has_hard_identifier(user_message, history):
        return ASK_FOR_IDENTIFIER

    return None


def _fallback_response(user_message: str, history: list[dict]) -> str:
    if not _has_hard_identifier(user_message, history):
        return ASK_FOR_IDENTIFIER
    return (
        "I hit a tool-calling issue while processing that. "
        "Please restate the request with the order number and the exact issue you want help with."
    )


def get_chat_model() -> BaseChatModel:
    if settings.llm_provider == "fake":
        from app.agent.demo_model import DemoChatModel

        return DemoChatModel()

    from langchain_groq import ChatGroq

    return ChatGroq(api_key=settings.groq_api_key, model=settings.groq_model, temperature=0.1)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


async def _save_log(session_id: str, node: str, event_type: str, content: dict) -> None:
    async with AsyncSessionLocal() as db:
        db.add(AgentLog(session_id=session_id, node=node, event_type=event_type, content=content))
        await db.commit()


def _recorded_outcome(messages: list) -> dict:
    """The result of the last successful process_refund_decision call this turn, if any."""
    outcome: dict = {}
    for msg in messages:
        if isinstance(msg, ToolMessage) and msg.name == "process_refund_decision":
            try:
                parsed = json.loads(msg.content)
            except (TypeError, ValueError):
                continue
            if isinstance(parsed, dict) and parsed.get("success"):
                outcome = parsed
    return outcome


def route_after_triage(state: AgentState) -> str:
    return END if state.get("response") else "agent"


def route_after_agent(state: AgentState) -> str:
    if state.get("decision") == "error":
        return END
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls and state.get("iterations", 0) < MAX_ITERATIONS:
        return "tools"
    return "finalize"


def build_graph(model: BaseChatModel, *, session_id: str, user_message: str, history: list[dict], emit: Emit):
    llm = model.bind_tools(ALL_TOOLS)

    async def triage(state: AgentState) -> dict:
        text = await _maybe_handle_without_llm(session_id, user_message, history)
        if not text:
            return {}
        await emit(
            "decision",
            "decision",
            {
                "type": "decision",
                "node": "decision",
                "decision": "informational",
                "content": "Handled without refund decision.",
            },
        )
        return {"response": text, "decision": "informational"}

    async def agent(state: AgentState) -> dict:
        iteration = state.get("iterations", 0) + 1
        await emit(
            "agent",
            "reasoning",
            {
                "type": "reasoning",
                "node": "agent",
                "iteration": iteration,
                "content": f"Iteration {iteration}: Calling LLM to decide next action...",
            },
        )
        try:
            response = await llm.ainvoke(state["messages"])
        except Exception as exc:  # provider/network errors end the turn with a safe reply
            body = getattr(exc, "body", None) or {}
            detail = body.get("failed_generation") if isinstance(body, dict) else None
            await emit(
                "decision",
                "decision",
                {
                    "type": "decision",
                    "node": "decision",
                    "decision": "error",
                    "content": str(detail or exc),
                },
            )
            return {"iterations": iteration, "decision": "error", "response": _fallback_response(user_message, history)}
        return {"messages": [response], "iterations": iteration}

    async def tools(state: AgentState) -> dict:
        results = []
        for call in state["messages"][-1].tool_calls:
            name = call["name"]
            # The session is never taken from model output.
            args = {k: v for k, v in call["args"].items() if k != "session_id"}
            await emit(
                "tools",
                "tool_call",
                {
                    "type": "tool_call",
                    "node": "tools",
                    "tool": name,
                    "args": args,
                    "content": f"Calling tool: {name}({json.dumps(args, default=str)})",
                },
            )
            if name == "process_refund_decision":
                args["session_id"] = session_id

            tool = TOOLS_BY_NAME.get(name)
            if tool is None:
                output = json.dumps({"error": f"Unknown tool: {name}"})
            else:
                try:
                    output = await tool.ainvoke(args)
                except Exception as exc:  # bad arguments from the model go back to it as data
                    output = json.dumps({"error": str(exc)})

            try:
                parsed = json.loads(output)
            except (TypeError, ValueError):
                parsed = str(output)
            await emit(
                "tools",
                "tool_result",
                {
                    "type": "tool_result",
                    "node": "tools",
                    "tool": name,
                    "result": parsed,
                    "content": f"Tool {name} returned: {json.dumps(parsed, default=str)[:300]}",
                },
            )
            results.append(ToolMessage(content=output, tool_call_id=call["id"], name=name))
        return {"messages": results}

    async def finalize(state: AgentState) -> dict:
        last = state["messages"][-1]
        text = last.content if isinstance(last, AIMessage) and not last.tool_calls else ""
        outcome = _recorded_outcome(state["messages"])
        decision = outcome.get("decision", "pending")
        if outcome.get("policy_override"):
            # The model asked for more than the policy allows, so its wording
            # can't be trusted to match what was recorded.
            text = f"I wasn't able to approve that refund. {outcome['message']}"
        await emit(
            "decision",
            "decision",
            {
                "type": "decision",
                "node": "decision",
                "decision": decision,
                "content": f"Final decision: {decision.upper()}. Composing customer response.",
            },
        )
        return {"response": text or GAVE_UP_RESPONSE, "decision": decision}

    graph = StateGraph(AgentState)
    graph.add_node("triage", triage)
    graph.add_node("agent", agent)
    graph.add_node("tools", tools)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "triage")
    graph.add_conditional_edges("triage", route_after_triage, ["agent", END])
    graph.add_conditional_edges("agent", route_after_agent, ["tools", "finalize", END])
    graph.add_edge("tools", "agent")
    graph.add_edge("finalize", END)
    return graph.compile()


def _initial_messages(user_message: str, history: list[dict]) -> list:
    messages = [SystemMessage(content=SYSTEM_PROMPT)]
    for msg in history:
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            messages.append(AIMessage(content=msg["content"]))
    messages.append(HumanMessage(content=user_message))
    return messages


async def run_agent(
    session_id: str,
    user_message: str,
    history: list[dict],
    log_queue: asyncio.Queue,
    model: BaseChatModel | None = None,
) -> str:
    """
    Run the refund agent for one turn and return the reply text.
    Log events go to log_queue as they happen; None marks the end of the turn.
    """

    async def emit(node: str, event_type: str, payload: dict) -> None:
        payload = {**payload, "timestamp": _now_iso()}
        await log_queue.put(payload)
        await _save_log(session_id, node, event_type, payload)

    try:
        graph = build_graph(
            model or get_chat_model(), session_id=session_id, user_message=user_message, history=history, emit=emit
        )
        final = await graph.ainvoke(
            {"messages": _initial_messages(user_message, history), "iterations": 0},
            config={"recursion_limit": 2 * MAX_ITERATIONS + 5},
        )
        return final.get("response") or GAVE_UP_RESPONSE
    finally:
        await log_queue.put(None)
