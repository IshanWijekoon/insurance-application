"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { get, post } from "@/lib/api";
import { formatWhen } from "@/lib/format";
import { useAuth } from "@/lib/auth";
import type { AppNotification, Page } from "@/lib/types";

function portalBase(pathname: string) {
  if (pathname.startsWith("/client") || pathname.startsWith("/app")) return "/client";
  if (pathname.startsWith("/admin")) return "/admin";
  return "/agent";
}

export function NotificationBell() {
  const { user } = useAuth();
  const pathname = usePathname();
  const hrefBase = portalBase(pathname);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<AppNotification[]>([]);
  const box = useRef<HTMLDivElement>(null);

  async function refresh() {
    try {
      const count = await get<{ unread: number }>("/api/v1/notifications/unread-count");
      setUnread(count.unread);
      const page = await get<Page<AppNotification>>("/api/v1/notifications?page_size=8");
      setItems(page.items);
    } catch {
      // Polling must not crash the page if the API is briefly unavailable.
    }
  }

  useEffect(() => {
    if (!user) return;
    refresh();
    const timer = setInterval(refresh, 12000);
    return () => clearInterval(timer);
  }, [user]);

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  if (!user) return null;

  return (
    <div className="relative" ref={box}>
      <button className="btn-ghost relative !py-1.5" type="button" onClick={() => setOpen((v) => !v)}>
        Alerts
        {unread > 0 && (
          <span className="absolute -right-1 -top-1 grid h-5 min-w-5 place-items-center rounded-full bg-rose-600 px-1 text-[10px] text-white">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 z-30 mt-2 w-80 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-lg">
          <div className="flex items-center justify-between border-b px-3 py-2 text-xs font-semibold uppercase text-slate-500">
            Notifications
            {unread > 0 && (
              <button
                className="font-semibold text-navy-900"
                type="button"
                onClick={async () => {
                  await post("/api/v1/notifications/read-all");
                  refresh();
                }}
              >
                Mark all read
              </button>
            )}
          </div>
          <ul className="max-h-96 overflow-y-auto text-sm">
            {items.length === 0 && <li className="px-3 py-6 text-center text-slate-500">No alerts yet.</li>}
            {items.map((n) => (
              <li key={n.id} className={n.is_read ? "border-b border-slate-100" : "border-b border-slate-100 bg-accent-500/10"}>
                <Link
                  href={n.claim_id ? `${hrefBase}/claims/${n.claim_id}` : `${hrefBase}/notifications`}
                  className="block px-3 py-2"
                  onClick={async () => {
                    if (!n.is_read) await post(`/api/v1/notifications/${n.id}/read`);
                    setOpen(false);
                  }}
                >
                  <p className="font-semibold">{n.title}</p>
                  <p className="line-clamp-2 text-xs text-slate-500">{n.body}</p>
                  <p className="mt-1 text-[10px] text-slate-400">{formatWhen(n.created_at)}</p>
                </Link>
              </li>
            ))}
          </ul>
          <Link href={`${hrefBase}/notifications`} className="block bg-slate-50 px-3 py-2 text-center text-xs font-semibold" onClick={() => setOpen(false)}>
            Open notification centre
          </Link>
        </div>
      )}
    </div>
  );
}
