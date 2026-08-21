"use client";

import { FormEvent, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Disclaimer, StatusBadge } from "@/components/Badge";
import { EstimateBreakdown } from "@/components/EstimateBreakdown";
import { ApiError, get, post } from "@/lib/api";
import { formatWhen, lkr, moneyRange, pct } from "@/lib/format";
import type { ClaimDetail } from "@/lib/types";

export default function AgentClaimPage() {
  const { id } = useParams<{ id: string }>();
  const [claim, setClaim] = useState<ClaimDetail | null>(null);
  const [note, setNote] = useState("");
  const [info, setInfo] = useState("");
  const [decision, setDecision] = useState<"APPROVED" | "REJECTED" | "AGENT_REVIEW">("APPROVED");
  const [reason, setReason] = useState("");
  const [overlay, setOverlay] = useState(true);
  const [checks, setChecks] = useState({
    images_reviewed: false,
    cost_reviewed: false,
    location_reviewed: false,
    time_reviewed: false,
  });
  const [error, setError] = useState("");

  async function reload() {
    setClaim(await get<ClaimDetail>(`/api/v1/agent/claims/${id}`));
  }
  useEffect(() => { reload(); }, [id]);

  if (!claim) return <p>Loading…</p>;

  async function onNote(e: FormEvent) {
    e.preventDefault();
    await post(`/api/v1/agent/claims/${id}/notes`, { body: note, visibility: "INTERNAL" });
    setNote("");
    reload();
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500">Client report · {claim.claim_number}</p>
          <h1 className="text-2xl font-semibold">Review {claim.customer_name}&apos;s report</h1>
          <p className="text-sm text-slate-500">{claim.customer_email} · {claim.customer_phone} · policy {claim.policy_number || "—"}</p>
        </div>
        <div className="flex gap-2">
          <StatusBadge status={claim.status} />
          <StatusBadge status={claim.priority} />
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        <button className="btn-ghost" onClick={() => post(`/api/v1/agent/claims/${id}/assign`).then(reload)}>Assign to me</button>
        <button className="btn-ghost" onClick={() => post(`/api/v1/agent/claims/${id}/analyze`).then(reload)}>Re-run AI</button>
        <label className="btn-ghost">
          <input type="checkbox" checked={overlay} onChange={(e) => setOverlay(e.target.checked)} className="mr-2" />
          Damage overlay
        </label>
      </div>

      {claim.manual_review_required && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
          <p className="font-semibold">Manual review required</p>
          <ul className="mt-2 list-disc pl-5">
            {claim.manual_review_reasons.map((r) => <li key={r}>{r}</li>)}
          </ul>
        </div>
      )}

      <section className="card p-5">
        <h2 className="font-semibold">Claim report to verify</h2>
        <p className="mt-1 text-sm text-slate-500">Review the photograph, cost, location and time before recording a decision.</p>
        <dl className="mt-4 grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <dt className="text-xs font-semibold uppercase tracking-wide text-slate-400">Images</dt>
            <dd>{claim.images.length} photograph{claim.images.length === 1 ? "" : "s"}</dd>
          </div>
          <div>
            <dt className="text-xs font-semibold uppercase tracking-wide text-slate-400">Cost</dt>
            <dd>{claim.estimate ? moneyRange(claim.estimate.total) : "Unavailable — manual verification required"}</dd>
          </div>
          <div>
            <dt className="text-xs font-semibold uppercase tracking-wide text-slate-400">Location</dt>
            <dd>
              {claim.location
                ? `${claim.location.latitude.toFixed(5)}, ${claim.location.longitude.toFixed(5)} (${claim.location.source.replaceAll("_", " ")})`
                : "Not obtained"}
            </dd>
          </div>
          <div>
            <dt className="text-xs font-semibold uppercase tracking-wide text-slate-400">Time</dt>
            <dd>
              Photo {formatWhen(claim.images.find((i) => i.image_metadata?.captured_at)?.image_metadata?.captured_at)}
              <br />
              Submitted {formatWhen(claim.submitted_at)}
            </dd>
          </div>
        </dl>
      </section>

      <section className="card p-5">
        <h2 className="font-semibold">Customer report</h2>
        <p className="mt-2 whitespace-pre-wrap text-sm">{claim.accident_description || "No description provided."}</p>
        <p className="mt-2 text-xs text-slate-500">Reported parts: {claim.customer_reported_parts.join(", ") || "none"}</p>
        {claim.customer_vehicle_description && <p className="mt-2 text-sm text-slate-600">{claim.customer_vehicle_description}</p>}
      </section>

      {claim.assessment?.reconciliation && (
        <section className="card p-5">
          <h2 className="font-semibold">AI vs customer</h2>
          <p className="mt-2 text-sm">{claim.assessment.reconciliation.summary}</p>
        </section>
      )}

      <section className="grid gap-4 lg:grid-cols-2">
        {claim.images.map((img) => (
          <figure key={img.id} className="card overflow-hidden">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={(overlay && img.annotated_url) || img.url || ""} alt="" className="h-56 w-full object-cover" />
            <figcaption className="p-3 text-xs text-slate-500">
              {img.image_role} · captured {formatWhen(img.image_metadata?.captured_at)} · source {img.image_metadata?.has_exif ? "EXIF" : "unavailable"}
            </figcaption>
          </figure>
        ))}
      </section>

      {claim.assessment && (
        <section className="card overflow-hidden">
          <div className="border-b px-5 py-4 font-semibold">AI damage analysis</div>
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-2">Part</th>
                <th>Type</th>
                <th>Severity</th>
                <th>Action</th>
                <th>Confidence</th>
                <th>Agreement</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {claim.assessment.damaged_parts.map((p) => (
                <tr key={p.id}>
                  <td className="px-4 py-2">{p.display_name}</td>
                  <td>{p.damage_type}</td>
                  <td><StatusBadge status={p.severity} /></td>
                  <td>{p.recommended_action}</td>
                  <td>{pct(p.confidence)}</td>
                  <td>{p.agreement.replaceAll("_", " ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {claim.assessment.disclaimer && <div className="p-4"><Disclaimer>{claim.assessment.disclaimer}</Disclaimer></div>}
        </section>
      )}

      <section className="card p-5">
        <h2 className="font-semibold">Web price evidence</h2>
        {claim.part_prices.length === 0 && <p className="mt-2 text-sm text-slate-500">No part prices researched yet.</p>}
        {claim.part_prices.map((part) => (
          <div key={part.damaged_part_id} className="mt-4 border-t pt-4">
            <p className="font-semibold">{part.display_name} · {moneyRange(part.price)}</p>
            <p className="text-xs text-slate-500">{part.confidence_reason}</p>
            <ul className="mt-2 space-y-1 text-sm">
              {part.sources.map((s) => (
                <li key={s.id} className="flex justify-between gap-3">
                  <a className="text-accent-700 underline" href={s.url || undefined} target="_blank" rel="noreferrer">
                    {s.source_name} · {s.product_name}
                  </a>
                  <span>{lkr(s.price, s.currency)} · {s.part_grade} · {formatWhen(s.retrieved_at)}</span>
                </li>
              ))}
              {part.price.status === "UNAVAILABLE" && <li className="text-amber-800">{part.price.reason}</li>}
            </ul>
          </div>
        ))}
      </section>

      {claim.market_data && (
        <section className="card p-5">
          <h2 className="font-semibold">Vehicle valuation</h2>
          <p className="mt-1">{claim.market_data.vehicle_label} · {moneyRange(claim.market_data.valuation)}</p>
          <ul className="mt-3 space-y-1 text-sm">
            {claim.market_data.sources.map((s, i) => (
              <li key={i} className="flex justify-between">
                <a className="underline" href={s.url || undefined} target="_blank" rel="noreferrer">{s.source_name}</a>
                <span>{lkr(s.price, s.currency)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {claim.estimate && <EstimateBreakdown estimate={claim.estimate} />}

      {claim.location && (
        <section className="card p-5">
          <h2 className="font-semibold">Location · {claim.location.source.replaceAll("_", " ")}</h2>
          <iframe
            title="map"
            className="mt-3 h-56 w-full rounded-xl border"
            src={`https://www.openstreetmap.org/export/embed.html?bbox=${claim.location.longitude - 0.02}%2C${claim.location.latitude - 0.02}%2C${claim.location.longitude + 0.02}%2C${claim.location.latitude + 0.02}&layer=mapnik&marker=${claim.location.latitude}%2C${claim.location.longitude}`}
          />
        </section>
      )}

      {claim.fraud_signals.length > 0 && (
        <section className="card p-5">
          <h2 className="font-semibold">Risk signals</h2>
          <ul className="mt-2 space-y-2 text-sm">
            {claim.fraud_signals.map((s) => (
              <li key={s.signal_code}><StatusBadge status={s.risk_level} /> {s.description}</li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-slate-500">Signals never automatically reject a claim.</p>
        </section>
      )}

      <section className="card p-5">
        <h2 className="font-semibold">Timeline</h2>
        <ol className="mt-3 space-y-2 text-sm">
          {claim.timeline.map((e) => (
            <li key={e.at + e.title}>
              <span className="text-slate-500">{formatWhen(e.at)}</span> · {e.title}
              {e.detail && <p className="text-slate-600">{e.detail}</p>}
            </li>
          ))}
        </ol>
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <form className="card space-y-3 p-5" onSubmit={onNote}>
          <h3 className="font-semibold">Internal note</h3>
          <textarea className="input min-h-24" value={note} onChange={(e) => setNote(e.target.value)} />
          <button className="btn-primary">Add note</button>
        </form>
        <form
          className="card space-y-3 p-5"
          onSubmit={async (e) => {
            e.preventDefault();
            await post(`/api/v1/agent/claims/${id}/request-information`, { message: info });
            setInfo("");
            reload();
          }}
        >
          <h3 className="font-semibold">Request more information</h3>
          <textarea className="input min-h-24" value={info} onChange={(e) => setInfo(e.target.value)} />
          <button className="btn-ghost">Send to customer</button>
        </form>
      </div>

      <form
        className="card space-y-3 p-5"
        onSubmit={async (e) => {
          e.preventDefault();
          setError("");
          try {
            await post(`/api/v1/agent/claims/${id}/verify`, { decision, reason, ...checks });
            reload();
          } catch (err) {
            setError(err instanceof ApiError ? err.displayMessage() : "Could not record the decision.");
          }
        }}
      >
        <h3 className="font-semibold">Verify and decide</h3>
        <p className="text-xs text-slate-500">This is the authorised human decision. The AI estimate is not a settlement. Approval requires all four checks.</p>
        <div className="grid gap-2 sm:grid-cols-2">
          {(
            [
              ["images_reviewed", "Images reviewed"],
              ["cost_reviewed", "Cost reviewed"],
              ["location_reviewed", "Location reviewed"],
              ["time_reviewed", "Time reviewed"],
            ] as const
          ).map(([key, label]) => (
            <label key={key} className="flex items-center gap-2 rounded-xl border border-slate-200 px-3 py-2 text-sm">
              <input
                type="checkbox"
                checked={checks[key]}
                onChange={(e) => setChecks({ ...checks, [key]: e.target.checked })}
              />
              {label}
            </label>
          ))}
        </div>
        <select className="input" value={decision} onChange={(e) => setDecision(e.target.value as typeof decision)}>
          <option value="APPROVED">Approve</option>
          <option value="REJECTED">Reject</option>
          <option value="AGENT_REVIEW">Further assessment</option>
        </select>
        <textarea className="input min-h-24" required value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason for the decision" />
        {error && <p className="text-sm text-rose-600">{error}</p>}
        <button className="btn-accent">Verify and record decision</button>
      </form>
    </div>
  );
}
