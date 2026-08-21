"use client";

import Link from "next/link";
import { StatusBadge } from "@/components/Badge";
import { formatWhen, moneyRange } from "@/lib/format";
import type { ClaimSummary } from "@/lib/types";

function coords(claim: ClaimSummary) {
  if (claim.location_latitude == null || claim.location_longitude == null) return "Location not obtained";
  const label = claim.location_label ? `${claim.location_label} · ` : "";
  return `${label}${claim.location_latitude.toFixed(5)}, ${claim.location_longitude.toFixed(5)}`;
}

export function ClaimWatchCard({ claim, href }: { claim: ClaimSummary; href: string }) {
  return (
    <Link href={href} className="card block overflow-hidden transition hover:shadow-md">
      <div className="grid gap-0 sm:grid-cols-[10rem_1fr]">
        <div className="h-40 bg-slate-100 sm:h-full">
          {claim.thumbnail_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={claim.thumbnail_url} alt="" className="h-40 w-full object-cover sm:h-full" />
          ) : (
            <div className="grid h-40 place-items-center text-xs text-slate-400 sm:h-full">No photo</div>
          )}
        </div>
        <div className="space-y-2 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="font-semibold">{claim.claim_number}</p>
            <div className="flex gap-1">
              <StatusBadge status={claim.status} />
              <StatusBadge status={claim.priority} />
            </div>
          </div>
          <p className="text-sm">{claim.vehicle_label || "Vehicle not identified"} · {claim.customer_name || "Unknown customer"}</p>
          <dl className="grid gap-1 text-xs text-slate-600 sm:grid-cols-2">
            <div>
              <dt className="font-semibold uppercase tracking-wide text-slate-400">Cost</dt>
              <dd>{moneyRange(claim.estimate)}</dd>
            </div>
            <div>
              <dt className="font-semibold uppercase tracking-wide text-slate-400">Location</dt>
              <dd>{coords(claim)}</dd>
            </div>
            <div>
              <dt className="font-semibold uppercase tracking-wide text-slate-400">Time</dt>
              <dd>
                Photo {formatWhen(claim.photo_captured_at)} · submitted {formatWhen(claim.submitted_at)}
              </dd>
            </div>
            <div>
              <dt className="font-semibold uppercase tracking-wide text-slate-400">Evidence</dt>
              <dd>
                {claim.image_count} photo{claim.image_count === 1 ? "" : "s"}
                {claim.assigned_agent_name ? ` · ${claim.assigned_agent_name}` : " · unassigned"}
              </dd>
            </div>
          </dl>
        </div>
      </div>
    </Link>
  );
}
