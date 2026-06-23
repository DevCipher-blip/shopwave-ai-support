"use client";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { ArrowLeft, LogOut, RefreshCw } from "lucide-react";
import {
  ApiError, fetchSessions, fetchStats, subscribeAdminStream,
  type AdminStats, type AgentLog, type SessionSummary,
} from "@/lib/api";
import { cn, formatCurrency, formatDate } from "@/lib/utils";
import { DecisionStamp } from "@/components/DecisionStamp";

interface Dashboard {
  stats: AdminStats;
  sessions: SessionSummary[];
}

type LiveLog = AgentLog & { session_id?: string };

async function loadDashboard(token: string): Promise<Dashboard> {
  const [stats, sessions] = await Promise.all([fetchStats(token), fetchSessions(token, 30)]);
  return { stats, sessions };
}

const TOKEN_KEY = "shopwave-admin-token";
const TOKEN_EVENT = "shopwave-admin-token-change";

function subscribeToken(onChange: () => void) {
  window.addEventListener(TOKEN_EVENT, onChange);
  return () => window.removeEventListener(TOKEN_EVENT, onChange);
}

function storeToken(token: string | null) {
  if (token) window.sessionStorage.setItem(TOKEN_KEY, token);
  else window.sessionStorage.removeItem(TOKEN_KEY);
  window.dispatchEvent(new Event(TOKEN_EVENT));
}

function useAdminToken(): string | null {
  return useSyncExternalStore(subscribeToken, () => window.sessionStorage.getItem(TOKEN_KEY), () => null);
}

function TokenForm({ error, onSubmit }: { error: string | null; onSubmit: (token: string) => void }) {
  const [value, setValue] = useState("");
  return (
    <main className="flex min-h-screen items-center justify-center bg-paper px-4">
      <form
        onSubmit={(e) => { e.preventDefault(); if (value.trim()) onSubmit(value.trim()); }}
        className="w-full max-w-sm space-y-4 rounded-xl border border-line bg-card p-6"
      >
        <div>
          <h1 className="font-display text-xl font-semibold">Returns desk admin</h1>
          <p className="mt-1 text-sm text-muted">Enter the ADMIN_TOKEN configured on the API.</p>
        </div>
        <div>
          <label htmlFor="admin-token" className="text-sm font-medium">Admin token</label>
          <input
            id="admin-token"
            type="password"
            autoComplete="current-password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className="mt-1 w-full rounded-lg border border-line bg-paper px-3 py-2 focus:border-tide-700 focus:outline-none"
          />
        </div>
        {error && <p role="alert" className="text-sm text-deny">{error}</p>}
        <button type="submit" className="w-full rounded-lg bg-tide-700 py-2 text-sm font-medium text-card hover:bg-tide-800">
          Open dashboard
        </button>
        <Link href="/" className="block text-center text-sm text-muted underline-offset-2 hover:underline">
          Back to the chat
        </Link>
      </form>
    </main>
  );
}

function Figure({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="px-5 py-4">
      <p className="text-xs font-medium uppercase tracking-wider text-muted">{label}</p>
      <p className="mt-1 font-display text-3xl font-semibold tabular-nums">{value}</p>
      {note && <p className="text-xs text-muted">{note}</p>}
    </div>
  );
}

function OutcomeSplit({ stats }: { stats: AdminStats }) {
  const parts = [
    { key: "approve", label: "Approved", value: stats.approved, bar: "bg-approve" },
    { key: "deny", label: "Denied", value: stats.denied, bar: "bg-deny" },
    { key: "escalate", label: "Escalated", value: stats.escalated, bar: "bg-escalate" },
    { key: "pending", label: "Open", value: stats.pending, bar: "bg-line" },
  ];
  const total = Math.max(stats.total_sessions, 1);
  return (
    <section aria-labelledby="split-heading" className="rounded-xl border border-line bg-card p-5">
      <h2 id="split-heading" className="font-display text-base font-semibold">Outcomes</h2>
      <div className="mt-3 flex h-3 overflow-hidden rounded-full bg-paper" aria-hidden>
        {parts.map((p) => p.value > 0 && (
          <div key={p.key} className={p.bar} style={{ width: `${(p.value / total) * 100}%` }} />
        ))}
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4">
        {parts.map((p) => (
          <div key={p.key} className="flex items-center gap-2">
            <span aria-hidden className={cn("h-2.5 w-2.5 rounded-sm", p.bar)} />
            <dt className="text-muted">{p.label}</dt>
            <dd className="ml-auto font-mono tabular-nums sm:ml-0">{p.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

const FEED_LABEL: Record<string, string> = {
  reasoning: "model",
  tool_call: "call",
  tool_result: "result",
  decision: "decision",
};

function FeedItem({ log }: { log: LiveLog }) {
  const time = new Date(log.timestamp).toLocaleTimeString("en-US", { hour12: false });
  return (
    <li className="grid grid-cols-[4.5rem_4.5rem_1fr] gap-2 border-b border-line/70 py-1.5 font-mono text-xs last:border-0">
      <time className="text-muted">{time}</time>
      <span className={cn(log.type === "decision" ? "text-tide-700" : "text-muted")}>{FEED_LABEL[log.type] ?? log.type}</span>
      <span className="min-w-0 text-ink/90 [overflow-wrap:anywhere]">
        {log.session_id && <span className="mr-1.5 text-muted">{log.session_id.slice(0, 8)}</span>}
        {log.type === "decision" && log.decision
          ? <DecisionStamp decision={log.decision} />
          : log.content.length > 140 ? `${log.content.slice(0, 140)}…` : log.content}
      </span>
    </li>
  );
}

export default function AdminPage() {
  const token = useAdminToken();
  const [authError, setAuthError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [liveLogs, setLiveLogs] = useState<LiveLog[]>([]);
  const [loading, setLoading] = useState(true);
  const feedRef = useRef<HTMLOListElement>(null);

  const signOut = useCallback((message: string | null) => {
    setAuthError(message);
    setDashboard(null);
    storeToken(null);
  }, []);

  const applyDashboard = useCallback((data: Dashboard) => {
    setDashboard(data);
    setLoadError(null);
  }, []);

  const handleLoadError = useCallback((err: unknown) => {
    if (err instanceof ApiError && err.status === 401) signOut("That token was rejected.");
    else if (err instanceof ApiError && err.status === 503) signOut("Admin access is disabled on the server (ADMIN_TOKEN is not set).");
    else setLoadError("Couldn't reach the API. Check that the backend is running, then refresh.");
  }, [signOut]);

  const refresh = () => {
    if (!token) return;
    setLoading(true);
    loadDashboard(token).then(applyDashboard, handleLoadError).finally(() => setLoading(false));
  };

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    loadDashboard(token)
      .then((data) => { if (!cancelled) applyDashboard(data); }, handleLoadError)
      .finally(() => { if (!cancelled) setLoading(false); });
    const close = subscribeAdminStream(
      token,
      (log) => setLiveLogs((prev) => [...prev.slice(-199), log]),
      () => undefined,
    );
    return () => {
      cancelled = true;
      close();
    };
  }, [token, applyDashboard, handleLoadError]);

  useEffect(() => {
    feedRef.current?.lastElementChild?.scrollIntoView({ block: "nearest" });
  }, [liveLogs]);

  if (!token) {
    return (
      <TokenForm
        error={authError}
        onSubmit={(value) => {
          setAuthError(null);
          storeToken(value);
        }}
      />
    );
  }

  const stats = dashboard?.stats;
  const sessions = dashboard?.sessions ?? [];

  return (
    <div className="min-h-screen bg-paper">
      <header className="sticky top-0 z-10 border-b border-line bg-card">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-3 md:px-6">
          <div className="flex items-center gap-3">
            <Link href="/" aria-label="Back to the chat" className="rounded-md p-1.5 text-muted hover:bg-paper hover:text-ink">
              <ArrowLeft className="h-4 w-4" aria-hidden />
            </Link>
            <div>
              <h1 className="font-display text-lg font-semibold leading-tight">Returns desk ledger</h1>
              <p className="text-xs text-muted">Every decision Aria recorded, live</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={refresh}
              className="flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-sm hover:border-tide-700"
            >
              <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} aria-hidden />
              Refresh
            </button>
            <button
              type="button"
              onClick={() => signOut(null)}
              aria-label="Sign out"
              title="Sign out"
              className="rounded-lg p-2 text-muted hover:bg-paper hover:text-ink"
            >
              <LogOut className="h-4 w-4" aria-hidden />
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl space-y-6 px-4 py-6 md:px-6">
        {loadError && (
          <p role="alert" className="rounded-lg border border-deny/40 bg-deny-soft px-4 py-3 text-sm text-deny">{loadError}</p>
        )}

        {stats ? (
          <section
            aria-label="Totals"
            className="grid grid-cols-2 divide-line rounded-xl border border-line bg-card md:grid-cols-4 md:divide-x [&>*:nth-child(-n+2)]:border-b [&>*:nth-child(-n+2)]:border-line md:[&>*:nth-child(-n+2)]:border-b-0"
          >
            <Figure label="Conversations" value={String(stats.total_sessions)} />
            <Figure label="Approval rate" value={`${stats.approval_rate}%`} note={`${stats.approved} approved`} />
            <Figure label="Total refunded" value={formatCurrency(stats.total_refunded)} />
            <Figure label="Customers on file" value={String(stats.customer_count)} />
          </section>
        ) : (
          !loadError && <div className="h-28 animate-pulse rounded-xl border border-line bg-card" aria-label="Loading totals" />
        )}

        {stats && <OutcomeSplit stats={stats} />}

        <div className="grid gap-6 lg:grid-cols-5">
          <section aria-labelledby="sessions-heading" className="rounded-xl border border-line bg-card lg:col-span-3">
            <div className="flex items-baseline justify-between px-5 pb-2 pt-4">
              <h2 id="sessions-heading" className="font-display text-base font-semibold">Recent conversations</h2>
              <span className="text-xs text-muted">{sessions.length} shown</span>
            </div>
            {sessions.length === 0 ? (
              <p className="px-5 pb-6 pt-2 text-sm text-muted">No conversations yet. Decisions appear here as customers chat.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-y border-line text-left text-xs uppercase tracking-wider text-muted">
                      <th scope="col" className="px-5 py-2 font-medium">Session</th>
                      <th scope="col" className="px-3 py-2 font-medium">Customer</th>
                      <th scope="col" className="px-3 py-2 font-medium">Started</th>
                      <th scope="col" className="px-3 py-2 font-medium">Outcome</th>
                      <th scope="col" className="px-5 py-2 text-right font-medium">Refund</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sessions.map((s) => (
                      <tr key={s.session_id} className="border-b border-line/70 last:border-0">
                        <td className="px-5 py-2.5 font-mono text-xs text-muted">{s.session_id.slice(0, 8)}</td>
                        <td className="px-3 py-2.5 font-mono text-xs">{s.customer_id ?? "—"}</td>
                        <td className="whitespace-nowrap px-3 py-2.5 text-xs text-muted">{formatDate(s.started_at)}</td>
                        <td className="px-3 py-2.5"><DecisionStamp decision={s.outcome} /></td>
                        <td className="px-5 py-2.5 text-right font-mono tabular-nums">
                          {s.refund_amount != null ? formatCurrency(s.refund_amount) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section aria-labelledby="feed-heading" className="flex flex-col rounded-xl border border-line bg-card lg:col-span-2">
            <div className="flex items-baseline justify-between px-5 pb-2 pt-4">
              <h2 id="feed-heading" className="font-display text-base font-semibold">Live agent feed</h2>
              <button type="button" onClick={() => setLiveLogs([])} className="text-xs text-muted hover:text-ink">
                Clear
              </button>
            </div>
            <ol ref={feedRef} aria-live="polite" className="max-h-96 min-h-40 flex-1 overflow-y-auto border-t border-line px-5 py-2">
              {liveLogs.length === 0 ? (
                <li className="py-8 text-center text-sm text-muted">Waiting for activity. Start a chat to watch each step arrive.</li>
              ) : (
                liveLogs.map((log, i) => <FeedItem key={i} log={log} />)
              )}
            </ol>
          </section>
        </div>
      </main>
    </div>
  );
}
