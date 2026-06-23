"""
LangGraph ReAct agent for refund processing.
Streams reasoning steps via an asyncio.Queue for SSE broadcast.
"""
import asyncio
import json
import re
import uuid
from typing import AsyncIterator
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from langchain_groq import ChatGroq
from langgraph.prebuilt import create_react_agent
from langgraph.graph import StateGraph, END
from sqlalchemy import select

from app.agent.state import AgentState
from app.agent.tools import ALL_TOOLS, get_order_details
from app.agent.prompts import SYSTEM_PROMPT
from app.config import settings
from app.database.db import AsyncSessionLocal
from app.database.models import ChatSession, Message, AgentLog, Customer


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


# Keep the old name for call-sites that already use it.
_has_identifier = _has_hard_identifier


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
    item_summary = ", ".join(
        f"{item.get('name', 'Item')} x{item.get('quantity', 1)}"
        for item in items
    ) or "No line items found."
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
        result = await db.execute(
            select(Customer).where(Customer.email == email.lower())
        )
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
    for text in [user_message, *[m.get("content", "") for m in history[-8:]
                                  if m.get("role") == "user"]]:
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
                return (
                    "The name and email address don't match our records. "
                    "Please double-check and try again."
                )
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
            return f"I couldn't find order {order_id}. Please check the order number or share the email address on the order."

        return _format_order_details(order)

    if not _has_identifier(user_message, history):
        return "Please share your order number or the email address on the order, and tell me what you need help with."

    return None


def _fallback_response(user_message: str, history: list[dict]) -> str:
    if not _has_identifier(user_message, history):
        return "Please share your order number or the email address on the order, and tell me what you need help with."
    return "I hit a tool-calling issue while processing that. Please restate the request with the order number and the exact issue you want help with."


def _build_llm() -> ChatGroq:
    return ChatGroq(
        api_key=settings.groq_api_key,
        model="llama-3.3-70b-versatile",
        temperature=0.1,
        streaming=True,
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _save_log(session_id: str, node: str, event_type: str, content: dict) -> None:
    """Persist an agent log entry to the database."""
    async with AsyncSessionLocal() as db:
        log = AgentLog(
            session_id=session_id,
            node=node,
            event_type=event_type,
            content=content,
        )
        db.add(log)
        await db.commit()


async def run_agent(
    session_id: str,
    user_message: str,
    history: list[dict],
    log_queue: "asyncio.Queue",
) -> str:
    """
    Run the refund agent for one turn.
    Emits structured log events to log_queue for real-time SSE streaming.
    Returns the final assistant text response.
    """
    import asyncio

    precomputed_response = await _maybe_handle_without_llm(session_id, user_message, history)
    if precomputed_response:
        decision_log = {
            "type": "decision",
            "node": "decision",
            "decision": "informational",
            "timestamp": _now_iso(),
            "content": "Handled without refund decision."
        }
        await log_queue.put(decision_log)
        await _save_log(session_id, "decision", "decision", decision_log)
        await log_queue.put(None)
        return precomputed_response

    llm = _build_llm()
    llm_with_tools = llm.bind_tools(ALL_TOOLS)

    # Build message history
    messages = [SystemMessage(content=SYSTEM_PROMPT)]
    for msg in history:
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            messages.append(AIMessage(content=msg["content"]))
    messages.append(HumanMessage(content=user_message))

    tool_map = {t.name: t for t in ALL_TOOLS}

    # ── Agentic loop ────────────────────────────────────────────────────────
    max_iterations = 10
    iteration = 0
    final_response = ""

    while iteration < max_iterations:
        iteration += 1

        # Emit "thinking" log
        thinking_log = {
            "type": "reasoning",
            "node": "agent",
            "iteration": iteration,
            "timestamp": _now_iso(),
            "content": f"Iteration {iteration}: Calling LLM to decide next action..."
        }
        await log_queue.put(thinking_log)
        await _save_log(session_id, "agent", "reasoning", thinking_log)

        # Call LLM
        try:
            response = await llm_with_tools.ainvoke(messages)
        except Exception as exc:
            error_body = getattr(exc, "body", {}) or {}
            error_log = {
                "type": "decision",
                "node": "decision",
                "decision": "error",
                "timestamp": _now_iso(),
                "content": str(error_body.get("failed_generation") or exc),
            }
            await log_queue.put(error_log)
            await _save_log(session_id, "decision", "decision", error_log)
            await log_queue.put(None)
            return _fallback_response(user_message, history)

        # Check for tool calls
        if hasattr(response, "tool_calls") and response.tool_calls:
            # Add assistant message with tool calls
            messages.append(response)

            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]

                # Inject session_id into process_refund_decision
                if tool_name == "process_refund_decision" and "session_id" not in tool_args:
                    tool_args["session_id"] = session_id

                # Emit tool call log
                tool_call_log = {
                    "type": "tool_call",
                    "node": "tools",
                    "tool": tool_name,
                    "args": tool_args,
                    "timestamp": _now_iso(),
                    "content": f"Calling tool: {tool_name}({json.dumps(tool_args, default=str)})"
                }
                await log_queue.put(tool_call_log)
                await _save_log(session_id, "tools", "tool_call", tool_call_log)

                # Execute tool
                if tool_name in tool_map:
                    try:
                        tool_result = await tool_map[tool_name].ainvoke(tool_args)
                    except Exception as e:
                        tool_result = json.dumps({"error": str(e)})
                else:
                    tool_result = json.dumps({"error": f"Unknown tool: {tool_name}"})

                # Emit tool result log
                try:
                    parsed_result = json.loads(tool_result) if isinstance(tool_result, str) else tool_result
                except Exception:
                    parsed_result = str(tool_result)

                tool_result_log = {
                    "type": "tool_result",
                    "node": "tools",
                    "tool": tool_name,
                    "result": parsed_result,
                    "timestamp": _now_iso(),
                    "content": f"Tool {tool_name} returned: {json.dumps(parsed_result, default=str)[:300]}"
                }
                await log_queue.put(tool_result_log)
                await _save_log(session_id, "tools", "tool_result", tool_result_log)

                # Add tool result to messages
                messages.append(ToolMessage(
                    content=tool_result if isinstance(tool_result, str) else json.dumps(tool_result),
                    tool_call_id=tool_call["id"],
                ))

        else:
            # No more tool calls — this is the final response
            final_response = response.content or ""

            # Detect decision type from tool history
            decision = "pending"
            for msg in messages:
                if isinstance(msg, ToolMessage):
                    try:
                        data = json.loads(msg.content)
                        if "decision" in data:
                            decision = data.get("decision", "pending")
                    except Exception:
                        pass

            # Emit final decision log
            decision_log = {
                "type": "decision",
                "node": "decision",
                "decision": decision,
                "timestamp": _now_iso(),
                "content": f"Final decision: {decision.upper()}. Composing customer response."
            }
            await log_queue.put(decision_log)
            await _save_log(session_id, "decision", "decision", decision_log)

            # Signal end of stream
            await log_queue.put(None)
            break

    if not final_response:
        final_response = "I apologize, I was unable to process your request. Please try again or contact support."
        await log_queue.put(None)

    return final_response
