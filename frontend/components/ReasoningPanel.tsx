"use client";

import { useEffect, useRef } from "react";
import { X } from "lucide-react";
import { type AgentLog } from "@/lib/api";
import { cn } from "@/lib/utils";
import { DecisionStamp } from "@/components/DecisionStamp";

interface Props {
  logs: AgentLog[];
  onClose: () => void;
}

const STEP_LABEL: Record<AgentLog["type"], string> = {
  reasoning: "Model",
  tool_call: "Tool call",
  tool_result: "Result",
  decision: "Decision",
};

function formatTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

function preview(value: unknown): string {
  const text = JSON.stringify(value);
  return text.length > 220 ? `${text.slice(0, 220)}…` : text;
}

export function ReasoningPanel({ logs, onClose }: Props) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [logs]);

  return (
    <aside
      aria-label="Agent reasoning trace"
      className="fixed inset-0 z-30 flex flex-col bg-card animate-fade-in md:static md:inset-auto md:z-auto md:w-96 md:shrink-0 md:border-l md:border-line"
    >
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <div>
          <h2 className="font-display text-base font-semibold">How Aria decided</h2>
          <p className="text-xs text-muted">Every model step and tool call for this turn</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close reasoning trace"
          className="rounded-md p-2 text-muted hover:bg-paper hover:text-ink"
        >
          <X className="h-4 w-4" aria-hidden />
        </button>
      </div>

      <ol className="flex-1 overflow-y-auto px-4 py-3">
        {logs.length === 0 ? (
          <li className="py-10 text-center text-sm text-muted">
            Send a message to see the lookup, policy check and decision step by step.
          </li>
        ) : (
          logs.map((log, i) => (
            <li key={i} className="relative border-l-2 border-line pb-4 pl-4 last:pb-1">
              <span
                aria-hidden
                className={cn(
                  "absolute -left-[5px] top-1.5 h-2 w-2 rounded-full",
                  log.type === "decision" ? "bg-tide-700" : log.type === "tool_result" ? "bg-approve" : "bg-line"
                )}
              />
              <div className="flex items-baseline justify-between gap-2">
                <p className="text-xs font-semibold uppercase tracking-wider text-muted">
                  {STEP_LABEL[log.type] ?? log.type}
                  {log.tool && <span className="ml-1.5 font-mono normal-case tracking-normal text-ink">{log.tool}</span>}
                </p>
                <time className="font-mono text-[11px] text-muted">{formatTime(log.timestamp)}</time>
              </div>
              {log.type === "decision" && log.decision && <DecisionStamp decision={log.decision} className="mt-1.5" />}
              {log.type === "reasoning" && <p className="mt-1 text-sm text-ink/80">{log.content}</p>}
              {log.type === "tool_call" && log.args && (
                <pre className="mt-1.5 whitespace-pre-wrap break-all rounded-md bg-paper px-2 py-1.5 font-mono text-[11px] text-ink/80">
                  {preview(log.args)}
                </pre>
              )}
              {log.type === "tool_result" && log.result != null && (
                <pre className="mt-1.5 whitespace-pre-wrap break-all rounded-md bg-paper px-2 py-1.5 font-mono text-[11px] text-ink/80">
                  {preview(log.result)}
                </pre>
              )}
            </li>
          ))
        )}
        <div ref={endRef} />
      </ol>
    </aside>
  );
}
