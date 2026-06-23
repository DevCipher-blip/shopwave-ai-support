# ShopWave AI Refund Agent

> **AI-powered customer support agent** for automated e-commerce refund processing — built with LangGraph, Groq (Llama 3.3 70B + Whisper), FastAPI, and Next.js.

## Live Demo

| Interface | URL |
|---|---|
| Customer Chat | http://localhost:3000 |
| Admin Dashboard | http://localhost:3000/admin |
| API Docs | http://localhost:8000/docs |

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Frontend (Next.js 14)              │
│  ┌──────────────────┐    ┌───────────────────────┐  │
│  │  Customer Chat   │    │   Admin Dashboard     │  │
│  │  + Voice Input   │    │   + Live Log Stream   │  │
│  │  (Groq Whisper)  │    │   (SSE broadcast)     │  │
│  └────────┬─────────┘    └───────────┬───────────┘  │
└───────────┼──────────────────────────┼───────────────┘
            │ SSE / REST               │ SSE
┌───────────▼──────────────────────────▼───────────────┐
│                   Backend (FastAPI)                    │
│  ┌────────────────────────────────────────────────┐  │
│  │              LangGraph ReAct Agent              │  │
│  │                                                  │  │
│  │  START → classify → [tool loop] → decision → END│  │
│  │                                                  │  │
│  │  Tools:  search_customer                         │  │
│  │          get_customer_profile                    │  │
│  │          get_order_details                       │  │
│  │          check_refund_eligibility  ◄── policy   │  │
│  │          check_fraud_risk                        │  │
│  │          process_refund_decision                 │  │
│  └─────────────────────┬──────────────────────────┘  │
│                         │                              │
│  ┌──────────────────────▼──────────────────────────┐  │
│  │   SQLite DB (SQLAlchemy)                         │  │
│  │   • 15 customer CRM profiles                    │  │
│  │   • Orders, refund history, chat sessions       │  │
│  │   • Agent reasoning logs                        │  │
│  └─────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────┘
            │
┌───────────▼───────────────┐
│   Groq API (Free Tier)    │
│   • llama-3.3-70b         │  ← Agent LLM
│   • whisper-large-v3-turbo│  ← Voice STT
└───────────────────────────┘
```

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| LLM | Groq `llama-3.3-70b-versatile` | Free tier, 500+ tok/s, function calling |
| Agent | LangGraph (ReAct loop) | Explicit reasoning trace, tool orchestration |
| Voice STT | Groq `whisper-large-v3-turbo` | Free tier, best open-source accuracy |
| Voice TTS | Browser Web Speech API | Zero latency, zero cost |
| Backend | FastAPI + SSE | Async, streaming-native |
| Database | SQLite + SQLAlchemy async | Zero-config, ships everywhere |
| Frontend | Next.js 14 + Tailwind | App Router, TypeScript, dark theme |

**Cost: $0** — runs entirely on Groq's free tier.

---

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+
- Free [Groq API key](https://console.groq.com) (sign up, copy key)

### 1. Install dependencies

```bash
chmod +x setup.sh start.sh
./setup.sh
```

### 2. Add your Groq API key

```bash
# Edit backend/.env
GROQ_API_KEY=gsk_your_key_here
```

### 3. Start everything

```bash
./start.sh
```

Or separately:

```bash
# Terminal 1 — Backend
cd backend && source .venv/bin/activate
uvicorn app.main:app --reload --port 8000

# Terminal 2 — Frontend
cd frontend && npm run dev
```

---

## Policy Engine — 15 Covered Use Cases

| # | Scenario | Expected Decision |
|---|---|---|
| 1 | Standard refund within 30 days (`CHANGE_OF_MIND`) | ✅ Approve (−15% restocking) |
| 2 | Request past 30-day window | ❌ Deny |
| 3 | Digital software license refund | ❌ Deny (absolute) |
| 4 | Final Sale item | ❌ Deny (absolute) |
| 5 | Damaged on arrival (within 72h) | ✅ Approve (full) |
| 6 | Damaged on arrival (after 72h) | ❌ Deny |
| 7 | Defective item (within 90-day warranty) | ✅ Approve |
| 8 | Defective item (past 90 days) | ❌ Deny |
| 9 | Wrong item received | ✅ Approve + free return |
| 10 | Order total > $500 | ⚠️ Escalate (human review) |
| 11 | Fraud flag on account | ❌ Deny (policy §7) |
| 12 | 3+ refunds in 90 days | ⚠️ Escalate (fraud prevention) |
| 13 | VIP (Gold/Platinum) past window by ≤15 days | ⚠️ Escalate (store credit review) |
| 14 | International order past 14-day window | ❌ Deny |
| 15 | Subscription cancel within 24h | ✅ Approve (full) |

---

## Repository Structure

```
loopp/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI routes, SSE endpoints, voice
│   │   ├── config.py        # Pydantic settings
│   │   ├── agent/
│   │   │   ├── graph.py     # LangGraph ReAct agent loop
│   │   │   ├── tools.py     # 6 tools: search, lookup, policy, fraud, decision
│   │   │   ├── state.py     # AgentState TypedDict
│   │   │   └── prompts.py   # System prompt for Aria
│   │   └── database/
│   │       ├── models.py    # SQLAlchemy models
│   │       ├── db.py        # Async engine + session
│   │       └── seed.py      # Seeds CRM from JSON
│   └── requirements.txt
├── frontend/
│   ├── app/
│   │   ├── page.tsx         # Customer chat interface
│   │   └── admin/page.tsx   # Admin dashboard
│   ├── components/
│   │   ├── VoiceInput.tsx   # Mic recording → Groq Whisper
│   │   └── ReasoningPanel.tsx # Real-time agent reasoning sidebar
│   └── lib/
│       ├── api.ts           # All API calls + SSE subscriptions
│       └── utils.ts         # cn, formatCurrency, formatDate
├── data/
│   ├── crm_data.json        # 15 customer CRM profiles
│   └── refund_policy.md     # Full 11-section policy document
├── setup.sh                 # One-time install
├── start.sh                 # Start both services
└── README.md
```

---

## Demo Scenarios for Loom Video

### Standard refund (policy-compliant ✅)
> "Hi, I'm sarah.mitchell@email.com. I ordered headphones (ORD-10021) and they arrived damaged — I want a refund."

### Policy violation — past window (hold the line ❌)
> "I'm Priya Nair, priya.nair@outlook.com. I want to return my air purifier from order ORD-10033."
> *(Delivered April 14 — over 30 days ago)*

### Digital product — absolute denial ❌
> "I need a refund for my software license, order ORD-10072. Tom Beaumont, tom.beaumont@corp.com"

### Fraud flag — firm denial ❌
> "Elena Vasquez, elena.v@protonmail.com. I want to return ORD-10058."

### High-value escalation ⚠️
> "My name is Zoe Thompson, zoe.t@designstudio.com. I'd like a refund on ORD-09980."

### VIP exception flow ⚠️
> *(Same as Priya but imagine the window is only 5 days over — would escalate instead of deny)*

---

## Voice Flow

1. Click microphone button → browser captures audio
2. Audio blob → `POST /api/voice/transcribe` → Groq Whisper
3. Transcript auto-fills chat input and sends
4. Agent response text → Browser `speechSynthesis` (TTS)

---

## Admin Dashboard Features

- **Real-time log stream** — every agent reasoning step, tool call, and decision broadcast via SSE
- **Session stats** — approval rate, total refunded, outcome breakdown
- **Session table** — all conversations with outcome and refund amount
- **Live activity indicator** — green pulse when agent is active

---

## Design Decisions

**Why LangGraph over CrewAI?**
LangGraph gives explicit control over the agent loop, makes reasoning steps introspectable, and produces clean per-step events that we stream to the admin dashboard. The tool-call → tool-result cycle is completely transparent.

**Why Groq?**
Free tier with `llama-3.3-70b-versatile` gives OpenAI GPT-4 class performance at 500+ tokens/second — dramatically faster demos. Whisper STT is also on the free tier.

**Why SSE over WebSockets?**
SSE is simpler (HTTP/1.1, no upgrade), browser-native via `EventSource`, auto-reconnects, and is ideal for the one-directional server → client log streaming pattern.
