"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { StatusBadge } from "@/components/Badge";
import { get } from "@/lib/api";
import { moneyRange } from "@/lib/format";
import type { ClaimSummary, Page } from "@/lib/types";
import { useAuth } from "@/lib/auth";

const STEPS = [
  ["1", "You report", "Photos, what happened, damage markings."],
  ["2", "AI assists", "Preliminary estimate from images and market data."],
  ["3", "Agent reviews", "An authorised agent verifies and decides."],
] as const;

function ReportRow({ claim }: { claim: ClaimSummary }) {
  const estimateReady = claim.estimate?.status === "AVAILABLE";
  const showEstimateWarning = claim.status !== "DRAFT" && !estimateReady;

  return (
    <li>
      <Link
        href={`/client/claims/${claim.id}`}
        className="flex items-center gap-3 px-5 py-3.5 transition hover:bg-[#F8FAFC]"
      >
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-navy-900">{claim.claim_number}</p>
          <p className="truncate text-sm text-slate-600">{claim.vehicle_label || "Vehicle pending identification"}</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <StatusBadge status={claim.status} />
          {estimateReady && (
            <span className="hidden text-xs font-medium text-slate-600 sm:inline">{moneyRange(claim.estimate)}</span>
          )}
          {showEstimateWarning && (
            <span
              className="grid h-6 w-6 place-items-center rounded-full bg-amber-50 text-amber-700"
              title="Estimate unavailable — an agent will verify"
            >
              !
            </span>
          )}
          <span className="text-slate-400" aria-hidden>
            →
          </span>
        </div>
      </Link>
    </li>
  );
}

export default function ClientHome() {
  const { user } = useAuth();
  const [claims, setClaims] = useState<ClaimSummary[]>([]);

  useEffect(() => {
    get<Page<ClaimSummary>>("/api/v1/claims?page_size=5").then((p) => setClaims(p.items)).catch(() => {});
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-accent-600">Client portal</p>
          <h1 className="text-2xl font-semibold">Hello, {user?.full_name.split(" ")[0]}</h1>
          <p className="text-sm text-slate-500">Your job is to report the accident. An insurance agent reviews the report and makes the decision.</p>
        </div>
        <Link href="/client/claims/new" className="btn-accent">
          Report an accident
        </Link>
      </div>

      <ol className="grid gap-3 md:grid-cols-[1fr_auto_1fr_auto_1fr] md:items-stretch">
        {STEPS.map(([n, t, d], i) => (
          <li key={n} className="contents">
            <div className="card flex items-center gap-3 px-4 py-3">
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-navy-900 text-xs font-bold text-white">
                {n}
              </span>
              <div>
                <p className="font-semibold">{t}</p>
                <p className="text-sm text-slate-500">{d}</p>
              </div>
            </div>
            {i < STEPS.length - 1 && (
              <span className="hidden items-center justify-center text-slate-300 md:flex" aria-hidden>
                →
              </span>
            )}
          </li>
        ))}
      </ol>

      <section className="card overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <h2 className="font-semibold">My reports</h2>
          <Link href="/client/claims" className="text-sm font-semibold text-accent-600">
            View all
          </Link>
        </div>
        <ul className="divide-y divide-slate-100">
          {claims.length === 0 && (
            <li className="px-5 py-8 text-sm text-slate-500">No reports yet. Start with Report an accident.</li>
          )}
          {claims.map((c) => (
            <ReportRow key={c.id} claim={c} />
          ))}
        </ul>
      </section>
    </div>
  );
}
