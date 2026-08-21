"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { StatusBadge } from "@/components/Badge";
import { get } from "@/lib/api";
import { formatWhen, moneyRange } from "@/lib/format";
import type { ClaimSummary, Page } from "@/lib/types";

export default function ClientReportsPage() {
  const [items, setItems] = useState<ClaimSummary[]>([]);
  useEffect(() => {
    get<Page<ClaimSummary>>("/api/v1/claims?page_size=50").then((p) => setItems(p.items));
  }, []);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">My reports</h1>
          <p className="text-sm text-slate-500">These are the accident reports you submitted. An agent reviews each one.</p>
        </div>
        <Link href="/client/claims/new" className="btn-accent">Report an accident</Link>
      </div>
      <div className="card overflow-hidden">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase text-slate-500">
            <tr>
              <th className="px-4 py-3">Report</th>
              <th>Vehicle</th>
              <th>Status</th>
              <th>Created</th>
              <th className="w-8" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {items.map((c) => {
              const estimateReady = c.estimate?.status === "AVAILABLE";
              return (
                <tr key={c.id} className="cursor-pointer hover:bg-[#F8FAFC]">
                  <td className="px-4 py-3 font-semibold">
                    <Link href={`/client/claims/${c.id}`} className="block">
                      {c.claim_number}
                    </Link>
                  </td>
                  <td className="text-slate-600">{c.vehicle_label || "Pending identification"}</td>
                  <td>
                    <span className="inline-flex items-center gap-1.5">
                      <StatusBadge status={c.status} />
                      {c.status !== "DRAFT" && !estimateReady && (
                        <span className="text-amber-600" title="Estimate unavailable — an agent will verify">!</span>
                      )}
                      {estimateReady && <span className="text-xs text-slate-500">{moneyRange(c.estimate)}</span>}
                    </span>
                  </td>
                  <td className="text-slate-500">{formatWhen(c.created_at)}</td>
                  <td className="pr-4 text-right text-slate-400">
                    <Link href={`/client/claims/${c.id}`} aria-label={`Open ${c.claim_number}`}>→</Link>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
