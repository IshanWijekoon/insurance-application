"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { get, post } from "@/lib/api";
import { formatWhen } from "@/lib/format";
import type { AppNotification, Page } from "@/lib/types";

export default function AgentNotificationsPage() {
  const [items, setItems] = useState<AppNotification[]>([]);
  const [total, setTotal] = useState(0);

  async function load() {
    const page = await get<Page<AppNotification>>("/api/v1/notifications?page_size=50");
    setItems(page.items);
    setTotal(page.total);
  }

  useEffect(() => {
    load();
    const timer = setInterval(load, 12000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Notifications</h1>
          <p className="text-sm text-slate-500">{total} alert{total === 1 ? "" : "s"} · new claims and analysis-ready reports appear here.</p>
        </div>
        <button
          className="btn-ghost"
          type="button"
          onClick={async () => {
            await post("/api/v1/notifications/read-all");
            load();
          }}
        >
          Mark all read
        </button>
      </div>
      <ul className="space-y-2">
        {items.length === 0 && <li className="card p-6 text-sm text-slate-500">No notifications yet. Submit a customer claim to see an agent alert.</li>}
        {items.map((n) => (
          <li key={n.id} className={`card p-4 ${n.is_read ? "" : "border-accent-500/40 bg-accent-500/10"}`}>
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="font-semibold">{n.title}</p>
                <p className="mt-1 whitespace-pre-wrap text-sm text-slate-600">{n.body}</p>
                <p className="mt-2 text-xs text-slate-400">{formatWhen(n.created_at)}</p>
              </div>
              {n.claim_id && (
                <Link
                  className="btn-primary shrink-0"
                  href={`/agent/claims/${n.claim_id}`}
                  onClick={async () => {
                    if (!n.is_read) await post(`/api/v1/notifications/${n.id}/read`);
                  }}
                >
                  Open report
                </Link>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
