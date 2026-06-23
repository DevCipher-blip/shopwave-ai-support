"use client";

import { useEffect, useState, useRef } from "react";
import Link from "next/link";
import {
  ArrowLeft, RefreshCw, CheckCircle, XCircle, AlertTriangle,
  Clock, Users, DollarSign, TrendingUp, Activity,
} from "lucide-react";
import {
  fetchStats, fetchSessions, subscribeAdminStream,
  type AdminStats, type SessionSummary, type AgentLog,
} from "@/lib/api";
import { cn, formatCurrency, formatDate } from "@/lib/utils";

// ── Live log item ─────────────────────────────────────────────────────────────

function LiveLogItem({ log }: { log: AgentLog & { session_id?: string } }) {
  const cfg: Record<string, { dot: string; label: string; text: string }> = {
    reasoning:   { dot: "bg-violet-400", label: "THINK",    text: "text-violet-700"  },
    tool_call:   { dot: "bg-amber-400",  label: "TOOL",     text: "text-amber-700"   },
    tool_result: { dot: "bg-emerald-400",label: "RESULT",   text: "text-emerald-700" },
    decision:    { dot: "bg-blue-400",   label: "DECISION", text: "text-blue-700"    },
  };
  const c = cfg[log.type] ?? { dot: "bg-slate-400", label: log.type.toUpperCase(), text: "text-slate-600" };

  return (
    <div className="flex gap-2.5 py-1.5 border-b border-slate-100 last:border-0 text-xs">
      <span className="text-slate-400 font-mono shrink-0 mt-0.5 tabular-nums">
        {new Date().toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" })}
      </span>
      <div className="flex items-center gap-1 shrink-0 mt-0.5">
        <span className={cn("w-1.5 h-1.5 rounded-full", c.dot)} />
        <span className={cn("font-bold text-[10px] w-[56px]", c.text)}>{c.label}</span>
      </div>
      {log.session_id && (
        <span className="text-slate-300 font-mono text-[10px] mt-0.5 hidden xl:block shrink-0">
          {log.session_id.slice(0, 8)}
        </span>
      )}
      <span className="text-slate-600 break-all leading-relaxed">{log.content}</span>
    </div>
  );
}

// ── Stat card ─────────────────────────────────────────────────────────────────

function StatCard({ label, value, icon: Icon, color, bg, sub }: {
  label: string;
  value: string | number;
  icon: React.ComponentType<{ className?: string }>;
  color: string;
  bg: string;
  sub?: string;
}) {
  return (
    <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-5">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">{label}</p>
          <p className="text-2xl font-bold text-slate-900 mt-1 tabular-nums">{value}</p>
          {sub && <p className="text-xs text-slate-400 mt-0.5">{sub}</p>}
        </div>
        <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center", bg)}>
          <Icon className={cn("w-5 h-5", color)} />
        </div>
      </div>
    </div>
  );
}

// ── Outcome badge ─────────────────────────────────────────────────────────────

function OutcomeBadge({ outcome }: { outcome: string | null }) {
  const config: Record<string, { label: string; className: string; Icon: React.ComponentType<{ className?: string }> }> = {
    approve:  { label: "Approved",  className: "bg-emerald-50 text-emerald-700 border-emerald-200", Icon: CheckCircle   },
    deny:     { label: "Denied",    className: "bg-red-50 text-red-700 border-red-200",             Icon: XCircle       },
    escalate: { label: "Escalated", className: "bg-amber-50 text-amber-700 border-amber-200",       Icon: AlertTriangle },
    pending:  { label: "Pending",   className: "bg-slate-50 text-slate-600 border-slate-200",       Icon: Clock         },
  };
  const cfg = config[outcome ?? "pending"] ?? config.pending;
  return (
    <span className={cn("inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium border", cfg.className)}>
      <cfg.Icon className="w-3 h-3" />
      {cfg.label}
    </span>
  );
}

// ── Session row ───────────────────────────────────────────────────────────────

function SessionRow({ session }: { session: SessionSummary }) {
  return (
    <tr className="border-b border-slate-100 hover:bg-slate-50 transition-colors text-sm">
      <td className="px-4 py-3 font-mono text-xs text-slate-400">{session.session_id.slice(0, 12)}…</td>
      <td className="px-4 py-3 text-slate-700">{session.customer_id ?? <span className="text-slate-300">—</span>}</td>
      <td className="px-4 py-3 text-slate-500 text-xs">{formatDate(session.started_at)}</td>
      <td className="px-4 py-3"><OutcomeBadge outcome={session.outcome} /></td>
      <td className="px-4 py-3">
        {session.refund_amount != null
          ? <span className="text-emerald-600 font-semibold">{formatCurrency(session.refund_amount)}</span>
          : <span className="text-slate-300">—</span>}
      </td>
    </tr>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function AdminPage() {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [liveLogs, setLiveLogs] = useState<(AgentLog & { session_id?: string })[]>([]);
  const [loading, setLoading] = useState(true);
  const [autoScroll, setAutoScroll] = useState(true);
  const logScrollRef = useRef<HTMLDivElement>(null);

  const loadData = async () => {
    setLoading(true);
    const [s, sess] = await Promise.all([fetchStats(), fetchSessions(30)]);
    setStats(s);
    setSessions(sess);
    setLoading(false);
  };

  useEffect(() => {
    loadData();
    const es = subscribeAdminStream((log) => {
      setLiveLogs((prev) => [...prev.slice(-199), log]);
    });
    return () => es.close();
  }, []);

  useEffect(() => {
    if (autoScroll && logScrollRef.current) {
      logScrollRef.current.scrollTop = logScrollRef.current.scrollHeight;
    }
  }, [liveLogs, autoScroll]);

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <header className="bg-white border-b border-slate-200 px-6 h-14 flex items-center justify-between sticky top-0 z-10">
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-500 hover:text-slate-900 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div className="w-px h-5 bg-slate-200" />
          <div>
            <h1 className="font-semibold text-slate-900 text-sm">Admin Dashboard</h1>
            <p className="text-xs text-slate-500">Real-time agent monitoring</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-50 border border-emerald-200 rounded-lg">
            <span className="w-2 h-2 bg-emerald-500 rounded-full animate-pulse" />
            <span className="text-xs text-emerald-700 font-medium">Live</span>
          </div>
          <button
            onClick={loadData}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-white border border-slate-200 hover:bg-slate-50 rounded-lg text-slate-600 font-medium transition-colors"
          >
            <RefreshCw className={cn("w-3.5 h-3.5", loading && "animate-spin")} />
            Refresh
          </button>
        </div>
      </header>

      <main className="max-w-7xl mx-auto p-6 space-y-6">
        {/* Stats */}
        {stats && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <StatCard label="Total Sessions"  value={stats.total_sessions}              icon={Activity}   color="text-blue-600"   bg="bg-blue-50" />
            <StatCard label="Approval Rate"   value={`${stats.approval_rate}%`}         icon={TrendingUp} color="text-emerald-600" bg="bg-emerald-50" sub={`${stats.approved} approved`} />
            <StatCard label="Total Refunded"  value={formatCurrency(stats.total_refunded)} icon={DollarSign} color="text-violet-600"  bg="bg-violet-50" />
            <StatCard label="Customers"       value={stats.customer_count}               icon={Users}      color="text-amber-600"  bg="bg-amber-50" />
          </div>
        )}

        {/* Outcome breakdown */}
        {stats && (
          <div className="grid grid-cols-3 gap-4">
            {[
              { label: "Approved",  value: stats.approved,  color: "text-emerald-700", bg: "bg-emerald-50 border-emerald-200", Icon: CheckCircle   },
              { label: "Denied",    value: stats.denied,    color: "text-red-700",     bg: "bg-red-50 border-red-200",         Icon: XCircle       },
              { label: "Escalated", value: stats.escalated, color: "text-amber-700",   bg: "bg-amber-50 border-amber-200",     Icon: AlertTriangle },
            ].map(({ label, value, color, bg, Icon }) => (
              <div key={label} className={cn("rounded-2xl border p-5 flex items-center gap-4", bg)}>
                <div className="w-10 h-10 rounded-xl bg-white/70 flex items-center justify-center">
                  <Icon className={cn("w-5 h-5", color)} />
                </div>
                <div>
                  <p className={cn("text-3xl font-bold tabular-nums", color)}>{value}</p>
                  <p className="text-sm text-slate-500 mt-0.5">{label}</p>
                </div>
                {stats.total_sessions > 0 && (
                  <p className={cn("ml-auto text-lg font-semibold", color)}>
                    {Math.round(value / stats.total_sessions * 100)}%
                  </p>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Live logs + sessions table */}
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          {/* Live log */}
          <div className="bg-white border border-slate-200 rounded-2xl shadow-sm flex flex-col" style={{ height: 420 }}>
            <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100 shrink-0">
              <div className="flex items-center gap-2">
                <Activity className="w-4 h-4 text-blue-500" />
                <span className="text-sm font-semibold text-slate-800">Live Agent Logs</span>
                <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-pulse" />
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-400">{liveLogs.length} events</span>
                <button
                  onClick={() => setAutoScroll((v) => !v)}
                  className={cn(
                    "px-2 py-0.5 rounded-md text-xs font-medium transition-colors",
                    autoScroll ? "bg-blue-100 text-blue-600" : "bg-slate-100 text-slate-500"
                  )}
                >
                  Auto-scroll {autoScroll ? "on" : "off"}
                </button>
                <button
                  onClick={() => setLiveLogs([])}
                  className="text-xs text-slate-400 hover:text-slate-600 transition-colors"
                >
                  Clear
                </button>
              </div>
            </div>
            <div ref={logScrollRef} className="flex-1 overflow-y-auto px-4 py-2">
              {liveLogs.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full text-center">
                  <Activity className="w-8 h-8 text-slate-200 mb-2" />
                  <p className="text-xs text-slate-400">
                    Waiting for agent activity…<br />
                    Start a chat to see real-time reasoning logs.
                  </p>
                </div>
              ) : (
                liveLogs.map((log, i) => <LiveLogItem key={i} log={log} />)
              )}
            </div>
          </div>

          {/* Recent sessions */}
          <div className="bg-white border border-slate-200 rounded-2xl shadow-sm flex flex-col" style={{ height: 420 }}>
            <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100 shrink-0">
              <div className="flex items-center gap-2">
                <Clock className="w-4 h-4 text-blue-500" />
                <span className="text-sm font-semibold text-slate-800">Recent Sessions</span>
              </div>
              <span className="text-xs text-slate-400">{sessions.length} sessions</span>
            </div>
            <div className="flex-1 overflow-y-auto">
              {sessions.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full">
                  <Clock className="w-8 h-8 text-slate-200 mb-2" />
                  <p className="text-xs text-slate-400">No sessions yet.</p>
                </div>
              ) : (
                <table className="w-full">
                  <thead className="sticky top-0 bg-white z-10 border-b border-slate-100">
                    <tr className="text-[10px] text-slate-400 font-semibold uppercase tracking-widest">
                      <th className="px-4 py-2.5 text-left">Session</th>
                      <th className="px-4 py-2.5 text-left">Customer</th>
                      <th className="px-4 py-2.5 text-left">Time</th>
                      <th className="px-4 py-2.5 text-left">Outcome</th>
                      <th className="px-4 py-2.5 text-left">Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sessions.map((s) => <SessionRow key={s.session_id} session={s} />)}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

// ── Live log feed item ────────────────────────────────────────────────────────
