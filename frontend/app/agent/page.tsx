"use client";

import { useEffect, useState } from "react";
import { ClaimWatchCard } from "@/components/ClaimWatchCard";
import { get } from "@/lib/api";
import type { ClaimSummary, Page } from "@/lib/types";

type Dash = {
  total_claims: number;
  new_claims: number;
  under_review: number;
  high_priority: number;
  approved: number;
  rejected: number;
  pending_information: number;
  awaiting_manual_review: number;
};

function Metric({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string;
  value: number;
  hint?: string;
  tone?: "default" | "action" | "muted";
}) {
  const numberClass =
    value === 0
      ? "text-slate-400"
      : tone === "action"
        ? "text-amber-700"
        : "text-navy-900";

  return (
    <div className="card p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p>
        {tone === "action" && value > 0 && (
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-800">
            Action
          </span>
        )}
      </div>
      <p className={`mt-1 text-3xl font-semibold tabular-nums ${numberClass}`}>{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

export default function AgentDashboard() {
  const [dash, setDash] = useState<Dash | null>(null);
  const [claims, setClaims] = useState<ClaimSummary[]>([]);

  async function load() {
    const [d, page] = await Promise.all([
      get<Dash>("/api/v1/agent/dashboard"),
      get<Page<ClaimSummary>>("/api/v1/agent/claims?page_size=50&needs_verification=true"),
    ]);
    setDash(d);
    setClaims(page.items);
  }

  useEffect(() => {
    load();
    const timer = setInterval(load, 15000);
    return () => clearInterval(timer);
  }, []);

  const needsAction = dash
    ? dash.new_claims + dash.awaiting_manual_review + dash.pending_information + dash.high_priority
    : 0;
  const resolved = dash ? dash.approved + dash.rejected : 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Client reports</h1>
        <p className="mt-1 text-sm text-[#475569]">
          Clients file reports. You review photos, cost, location and time, then verify.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="Total" value={dash?.total_claims ?? 0} hint="All non-deleted reports" />
        <Metric
          label="Needs action"
          value={needsAction}
          hint="New, high priority, verify, or pending info"
          tone="action"
        />
        <Metric label="In review" value={dash?.under_review ?? 0} hint="With an agent or AI-complete" />
        <Metric label="Resolved" value={resolved} hint={`${dash?.approved ?? 0} approved · ${dash?.rejected ?? 0} rejected`} tone="muted" />
      </div>

      <section className="card overflow-hidden">
        <div className="border-b border-slate-100 px-5 py-4">
          <h2 className="font-semibold">Reports waiting for review</h2>
        </div>
        {claims.length === 0 ? (
          <div className="flex flex-col items-center px-6 py-16 text-center">
            <span className="grid h-12 w-12 place-items-center rounded-2xl bg-slate-100 text-slate-500">
              <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="1.8">
                <path d="M4 7h16v12H4z" />
                <path d="M4 7l8 6 8-6" />
              </svg>
            </span>
            <p className="mt-4 font-semibold text-navy-900">No client reports yet</p>
            <p className="mt-1 max-w-sm text-sm text-[#475569]">
              When a client submits an accident report, it appears here and as an alert.
            </p>
          </div>
        ) : (
          <div className="space-y-3 p-4">
            {claims.map((c) => (
              <ClaimWatchCard key={c.id} claim={c} href={`/agent/claims/${c.id}`} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
