from sqlalchemy import (
    Column, String, Float, Boolean, Integer,
    DateTime, ForeignKey, JSON, Text
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database.db import Base


class Customer(Base):
    __tablename__ = "customers"

    customer_id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False, unique=True, index=True)
    phone = Column(String)
    loyalty_tier = Column(String, default="None")
    account_created = Column(String)
    total_orders = Column(Integer, default=0)
    total_spent = Column(Float, default=0.0)
    fraud_flag = Column(Boolean, default=False)
    address = Column(JSON)

    orders = relationship("Order", back_populates="customer", lazy="select")
    refund_history = relationship("RefundHistory", back_populates="customer", lazy="select")


class Order(Base):
    __tablename__ = "orders"

    order_id = Column(String, primary_key=True, index=True)
    customer_id = Column(String, ForeignKey("customers.customer_id"), nullable=False)
    date = Column(String, nullable=False)
    delivered_date = Column(String)
    status = Column(String, default="processing")
    total = Column(Float, nullable=False)
    shipping = Column(String)
    is_international = Column(Boolean, default=False)
    items = Column(JSON)  # list of item dicts

    customer = relationship("Customer", back_populates="orders")


class RefundHistory(Base):
    __tablename__ = "refund_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(String, ForeignKey("customers.customer_id"), nullable=False)
    order_id = Column(String, nullable=False)
    date = Column(String, nullable=False)
    reason = Column(String)
    amount = Column(Float)
    status = Column(String)

    customer = relationship("Customer", back_populates="refund_history")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    session_id = Column(String, primary_key=True, index=True)
    customer_id = Column(String, nullable=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    ended_at = Column(DateTime(timezone=True), nullable=True)
    outcome = Column(String, nullable=True)  # approved | denied | escalated | pending
    refund_amount = Column(Float, nullable=True)
    messages = relationship("Message", back_populates="session", lazy="select")
    agent_logs = relationship("AgentLog", back_populates="session", lazy="select")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("chat_sessions.session_id"), nullable=False)
    role = Column(String, nullable=False)  # user | assistant
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    session = relationship("ChatSession", back_populates="messages")


class AgentLog(Base):
    __tablename__ = "agent_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("chat_sessions.session_id"), nullable=False)
    node = Column(String, nullable=False)      # graph node name
    event_type = Column(String, nullable=False) # tool_call | tool_result | reasoning | decision
    content = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    session = relationship("ChatSession", back_populates="agent_logs")
