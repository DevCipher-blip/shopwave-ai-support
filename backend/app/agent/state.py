from typing import Annotated

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class AgentState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    iterations: int
    # Set by whichever node ends the turn.
    response: str
    decision: str  # approve | deny | escalate | pending | informational | error
