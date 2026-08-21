"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { get, getToken } from "@/lib/api";
import type { ClaimStatusPayload } from "@/lib/types";

const ORDER = [
  "VALIDATING_IMAGES",
  "EXTRACTING_METADATA",
  "IDENTIFYING_VEHICLE",
  "READING_PLATE",
  "PROCESSING_CUSTOMER_INPUT",
  "DETECTING_DAMAGE",
  "RECONCILING",
  "VEHICLE_VALUATION",
  "PART_PRICING",
  "ESTIMATING",
  "SUMMARISING",
  "SCORING_CONFIDENCE",
  "RISK_ANALYSIS",
  "REVIEW_DECISION",
  "NOTIFYING_AGENT",
];

export default function ProcessingPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [status, setStatus] = useState<ClaimStatusPayload | null>(null);

  useEffect(() => {
    let ws: WebSocket | null = null;
    const token = getToken();
    if (token) {
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${window.location.host}/api/v1/ws?token=${token}`);
      ws.onmessage = (ev) => {
        const data = JSON.parse(ev.data);
        if (data.claim_id === id && data.type === "claim.completed") {
          router.replace(`/client/claims/${id}`);
        }
      };
    }
    const timer = setInterval(async () => {
      const s = await get<ClaimStatusPayload>(`/api/v1/claims/${id}/status`);
      setStatus(s);
      if (["AI_COMPLETED", "AGENT_REVIEW", "APPROVED", "REJECTED", "MORE_INFORMATION_REQUIRED"].includes(s.status)) {
        router.replace(`/client/claims/${id}`);
      }
    }, 2000);
    return () => {
      clearInterval(timer);
      ws?.close();
    };
  }, [id, router]);

  const progress = status?.progress || {};
  const current = useMemo(() => ORDER.findIndex((k) => progress[k]?.status === "RUNNING"), [progress]);

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <h1 className="text-2xl font-semibold">Your report is being analysed</h1>
      <p className="text-sm text-slate-500">This runs in the background. An agent is notified when it is ready to review.</p>
      <ol className="card divide-y divide-slate-100">
        {ORDER.map((code, i) => {
          const item = progress[code];
          const done = item?.status === "OK";
          const skipped = item?.status === "SKIPPED" || item?.status === "ERROR";
          const running = item?.status === "RUNNING" || current === i;
          return (
            <li key={code} className="flex items-center gap-3 px-4 py-3 text-sm">
              <span className={`grid h-6 w-6 place-items-center rounded-full text-xs ${done ? "bg-accent-500 text-navy-950" : skipped ? "bg-amber-200" : running ? "bg-navy-900 text-white" : "bg-slate-100"}`}>
                {done ? "✓" : i + 1}
              </span>
              <span>{item?.label || code.replaceAll("_", " ").toLowerCase()}</span>
            </li>
          );
        })}
      </ol>
      <Link href={`/client/claims/${id}`} className="text-sm text-accent-700">Open report anyway</Link>
    </div>
  );
}
