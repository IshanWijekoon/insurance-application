"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { get } from "@/lib/api";
import { formatWhen } from "@/lib/format";
import type { AppNotification, Page } from "@/lib/types";

export default function CustomerNotificationsPage() {
  const [items, setItems] = useState<AppNotification[]>([]);

  async function load() {
    const page = await get<Page<AppNotification>>("/api/v1/notifications?page_size=50");
    setItems(page.items);
  }

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Notifications</h1>
      <ul className="space-y-2">
        {items.length === 0 && <li className="text-sm text-slate-500">No updates yet.</li>}
        {items.map((n) => (
          <li key={n.id} className="card p-4">
            <p className="font-semibold">{n.title}</p>
            <p className="mt-1 text-sm text-slate-600">{n.body}</p>
            <p className="mt-2 text-xs text-slate-400">{formatWhen(n.created_at)}</p>
            {n.claim_id && (
              <Link className="mt-3 inline-block text-sm font-semibold" href={`/client/claims/${n.claim_id}`}>
                Open report
              </Link>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
