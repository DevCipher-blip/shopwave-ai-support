import { parseSseBuffer } from "./sse";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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

// ── Chat ─────────────────────────────────────────────────────────────────────

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

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

function adminHeaders(token: string): HeadersInit {
  return { Authorization: `Bearer ${token}` };
}

async function adminGet<T>(path: string, token: string): Promise<T> {
  const res = await fetch(`${API}/api/admin${path}`, { cache: "no-store", headers: adminHeaders(token) });
  if (!res.ok) throw new ApiError(`Admin request failed: ${res.status}`, res.status);
  return res.json();
}

export function fetchStats(token: string): Promise<AdminStats> {
  return adminGet("/stats", token);
}

export function fetchSessions(token: string, limit = 20): Promise<SessionSummary[]> {
  return adminGet(`/sessions?limit=${limit}`, token);
}

/**
 * Admin event stream. EventSource cannot send an Authorization header, so this
 * reads the SSE response through fetch. Returns a function that closes it.
 */
export function subscribeAdminStream(
  token: string,
  onLog: (log: AgentLog & { session_id: string }) => void,
  onError: (err: unknown) => void
): () => void {
  const controller = new AbortController();

  (async () => {
    const res = await fetch(`${API}/api/admin/stream`, {
      headers: { ...adminHeaders(token), Accept: "text/event-stream" },
      signal: controller.signal,
    });
    if (!res.ok || !res.body) throw new ApiError(`Admin stream failed: ${res.status}`, res.status);

    const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      const parsed = parseSseBuffer(buffer + value);
      buffer = parsed.rest;
      for (const event of parsed.events) {
        if (event.event !== "log") continue;
        try { onLog(JSON.parse(event.data)); } catch { /* skip malformed event */ }
      }
    }
  })().catch((err) => {
    if (!controller.signal.aborted) onError(err);
  });

  return () => controller.abort();
}
