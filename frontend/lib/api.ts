const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface ChatResponse {
  session_id: string;
  response: string;
}

export interface ChatSession {
  session_id: string;
  started_at: string | null;
  ended_at: string | null;
  outcome: string | null;
  refund_amount: number | null;
  message_count: number;
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string | null;
}

export interface AgentLog {
  type: "reasoning" | "tool_call" | "tool_result" | "decision";
  node: string;
  tool?: string;
  args?: Record<string, unknown>;
  result?: unknown;
  decision?: string;
  content: string;
  timestamp: string;
  session_id?: string;
  iteration?: number;
}

export interface SessionSummary {
  session_id: string;
  customer_id: string | null;
  started_at: string | null;
  ended_at: string | null;
  outcome: string | null;
  refund_amount: number | null;
}

export interface AdminStats {
  total_sessions: number;
  approved: number;
  denied: number;
  escalated: number;
  pending: number;
  total_refunded: number;
  customer_count: number;
  approval_rate: number;
}

export interface Customer {
  customer_id: string;
  name: string;
  email: string;
  loyalty_tier: string;
  fraud_flag: boolean;
  total_orders: number;
  total_spent: number;
}

// ── Chat ─────────────────────────────────────────────────────────────────────

export async function sendMessage(
  message: string,
  sessionId: string | null
): Promise<ChatResponse> {
  const res = await fetch(`${API}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId }),
  });
  if (!res.ok) {
    const error = new Error(`Chat error: ${res.status}`) as Error & { status?: number };
    error.status = res.status;
    throw error;
  }
  return res.json();
}

export async function createChatSession(): Promise<ChatSession> {
  const res = await fetch(`${API}/api/chat/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok) {
    const error = new Error(`Session create error: ${res.status}`) as Error & { status?: number };
    error.status = res.status;
    throw error;
  }
  return res.json();
}

export async function fetchChatMessages(sessionId: string): Promise<ChatMessage[]> {
  const res = await fetch(`${API}/api/chat/sessions/${sessionId}/messages`, {
    cache: "no-store",
  });
  if (!res.ok) {
    const error = new Error(`Messages fetch error: ${res.status}`) as Error & { status?: number };
    error.status = res.status;
    throw error;
  }
  return res.json();
}

/**
 * Streaming chat — returns an EventSource.
 * Events: "log" (AgentLog) | "response" ({text}) | "done"
 */
export function streamChat(
  message: string,
  sessionId: string,
  onLog: (log: AgentLog) => void,
  onResponse: (text: string) => void,
  onDone: () => void,
  onError?: (err: Event) => void
): EventSource {
  const url = new URL(`${API}/api/chat/stream`);
  url.searchParams.set("session_id", sessionId);
  url.searchParams.set("message", message);

  const es = new EventSource(url.toString());

  es.addEventListener("log", (e) => {
    try { onLog(JSON.parse((e as MessageEvent).data)); } catch {}
  });
  es.addEventListener("response", (e) => {
    try { onResponse(JSON.parse((e as MessageEvent).data).text); } catch {}
  });
  es.addEventListener("done", () => {
    es.close();
    onDone();
  });
  if (onError) es.onerror = onError;

  return es;
}

// ── Voice ─────────────────────────────────────────────────────────────────────

export async function transcribeAudio(blob: Blob): Promise<string> {
  const form = new FormData();
  form.append("file", blob, "audio.webm");
  const res = await fetch(`${API}/api/voice/transcribe`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`Transcription error: ${res.status}`);
  const data = await res.json();
  return data.text as string;
}

// ── Admin ─────────────────────────────────────────────────────────────────────

export async function fetchStats(): Promise<AdminStats> {
  const res = await fetch(`${API}/api/admin/stats`, { cache: "no-store" });
  return res.json();
}

export async function fetchSessions(limit = 20): Promise<SessionSummary[]> {
  const res = await fetch(`${API}/api/admin/sessions?limit=${limit}`, { cache: "no-store" });
  return res.json();
}

export async function fetchSessionLogs(sessionId: string): Promise<AgentLog[]> {
  const res = await fetch(`${API}/api/admin/sessions/${sessionId}/logs`, { cache: "no-store" });
  return res.json();
}

export async function fetchCustomers(): Promise<Customer[]> {
  const res = await fetch(`${API}/api/admin/customers`, { cache: "no-store" });
  return res.json();
}

export function subscribeAdminStream(
  onLog: (log: AgentLog & { session_id: string }) => void
): EventSource {
  const es = new EventSource(`${API}/api/admin/stream`);
  es.addEventListener("log", (e) => {
    try { onLog(JSON.parse((e as MessageEvent).data)); } catch {}
  });
  return es;
}
