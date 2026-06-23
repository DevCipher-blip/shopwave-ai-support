import { cn } from "@/lib/utils";

const STAMPS: Record<string, { label: string; className: string }> = {
  approve: { label: "Approved", className: "border-approve text-approve bg-approve-soft" },
  deny: { label: "Denied", className: "border-deny text-deny bg-deny-soft" },
  escalate: { label: "Escalated", className: "border-escalate text-escalate bg-escalate-soft" },
  informational: { label: "Info", className: "border-tide-700 text-tide-700 bg-tide-50" },
  error: { label: "Error", className: "border-deny text-deny bg-card" },
  pending: { label: "Open", className: "border-muted text-muted bg-card" },
};

export function DecisionStamp({ decision, className }: { decision: string | null | undefined; className?: string }) {
  const stamp = STAMPS[decision ?? "pending"] ?? STAMPS.pending;
  return <span className={cn("stamp", stamp.className, className)}>{stamp.label}</span>;
}
