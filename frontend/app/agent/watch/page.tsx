"use client";

import { useEffect, useState } from "react";
import { ClaimWatchCard } from "@/components/ClaimWatchCard";
import { get } from "@/lib/api";
import type { ClaimSummary, Page } from "@/lib/types";

export default function AgentWatchPage() {
  const [mine, setMine] = useState<ClaimSummary[]>([]);
  const [queue, setQueue] = useState<ClaimSummary[]>([]);

  async function load() {
    const [assigned, open] = await Promise.all([
      get<Page<ClaimSummary>>("/api/v1/agent/claims?mine=true&page_size=50"),
      get<Page<ClaimSummary>>("/api/v1/agent/claims?needs_verification=true&page_size=50"),
    ]);
    setMine(assigned.items);
    setQueue(open.items);
  }

  useEffect(() => {
    load();
    const timer = setInterval(load, 15000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Watch client reports</h1>
        <p className="text-sm text-slate-500">Each card is a report the client submitted: photo, estimated cost, GPS and time. Open it to verify.</p>
      </div>
      <section className="space-y-3">
        <h2 className="font-semibold">Assigned to me</h2>
        {mine.length === 0 && <p className="text-sm text-slate-500">Nothing assigned yet. Open a claim and choose Assign to me.</p>}
        {mine.map((c) => (
          <ClaimWatchCard key={c.id} claim={c} href={`/agent/claims/${c.id}`} />
        ))}
      </section>
      <section className="space-y-3">
        <h2 className="font-semibold">Open queue</h2>
        {queue.length === 0 && <p className="text-sm text-slate-500">No claims waiting for verification.</p>}
        {queue.map((c) => (
          <ClaimWatchCard key={c.id} claim={c} href={`/agent/claims/${c.id}`} />
        ))}
      </section>
    </div>
  );
}
