"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Disclaimer, StatusBadge } from "@/components/Badge";
import { EstimateBreakdown } from "@/components/EstimateBreakdown";
import { get, post } from "@/lib/api";
import { formatWhen, moneyRange, pct } from "@/lib/format";
import type { ClaimDetail } from "@/lib/types";

export default function CustomerClaimPage() {
  const { id } = useParams<{ id: string }>();
  const [claim, setClaim] = useState<ClaimDetail | null>(null);
  const [reg, setReg] = useState("");

  useEffect(() => {
    get<ClaimDetail>(`/api/v1/claims/${id}`).then(setClaim);
  }, [id]);

  if (!claim) return <p className="text-sm text-slate-500">Loading claim…</p>;
  const v = claim.assessment?.vehicle;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500">{claim.claim_number}</p>
          <h1 className="text-2xl font-semibold">Your accident report</h1>
          <p className="text-sm text-slate-500">You submitted this. An agent reviews it and records the insurance decision.</p>
        </div>
        <StatusBadge status={claim.status} />
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <div className="card p-4">
          <p className="text-xs text-slate-500">Vehicle</p>
          <p className="font-semibold">{[v?.make, v?.model, v?.year].filter(Boolean).join(" ") || Object.values(claim.vehicle).filter(Boolean).join(" ") || "Not identified"}</p>
        </div>
        <div className="card p-4">
          <p className="text-xs text-slate-500">Estimated repair cost</p>
          <p className="font-semibold">{moneyRange(claim.estimate?.total ?? null)}</p>
        </div>
        <div className="card p-4">
          <p className="text-xs text-slate-500">Estimated vehicle value</p>
          <p className="font-semibold">{moneyRange(claim.market_data?.valuation ?? null)}</p>
        </div>
      </div>

      {claim.assessment && (
        <Disclaimer>{claim.assessment.disclaimer}</Disclaimer>
      )}

      {claim.assessment?.vehicle?.ocr_confidence != null && claim.assessment.vehicle.ocr_confidence < 0.75 && (
        <form
          className="card flex flex-wrap items-end gap-3 p-4"
          onSubmit={async (e) => {
            e.preventDefault();
            await post(`/api/v1/claims/${id}/confirm-registration`, { registration_number: reg });
            setClaim(await get(`/api/v1/claims/${id}`));
          }}
        >
          <label className="flex-1">
            <span className="label">Confirm registration (OCR {pct(claim.assessment.vehicle.ocr_confidence)})</span>
            <input className="input" value={reg} placeholder={claim.assessment.vehicle.registration_number || ""} onChange={(e) => setReg(e.target.value)} />
          </label>
          <button className="btn-primary" type="submit">Confirm</button>
        </form>
      )}

      {claim.assessment?.reconciliation && (
        <div className="card p-5">
          <h2 className="font-semibold">Customer report vs AI detection</h2>
          <p className="mt-2 text-sm text-slate-600">{claim.assessment.reconciliation.summary}</p>
        </div>
      )}

      {claim.estimate && <EstimateBreakdown estimate={claim.estimate} />}

      <section className="card p-5">
        <h2 className="font-semibold">Photographs</h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {claim.images.map((img) => (
            <figure key={img.id} className="overflow-hidden rounded-xl border">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={img.annotated_url || img.url || ""} alt="" className="h-48 w-full object-cover" />
              <figcaption className="space-y-1 p-3 text-xs text-slate-500">
                <p>{img.image_role} · captured {formatWhen(img.image_metadata?.captured_at)} ({img.image_metadata?.has_exif ? "EXIF" : "upload time is not the accident time"})</p>
                {img.customer_note && <p className="text-slate-700">{img.customer_note}</p>}
              </figcaption>
            </figure>
          ))}
        </div>
      </section>

      {claim.location && (
        <div className="card p-5">
          <h2 className="font-semibold">Location</h2>
          <p className="text-sm text-slate-600">{claim.location.address || `${claim.location.latitude}, ${claim.location.longitude}`}</p>
          <p className="text-xs text-slate-500">Source: {claim.location.source.replaceAll("_", " ")}</p>
        </div>
      )}
    </div>
  );
}
