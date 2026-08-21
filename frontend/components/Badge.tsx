import { prettyStatus } from "@/lib/format";
import type { ClaimStatus } from "@/lib/types";

const TONE: Record<string, string> = {
  DRAFT: "bg-slate-100 text-slate-700",
  SUBMITTED: "bg-sky-50 text-sky-800",
  PROCESSING: "bg-indigo-50 text-indigo-800",
  AI_ANALYZING: "bg-indigo-50 text-indigo-800",
  MARKET_RESEARCH: "bg-violet-50 text-violet-800",
  ESTIMATING: "bg-violet-50 text-violet-800",
  AI_COMPLETED: "bg-teal-50 text-teal-800",
  AGENT_REVIEW: "bg-amber-50 text-amber-800",
  MORE_INFORMATION_REQUIRED: "bg-orange-50 text-orange-800",
  APPROVED: "bg-emerald-50 text-emerald-800",
  REJECTED: "bg-rose-50 text-rose-800",
  SETTLEMENT_PROCESSING: "bg-emerald-50 text-emerald-800",
  COMPLETED: "bg-emerald-100 text-emerald-900",
  HIGH: "bg-rose-50 text-rose-800",
  URGENT: "bg-rose-100 text-rose-900",
  CRITICAL: "bg-rose-100 text-rose-900",
  LOW: "bg-slate-100 text-slate-700",
  MEDIUM: "bg-amber-50 text-amber-800",
};

export function Badge({ children, tone }: { children: React.ReactNode; tone?: string }) {
  return (
    <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold ${tone || "bg-slate-100 text-slate-700"}`}>
      {children}
    </span>
  );
}

export function StatusBadge({ status }: { status: ClaimStatus | string }) {
  return <Badge tone={TONE[status] || TONE.DRAFT}>{prettyStatus(status)}</Badge>;
}

export function Disclaimer({ children }: { children: React.ReactNode }) {
  return (
    <p className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-900">
      {children}
    </p>
  );
}
