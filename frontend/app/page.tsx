"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import Link from "next/link";
import { ListTree, Loader2, Plus, Send, Volume2, VolumeX } from "lucide-react";
import {
  createChatSession,
  fetchChatMessages,
  streamChat,
  type AgentLog,
  type ChatMessage,
} from "@/lib/api";
import { cn, formatDate, newId } from "@/lib/utils";
import { MarkdownText } from "@/components/MarkdownText";
import { ReasoningPanel } from "@/components/ReasoningPanel";
import { VoiceInput } from "@/components/VoiceInput";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}

interface SessionRecord {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: Message[] | null;
  logs: AgentLog[];
  isLoading: boolean;
}

interface StoredSessionMeta {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
}

const WELCOME = `Hi, I'm **Aria** from the ShopWave returns desk.

I can check whether an order qualifies for a refund and record the decision. To start, tell me:
- your **order number** (for example ORD-10015) or the email on the order
- what went wrong with it`;

const EXAMPLES = [
  "My order ORD-10015 arrived damaged",
  "I changed my mind about ORD-10067",
  "ORD-09980 stopped working",
];

const STORAGE_KEY = "shopwave-chat-sessions-v1";
const DEFAULT_SESSION_TITLE = "New conversation";

function createWelcomeMessage(): Message {
  return {
    id: "welcome",
    role: "assistant",
    content: WELCOME,
    timestamp: new Date(),
  };
}

function deriveSessionTitle(text: string): string {
  const cleaned = text.replace(/\s+/g, " ").trim();
  if (!cleaned) return DEFAULT_SESSION_TITLE;
  return cleaned.length > 36 ? `${cleaned.slice(0, 36)}...` : cleaned;
}

function mapChatMessage(message: ChatMessage): Message {
  return {
    id: `server-${message.id}`,
    role: message.role,
    content: message.content,
    timestamp: message.created_at ? new Date(message.created_at) : new Date(),
  };
}

export default function ChatPage() {
  const [sessions, setSessions] = useState<SessionRecord[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [showLogs, setShowLogs] = useState(false);
  const [ttsEnabled, setTtsEnabled] = useState(true);
  const [isBootstrapping, setIsBootstrapping] = useState(true);
  const [bootError, setBootError] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const eventSourcesRef = useRef<Record<string, EventSource>>({});
  const activeSessionIdRef = useRef<string | null>(null);

  const activeSession = sessions.find((session) => session.id === activeSessionId) ?? null;
  const activeMessages = activeSession?.messages?.length ? activeSession.messages : [createWelcomeMessage()];
  const activeLogs = activeSession?.logs ?? [];
  const activeIsLoading = activeSession?.isLoading ?? false;

  useEffect(() => {
    activeSessionIdRef.current = activeSessionId;
  }, [activeSessionId]);

  const activeServerMessages = activeSession?.messages;
  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activeServerMessages]);

  const updateSession = useCallback((sessionId: string, updater: (session: SessionRecord) => SessionRecord) => {
    setSessions((prev) => prev.map((session) => session.id === sessionId ? updater(session) : session));
  }, []);

  const createSessionRecord = useCallback(async () => {
    const session = await createChatSession();
    return {
      id: session.session_id,
      title: DEFAULT_SESSION_TITLE,
      createdAt: session.started_at ?? new Date().toISOString(),
      updatedAt: session.started_at ?? new Date().toISOString(),
      messages: [],
      logs: [],
      isLoading: false,
    } satisfies SessionRecord;
  }, []);

  const loadSessionMessages = useCallback(async (sessionId: string) => {
    const serverMessages = await fetchChatMessages(sessionId);
    updateSession(sessionId, (session) => {
      const mappedMessages = serverMessages.map(mapChatMessage);
      const firstUserMessage = mappedMessages.find((message) => message.role === "user");
      return {
        ...session,
        messages: mappedMessages,
        title: session.title === DEFAULT_SESSION_TITLE && firstUserMessage
          ? deriveSessionTitle(firstUserMessage.content)
          : session.title,
        updatedAt: mappedMessages.at(-1)?.timestamp.toISOString() ?? session.updatedAt,
      };
    });
  }, [updateSession]);

  const createAndActivateSession = useCallback(async () => {
    const newSession = await createSessionRecord();
    setSessions((prev) => [newSession, ...prev]);
    setActiveSessionId(newSession.id);
    return newSession.id;
  }, [createSessionRecord]);

  useEffect(() => {
    let cancelled = false;

    const bootstrap = async () => {
      try {
        const raw = window.localStorage.getItem(STORAGE_KEY);
        if (raw) {
          const parsed = JSON.parse(raw) as StoredSessionMeta[];
          if (Array.isArray(parsed) && parsed.length > 0) {
            const restored = parsed.map((session) => ({
              id: session.id,
              title: session.title || DEFAULT_SESSION_TITLE,
              createdAt: session.createdAt,
              updatedAt: session.updatedAt,
              messages: null,
              logs: [],
              isLoading: false,
            } satisfies SessionRecord));

            const validSessions: SessionRecord[] = [];
            for (const session of restored) {
              try {
                const serverMessages = await fetchChatMessages(session.id);
                validSessions.push({
                  ...session,
                  messages: serverMessages.map(mapChatMessage),
                });
              } catch (error) {
                const status = typeof error === "object" && error && "status" in error
                  ? Number((error as { status?: number }).status)
                  : undefined;
                if (status !== 404) {
                  validSessions.push(session);
                }
              }
            }

            if (validSessions.length > 0) {
              if (!cancelled) {
                setSessions(validSessions);
                setActiveSessionId(validSessions[0].id);
              }
              return;
            }
          }
        }

        const firstSessionId = await createAndActivateSession();
        if (cancelled && eventSourcesRef.current[firstSessionId]) {
          eventSourcesRef.current[firstSessionId].close();
        }
      } finally {
        if (!cancelled) setIsBootstrapping(false);
      }
    };

    bootstrap().catch(() => {
      if (!cancelled) setBootError(true);
    });

    return () => {
      cancelled = true;
      Object.values(eventSourcesRef.current).forEach((source) => source.close());
      eventSourcesRef.current = {};
    };
  }, [createAndActivateSession]);

  useEffect(() => {
    if (!sessions.length) return;
    const toStore: StoredSessionMeta[] = sessions.map((session) => ({
      id: session.id,
      title: session.title,
      createdAt: session.createdAt,
      updatedAt: session.updatedAt,
    }));
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(toStore));
  }, [sessions]);

  const selectSession = (sessionId: string) => {
    setActiveSessionId(sessionId);
    const selected = sessions.find((session) => session.id === sessionId);
    if (!selected || selected.messages !== null) return;
    // Restored sessions whose messages failed to load during bootstrap.
    loadSessionMessages(sessionId).catch(() => {
      const remaining = sessions.filter((session) => session.id !== sessionId);
      setSessions(remaining);
      if (activeSessionIdRef.current === sessionId) setActiveSessionId(remaining[0]?.id ?? null);
    });
  };

  const speak = useCallback((text: string) => {
    if (!ttsEnabled || typeof window === "undefined") return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text.replace(/\*\*/g, "").replace(/[#*_`]/g, ""));
    utterance.rate = 1.05;
    utterance.pitch = 1;
    const voices = window.speechSynthesis.getVoices();
    const preferred = voices.find(v => v.name.includes("Samantha") || v.name.includes("Google US English") || v.lang === "en-US");
    if (preferred) utterance.voice = preferred;
    window.speechSynthesis.speak(utterance);
  }, [ttsEnabled]);

  const sendMessage = useCallback(async (text: string, targetSessionId?: string) => {
    const sessionId = targetSessionId ?? activeSessionIdRef.current;
    if (!sessionId) return;

    const trimmed = text.trim();
    const targetSession = sessions.find((session) => session.id === sessionId);
    if (!trimmed || targetSession?.isLoading) return;

    const userMsg: Message = {
      id: newId("user"),
      role: "user",
      content: trimmed,
      timestamp: new Date(),
    };
    setInput("");

    const assistantId = newId("assistant");
    updateSession(sessionId, (session) => ({
      ...session,
      title: session.title === DEFAULT_SESSION_TITLE ? deriveSessionTitle(trimmed) : session.title,
      updatedAt: new Date().toISOString(),
      logs: [],
      isLoading: true,
      messages: [
        ...(session.messages ?? []),
        userMsg,
        { id: assistantId, role: "assistant", content: "", timestamp: new Date() },
      ],
    }));

    let finalText = "";
    let finished = false;

    const source = streamChat(
      trimmed,
      sessionId,
      (log) => {
        updateSession(sessionId, (session) => ({
          ...session,
          logs: [...session.logs.slice(-199), log],
        }));
        setShowLogs(true);
      },
      (responseText) => {
        finalText = responseText;
        updateSession(sessionId, (session) => ({
          ...session,
          updatedAt: new Date().toISOString(),
          messages: (session.messages ?? []).map((message) =>
            message.id === assistantId ? { ...message, content: responseText } : message
          ),
        }));
      },
      () => {
        finished = true;
        delete eventSourcesRef.current[sessionId];
        updateSession(sessionId, (session) => ({ ...session, isLoading: false }));
        if (finalText && activeSessionIdRef.current === sessionId) speak(finalText);
      },
      () => {
        if (finished) return;
        source.close();
        delete eventSourcesRef.current[sessionId];
        updateSession(sessionId, (session) => ({
          ...session,
          isLoading: false,
          messages: (session.messages ?? []).map((message) =>
            message.id === assistantId
              ? {
                  ...message,
                  content: "I couldn't complete that request. Please try again with your order number or the email address on the order.",
                }
              : message
          ),
        }));
      }
    );

    eventSourcesRef.current[sessionId] = source;
  }, [sessions, speak, updateSession]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  };

  const handleVoiceTranscript = (text: string) => {
    setInput(text);
    setTimeout(() => sendMessage(text), 100);
  };

  const createSession = async () => {
    window.speechSynthesis.cancel();
    setInput("");
    await createAndActivateSession();
  };

  if (isBootstrapping || bootError) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-paper px-4">
        <div className="w-full max-w-sm rounded-xl border border-line bg-card p-8 text-center">
          <p className="font-display text-xl font-semibold">ShopWave Returns Desk</p>
          {bootError ? (
            <>
              <p role="alert" className="mt-3 text-sm text-deny">
                The support service isn&apos;t reachable right now.
              </p>
              <button
                type="button"
                onClick={() => window.location.reload()}
                className="mt-5 rounded-lg bg-tide-700 px-4 py-2 text-sm font-medium text-card hover:bg-tide-800"
              >
                Try again
              </button>
            </>
          ) : (
            <p className="mt-3 flex items-center justify-center gap-2 text-sm text-muted" role="status">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Opening a conversation…
            </p>
          )}
        </div>
      </main>
    );
  }

  const canSend = Boolean(input.trim()) && !activeIsLoading && Boolean(activeSession);
  const showExamples = Boolean(activeSession) && !activeSession?.messages?.length;

  return (
    <div className="flex h-dvh overflow-hidden bg-paper">
      <aside aria-label="Conversations" className="hidden w-72 shrink-0 flex-col border-r border-line bg-card md:flex">
        <div className="px-5 pb-4 pt-5">
          <p className="font-display text-xl font-semibold leading-tight">ShopWave</p>
          <p className="text-sm text-muted">Returns desk</p>
          <button
            type="button"
            onClick={createSession}
            className="mt-4 flex w-full items-center justify-center gap-2 rounded-lg bg-tide-700 px-4 py-2.5 text-sm font-medium text-card hover:bg-tide-800"
          >
            <Plus className="h-4 w-4" aria-hidden />
            New conversation
          </button>
        </div>
        <div className="perforation mx-5" />
        <nav className="flex-1 overflow-y-auto px-3 py-3">
          <ul className="space-y-1">
            {sessions.map((session) => {
              const isActive = session.id === activeSessionId;
              return (
                <li key={session.id}>
                  <button
                    type="button"
                    onClick={() => selectSession(session.id)}
                    aria-current={isActive ? "true" : undefined}
                    className={cn(
                      "w-full rounded-lg px-3 py-2.5 text-left transition-colors",
                      isActive ? "bg-tide-50 text-tide-800" : "hover:bg-paper"
                    )}
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm font-medium">{session.title}</span>
                      {session.isLoading && <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" aria-label="Working" />}
                    </span>
                    <span className="block text-xs text-muted">{formatDate(session.updatedAt)}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>
        <p className="border-t border-line px-5 py-3 text-xs text-muted">
          Decisions follow the ShopWave refund policy v3.2. Amounts are set by the policy engine, not the chat.
        </p>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex shrink-0 items-center justify-between gap-3 border-b border-line bg-card px-4 py-3 md:px-6">
          <div className="min-w-0">
            <h1 className="truncate font-display text-lg font-semibold leading-tight">
              <span className="md:hidden">ShopWave</span>
              <span className="hidden md:inline">{activeSession?.title ?? "Returns desk"}</span>
            </h1>
            <p className="text-xs text-muted">Aria, refund assistant</p>
          </div>

          <div className="flex shrink-0 items-center gap-1">
            <button
              type="button"
              onClick={() => setTtsEnabled((v) => !v)}
              aria-pressed={ttsEnabled}
              aria-label={ttsEnabled ? "Stop reading replies aloud" : "Read replies aloud"}
              title={ttsEnabled ? "Stop reading replies aloud" : "Read replies aloud"}
              className="rounded-lg p-2 text-muted hover:bg-paper hover:text-ink"
            >
              {ttsEnabled ? <Volume2 className="h-4 w-4" aria-hidden /> : <VolumeX className="h-4 w-4" aria-hidden />}
            </button>
            <button
              type="button"
              onClick={() => setShowLogs((v) => !v)}
              aria-pressed={showLogs}
              className={cn(
                "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium",
                showLogs ? "bg-tide-50 text-tide-800" : "text-muted hover:bg-paper hover:text-ink"
              )}
            >
              <ListTree className="h-4 w-4" aria-hidden />
              <span className="hidden sm:inline">Reasoning</span>
              {activeLogs.length > 0 && (
                <span className="rounded-full bg-tide-700 px-1.5 font-mono text-[11px] text-card">{activeLogs.length}</span>
              )}
            </button>
            <button
              type="button"
              onClick={createSession}
              aria-label="New conversation"
              title="New conversation"
              className="rounded-lg p-2 text-muted hover:bg-paper hover:text-ink md:hidden"
            >
              <Plus className="h-4 w-4" aria-hidden />
            </button>
            <Link
              href="/admin"
              className="rounded-lg border border-line px-3 py-1.5 text-sm font-medium text-ink hover:border-tide-700 hover:text-tide-800"
            >
              Admin
            </Link>
          </div>
        </header>

        {sessions.length > 1 && (
          <div className="border-b border-line bg-card px-4 py-2 md:hidden">
            <label htmlFor="session-picker" className="sr-only">Conversation</label>
            <select
              id="session-picker"
              value={activeSessionId ?? ""}
              onChange={(e) => selectSession(e.target.value)}
              className="w-full rounded-md border border-line bg-paper px-2 py-1.5 text-sm"
            >
              {sessions.map((session) => <option key={session.id} value={session.id}>{session.title}</option>)}
            </select>
          </div>
        )}

        <div className="flex min-h-0 flex-1">
          <main className="flex-1 overflow-y-auto">
            {!activeSession ? (
              <div className="flex h-full items-center justify-center px-6 text-center text-sm text-muted">
                Pick a conversation or start a new one.
              </div>
            ) : (
              <div role="log" aria-live="polite" aria-label="Conversation" className="mx-auto max-w-2xl space-y-4 px-4 py-6">
                {activeMessages.map((msg) => (
                  <ChatBubble
                    key={msg.id}
                    message={msg}
                    isLoading={activeIsLoading && msg.content === "" && msg.role === "assistant"}
                  />
                ))}
                {showExamples && (
                  <div className="pl-11">
                    <p className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">Try one of the demo orders</p>
                    <div className="flex flex-wrap gap-2">
                      {EXAMPLES.map((example) => (
                        <button
                          key={example}
                          type="button"
                          onClick={() => sendMessage(example)}
                          className="rounded-full border border-line bg-card px-3 py-1.5 text-sm hover:border-tide-700 hover:text-tide-800"
                        >
                          {example}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                <div ref={scrollRef} />
              </div>
            )}
          </main>

          {showLogs && <ReasoningPanel logs={activeLogs} onClose={() => setShowLogs(false)} />}
        </div>

        <form
          onSubmit={(e) => { e.preventDefault(); sendMessage(input, activeSessionId ?? undefined); }}
          className="shrink-0 border-t border-line bg-card px-4 pb-4 pt-3"
        >
          <div
            className={cn(
              "mx-auto flex max-w-2xl items-end gap-2 rounded-xl border border-line bg-paper px-3 py-2 focus-within:border-tide-700",
              (!activeSession || activeIsLoading) && "opacity-70"
            )}
          >
            <label htmlFor="chat-input" className="sr-only">Message</label>
            <textarea
              id="chat-input"
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Order number and what went wrong…"
              className="max-h-28 min-h-[40px] flex-1 resize-none bg-transparent py-2 text-[15px] leading-relaxed placeholder:text-muted focus:outline-none"
              rows={1}
              maxLength={2000}
              disabled={activeIsLoading || !activeSession}
            />
            <VoiceInput onTranscript={handleVoiceTranscript} disabled={activeIsLoading || !activeSession} />
            <button
              type="submit"
              disabled={!canSend}
              aria-label="Send message"
              className={cn(
                "rounded-lg p-2.5 transition-colors",
                canSend ? "bg-tide-700 text-card hover:bg-tide-800" : "cursor-not-allowed bg-line text-muted"
              )}
            >
              {activeIsLoading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Send className="h-4 w-4" aria-hidden />}
            </button>
          </div>
          <p className="mx-auto mt-1.5 hidden max-w-2xl text-xs text-muted sm:block">
            Enter to send, Shift+Enter for a new line. The microphone transcribes speech into the box.
          </p>
        </form>
      </div>
    </div>
  );
}

function ChatBubble({ message, isLoading }: { message: Message; isLoading: boolean }) {
  const isUser = message.role === "user";
  const time = message.timestamp.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });

  return (
    <div className={cn("flex items-start gap-3 animate-slide-up", isUser && "flex-row-reverse")}>
      <span
        aria-hidden
        className={cn(
          "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full font-display text-sm font-semibold",
          isUser ? "bg-line text-ink" : "bg-tide-700 text-card"
        )}
      >
        {isUser ? "Y" : "A"}
      </span>
      <div className={cn("flex max-w-[85%] flex-col gap-1 sm:max-w-[75%]", isUser ? "items-end" : "items-start")}>
        <span className="sr-only">{isUser ? "You said" : "Aria said"}</span>
        <div
          className={cn(
            "rounded-2xl px-4 py-3 text-[15px] leading-relaxed",
            isUser ? "rounded-tr-sm bg-tide-700 text-card" : "rounded-tl-sm border border-line bg-card"
          )}
        >
          {isLoading ? (
            <span className="flex gap-1.5 py-1" role="status" aria-label="Aria is checking the order">
              <span className="typing-dot" />
              <span className="typing-dot" />
              <span className="typing-dot" />
            </span>
          ) : (
            <MarkdownText text={message.content} inverted={isUser} />
          )}
        </div>
        <time className="px-1 text-[11px] text-muted">{time}</time>
      </div>
    </div>
  );
}
