"use client";

import { useRef, useEffect } from "react";
import { X, Cpu, Wrench, CheckCircle2, Zap } from "lucide-react";
import { type AgentLog } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Props {
  logs: AgentLog[];
  onClose: () => void;
}

const EVENT_CONFIG = {
  reasoning:   { icon: Cpu,           color: "text-violet-600", bg: "bg-violet-50 border-violet-200",   label: "Thinking" },
  tool_call:   { icon: Wrench,        color: "text-amber-600",  bg: "bg-amber-50 border-amber-200",     label: "Tool Call" },
  tool_result: { icon: CheckCircle2,  color: "text-emerald-600",bg: "bg-emerald-50 border-emerald-200", label: "Result" },
  decision:    { icon: Zap,           color: "text-blue-600",   bg: "bg-blue-50 border-blue-200",       label: "Decision" },
} as const;

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString("en-US", {
      hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
    });
  } catch { return ""; }
}

function DecisionBadge({ decision }: { decision: string }) {
  const styles: Record<string, string> = {
    approve:       "bg-emerald-100 text-emerald-700 border-emerald-200",
    deny:          "bg-red-100 text-red-700 border-red-200",
    escalate:      "bg-amber-100 text-amber-700 border-amber-200",
    informational: "bg-blue-100 text-blue-700 border-blue-200",
    pending:       "bg-slate-100 text-slate-600 border-slate-200",
  };
  return (
    <span className={cn(
      "inline-flex px-2 py-0.5 rounded-full text-[10px] font-bold border uppercase tracking-widest",
      styles[decision] ?? styles.pending
    )}>
      {decision}
    </span>
  );
}

export function ReasoningPanel({ logs, onClose }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  useEffect(() => { scrollRef.current?.scrollIntoView({ behavior: "smooth" }); }, [logs]);

  return (
    <aside className="w-80 border-l border-slate-200 bg-white flex flex-col overflow-hidden animate-fade-in shrink-0">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 shrink-0">
        <div className="flex items-center gap-2">
          <Cpu className="w-4 h-4 text-violet-500" />
          <span className="text-sm font-semibold text-slate-800">Agent Reasoning</span>
          {logs.length > 0 && (
            <span className="text-xs text-slate-500 bg-slate-100 px-1.5 py-0.5 rounded-full font-medium">
              {logs.length}
            </span>
          )}
        </div>
        <button
          onClick={onClose}
          className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-700 transition-colors"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Log entries */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {logs.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 text-center">
            <Cpu className="w-8 h-8 text-slate-200 mb-2" />
            <p className="text-xs text-slate-400">Agent reasoning steps will appear here.</p>
          </div>
        ) : (
          logs.map((log, i) => {
            const cfg = EVENT_CONFIG[log.type] ?? EVENT_CONFIG.reasoning;
            const Icon = cfg.icon;
            return (
              <div key={i} className={cn("rounded-xl border p-3 space-y-2 animate-slide-up", cfg.bg)}>
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-1.5">
                    <Icon className={cn("w-3.5 h-3.5 shrink-0", cfg.color)} />
                    <span className={cn("text-[10px] font-bold uppercase tracking-widest", cfg.color)}>
                      {cfg.label}
                    </span>
                    {log.tool && (
                      <span className="text-[10px] font-mono bg-white border border-slate-200 text-slate-600 px-1.5 py-0.5 rounded">
                        {log.tool}
                      </span>
                    )}
                  </div>
                  <span className="text-[10px] text-slate-400 font-mono shrink-0">
                    {formatTime(log.timestamp)}
                  </span>
                </div>

                {log.type === "decision" && log.decision && (
                  <DecisionBadge decision={log.decision} />
                )}

                {log.content && (
                  <p className="text-[11px] text-slate-600 leading-relaxed">
                    {log.content.length > 140 ? `${log.content.slice(0, 140)}…` : log.content}
                  </p>
                )}

                {log.type === "tool_call" && log.args && (
                  <div className="bg-white/70 border border-slate-200 rounded-lg p-2 font-mono text-[10px] text-slate-500 break-all">
                    {JSON.stringify(log.args, null, 0).substring(0, 180)}
                  </div>
                )}

                {log.type === "tool_result" && log.result != null && (
                  <div className="bg-white/70 border border-slate-200 rounded-lg p-2 font-mono text-[10px] text-slate-500 break-all">
                    {JSON.stringify(log.result).substring(0, 180)}
                  </div>
                )}
              </div>
            );
          })
        )}
        <div ref={scrollRef} />
      </div>
    </aside>
  );
}
