"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import Link from "next/link";
import {
  Send, Volume2, VolumeX, LayoutDashboard,
  ShoppingBag, RefreshCw, Bot, User, Loader2, Plus, MessageSquare,
  Sparkles, Shield,
} from "lucide-react";
import {
  createChatSession,
  fetchChatMessages,
  streamChat,
  type AgentLog,
  type ChatMessage,
} from "@/lib/api";
import { cn, formatDate } from "@/lib/utils";
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

const WELCOME = `Hi! I'm **Aria**, your ShopWave AI support agent.

I can help you with **refund and return requests** for your orders.

To get started, please share:
- Your **order number** (e.g. ORD-10021) or **email address**
- The issue you're experiencing`;

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

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activeMessages]);

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
      if (!cancelled) setIsBootstrapping(false);
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

  useEffect(() => {
    if (!activeSessionId) return;
    const selectedSession = sessions.find((session) => session.id === activeSessionId);
    if (!selectedSession || selectedSession.messages !== null) return;
    loadSessionMessages(activeSessionId).catch(() => {
      setSessions((prev) => prev.filter((session) => session.id !== activeSessionId));
      if (activeSessionIdRef.current === activeSessionId) {
        setActiveSessionId((prev) => {
          const next = sessions.find((session) => session.id !== activeSessionId)?.id ?? null;
          return next !== activeSessionId ? next : null;
        });
      }
    });
  }, [activeSessionId, sessions, loadSessionMessages, updateSession]);

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
      id: crypto.randomUUID(),
      role: "user",
      content: trimmed,
      timestamp: new Date(),
    };
    setInput("");

    const assistantId = crypto.randomUUID();
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

  if (isBootstrapping) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center px-4">
        <div className="w-full max-w-sm rounded-3xl border border-slate-200 bg-white shadow-sm p-8 text-center">
          <div className="w-12 h-12 rounded-2xl bg-blue-600 flex items-center justify-center shadow-sm mx-auto">
            <Shield className="w-6 h-6 text-white" />
          </div>
          <p className="mt-4 text-sm text-slate-500">Starting session…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen bg-slate-50 overflow-hidden">

      {/* ── Sidebar ─────────────────────────────────────────────────── */}
      <aside className="hidden md:flex flex-col w-72 bg-white border-r border-slate-200 shrink-0">
        <div className="p-4 border-b border-slate-100">
          <div className="flex items-center gap-2.5 mb-4">
            <div className="w-9 h-9 rounded-xl bg-blue-600 flex items-center justify-center shadow-sm shrink-0">
              <ShoppingBag className="w-[18px] h-[18px] text-white" />
            </div>
            <div>
              <p className="font-semibold text-slate-900 text-sm leading-tight">ShopWave Support</p>
              <p className="text-xs text-slate-500">AI Refund &amp; Returns</p>
            </div>
          </div>
          <button
            onClick={createSession}
            className="w-full flex items-center justify-center gap-2 rounded-xl bg-blue-600 hover:bg-blue-700 active:scale-[.98] text-white text-sm font-medium px-4 py-2.5 transition-all shadow-sm"
          >
            <Plus className="w-4 h-4" />
            New conversation
          </button>
        </div>

        <div className="mx-3 mt-3 flex items-start gap-2 rounded-xl bg-blue-50 border border-blue-100 px-3 py-2.5">
          <Shield className="w-3.5 h-3.5 text-blue-500 shrink-0 mt-0.5" />
          <p className="text-xs text-blue-700 leading-relaxed">
            Aria handles ShopWave order support only — refunds, returns, and delivery queries.
          </p>
        </div>

        <div className="flex-1 overflow-y-auto px-2 py-3">
          {sessions.length > 0 && (
            <p className="px-2 mb-2 text-[10px] font-semibold text-slate-400 uppercase tracking-widest">
              Conversations
            </p>
          )}
          <div className="space-y-0.5">
            {sessions.map((session) => {
              const preview = session.messages?.find((m) => m.role === "assistant")?.content;
              const isActive = session.id === activeSessionId;
              return (
                <button
                  key={session.id}
                  onClick={() => setActiveSessionId(session.id)}
                  className={cn(
                    "w-full text-left rounded-xl px-3 py-2.5 transition-colors border",
                    isActive
                      ? "bg-blue-50 border-blue-200"
                      : "hover:bg-slate-50 border-transparent"
                  )}
                >
                  <div className="flex items-center justify-between gap-1 mb-0.5">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <MessageSquare className={cn("w-3.5 h-3.5 shrink-0", isActive ? "text-blue-500" : "text-slate-400")} />
                      <span className={cn("text-sm font-medium truncate", isActive ? "text-blue-700" : "text-slate-700")}>
                        {session.title}
                      </span>
                    </div>
                    {session.isLoading && <Loader2 className="w-3 h-3 animate-spin text-blue-500 shrink-0" />}
                  </div>
                  <p className="text-xs text-slate-400 pl-5 line-clamp-1">
                    {preview
                      ? preview.replace(/\*\*/g, "").slice(0, 70)
                      : formatDate(session.updatedAt)}
                  </p>
                </button>
              );
            })}
          </div>
        </div>
      </aside>

      {/* ── Main Chat ───────────────────────────────────────────────── */}
      <div className="flex flex-1 flex-col overflow-hidden min-w-0">

        {/* Header */}
        <header className="flex items-center justify-between h-14 px-5 bg-white border-b border-slate-200 shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center shadow-sm shrink-0">
              <Bot className="w-4 h-4 text-white" />
            </div>
            <div className="min-w-0">
              <h2 className="font-semibold text-slate-900 text-sm leading-tight truncate">
                {activeSession?.title ?? "ShopWave Support"}
              </h2>
              <div className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                <span className="text-xs text-slate-500">Aria · Online</span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-1 shrink-0">
            <button
              onClick={() => setTtsEnabled((v) => !v)}
              className={cn(
                "p-2 rounded-lg transition-colors",
                ttsEnabled ? "text-blue-600 hover:bg-blue-50" : "text-slate-400 hover:bg-slate-100"
              )}
              title={ttsEnabled ? "Mute voice" : "Enable voice"}
            >
              {ttsEnabled ? <Volume2 className="w-4 h-4" /> : <VolumeX className="w-4 h-4" />}
            </button>

            <button
              onClick={() => setShowLogs((v) => !v)}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors",
                showLogs ? "bg-violet-100 text-violet-700" : "text-slate-500 hover:bg-slate-100"
              )}
            >
              <Sparkles className="w-3.5 h-3.5" />
              Reasoning
              {activeLogs.length > 0 && (
                <span className="text-[10px] bg-violet-200 text-violet-700 px-1.5 rounded-full font-semibold">
                  {activeLogs.length}
                </span>
              )}
            </button>

            <button
              onClick={createSession}
              className="p-2 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors"
              title="New conversation"
            >
              <RefreshCw className="w-4 h-4" />
            </button>

            <Link
              href="/admin"
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-slate-500 hover:bg-slate-100 text-xs font-medium transition-colors border border-slate-200 hover:border-slate-300"
            >
              <LayoutDashboard className="w-3.5 h-3.5" />
              Admin
            </Link>

          </div>
        </header>

        {/* Messages + optional reasoning panel */}
        <div className="flex flex-1 overflow-hidden">
          <div className="flex-1 overflow-y-auto">
            {isBootstrapping ? (
              <div className="h-full flex flex-col items-center justify-center gap-3">
                <div className="w-12 h-12 rounded-2xl bg-blue-600 flex items-center justify-center shadow-sm">
                  <Bot className="w-6 h-6 text-white" />
                </div>
                <p className="text-sm text-slate-500">Starting conversation…</p>
              </div>
            ) : !activeSession ? (
              <div className="h-full flex items-center justify-center">
                <p className="text-sm text-slate-400">Select a conversation or start a new one.</p>
              </div>
            ) : (
              <div className="max-w-2xl mx-auto px-4 py-6 space-y-1">
                {activeMessages.map((msg, idx) => (
                  <ChatBubble
                    key={msg.id}
                    message={msg}
                    isLoading={activeIsLoading && msg.content === "" && msg.role === "assistant"}
                    showAvatar={idx === 0 || activeMessages[idx - 1]?.role !== msg.role}
                  />
                ))}
                <div ref={scrollRef} />
              </div>
            )}
          </div>

          {showLogs && (
            <ReasoningPanel logs={activeLogs} onClose={() => setShowLogs(false)} />
          )}
        </div>

        {/* Input */}
        <div className="bg-white border-t border-slate-200 px-4 pt-3 pb-4 shrink-0">
          <div
            className={cn(
              "flex items-end gap-3 bg-slate-50 border rounded-2xl px-4 py-3 transition-all duration-150",
              "border-slate-200 focus-within:border-blue-300 focus-within:ring-2 focus-within:ring-blue-50",
              (!activeSession || activeIsLoading) && "opacity-60"
            )}
          >
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="e.g. 'I received a defective item — order ORD-10021'"
              className="flex-1 bg-transparent text-slate-900 text-sm placeholder-slate-400 resize-none outline-none min-h-[36px] max-h-[100px] leading-relaxed"
              rows={1}
              disabled={activeIsLoading || !activeSession}
            />
            <div className="flex items-center gap-1.5 shrink-0 pb-px">
              <VoiceInput
                onTranscript={handleVoiceTranscript}
                disabled={activeIsLoading || !activeSession}
              />
              <button
                onClick={() => sendMessage(input, activeSessionId ?? undefined)}
                disabled={!input.trim() || activeIsLoading || !activeSession}
                className={cn(
                  "p-2 rounded-xl transition-all",
                  input.trim() && !activeIsLoading && activeSession
                    ? "bg-blue-600 text-white hover:bg-blue-700 shadow-sm active:scale-95"
                    : "bg-slate-200 text-slate-400 cursor-not-allowed"
                )}
              >
                {activeIsLoading
                  ? <Loader2 className="w-4 h-4 animate-spin" />
                  : <Send className="w-4 h-4" />}
              </button>
            </div>
          </div>
          <p className="text-xs text-slate-400 mt-1.5 text-center">
            Enter to send · Shift+Enter for new line · Use microphone for voice input
          </p>
        </div>
      </div>
    </div>
  );
}

// ── Chat Bubble ──────────────────────────────────────────────────────────────
function ChatBubble({
  message,
  isLoading,
  showAvatar,
}: {
  message: Message;
  isLoading: boolean;
  showAvatar: boolean;
}) {
  const isUser = message.role === "user";
  const time = message.timestamp?.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: true,
  });

  return (
    <div
      className={cn(
        "flex items-end gap-2.5 animate-slide-up",
        isUser ? "flex-row-reverse" : "flex-row",
        !showAvatar && (isUser ? "pr-[44px]" : "pl-[44px]")
      )}
    >
      {showAvatar && (
        <div
          className={cn(
            "w-8 h-8 rounded-full flex items-center justify-center shrink-0 shadow-sm",
            isUser ? "bg-slate-200" : "bg-blue-600"
          )}
        >
          {isUser
            ? <User className="w-4 h-4 text-slate-600" />
            : <Bot className="w-4 h-4 text-white" />}
        </div>
      )}

      <div className={cn("flex flex-col gap-1", isUser ? "items-end" : "items-start", "max-w-[75%]")}>
        <div
          className={cn(
            "px-4 py-3 rounded-2xl text-sm leading-relaxed",
            isUser
              ? "bg-blue-600 text-white rounded-br-sm shadow-sm"
              : "bg-white text-slate-800 rounded-bl-sm border border-slate-200 shadow-sm"
          )}
        >
          {isLoading ? (
            <span className="flex gap-1.5 py-0.5 px-1">
              <span className="typing-dot" />
              <span className="typing-dot" />
              <span className="typing-dot" />
            </span>
          ) : (
            <MarkdownText text={message.content} isUser={isUser} />
          )}
        </div>
        <span className="text-[10px] text-slate-400 px-1">{time}</span>
      </div>
    </div>
  );
}

// ── Markdown ──────────────────────────────────────────────────────────────────
function MarkdownText({ text, isUser }: { text: string; isUser: boolean }) {
  const lines = text.split("\n");
  return (
    <>
      {lines.map((line, i) => {
        const isList = /^[-•]\s/.test(line);
        const content = isList ? line.slice(2) : line;
        const parts = content.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
        const rendered = parts.map((part, j) => {
          if (part.startsWith("**") && part.endsWith("**"))
            return <strong key={j} className="font-semibold">{part.slice(2, -2)}</strong>;
          if (part.startsWith("`") && part.endsWith("`"))
            return (
              <code
                key={j}
                className={cn(
                  "px-1.5 py-0.5 rounded text-xs font-mono",
                  isUser ? "bg-blue-500/30" : "bg-slate-100 text-slate-700"
                )}
              >
                {part.slice(1, -1)}
              </code>
            );
          return <span key={j}>{part}</span>;
        });

        return (
          <span key={i} className={cn("block", isList && "flex gap-2 items-start")}>
            {isList && (
              <span className={cn("mt-2 w-1.5 h-1.5 rounded-full shrink-0 inline-block", isUser ? "bg-blue-300" : "bg-slate-400")} />
            )}
            <span className={isList ? undefined : "block"}>{rendered}</span>
          </span>
        );
      })}
    </>
  );
}
