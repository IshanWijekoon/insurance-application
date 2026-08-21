"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { homeFor, loginFor, useAuth } from "@/lib/auth";
import { NotificationBell } from "@/components/NotificationBell";

export function Shell({
  children,
  links,
  portal,
}: {
  children: React.ReactNode;
  links: { href: string; label: string }[];
  portal?: string;
}) {
  const { user, logout } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3">
          <Link href={user ? homeFor(user.role) : "/"} className="flex items-center gap-2">
            <span className="grid h-8 w-8 place-items-center rounded-lg bg-navy-900 text-xs font-bold text-accent-400">
              AC
            </span>
            <span className="text-sm font-semibold tracking-tight">Aether Cover</span>
            {portal && <span className="hidden rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-500 sm:inline">{portal}</span>}
          </Link>
          <nav className="hidden items-center gap-1 md:flex">
            {links.map((l) => {
              const active = pathname === l.href || (l.href.split("/").length > 2 && pathname.startsWith(l.href + "/"));
              return (
              <Link
                key={l.href}
                href={l.href}
                className={`rounded-lg px-3 py-1.5 text-sm ${
                  active
                    ? "bg-navy-900 text-white"
                    : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                {l.label}
              </Link>
              );
            })}
          </nav>
          <div className="flex items-center gap-3 text-sm">
            <NotificationBell />
            <span className="hidden text-slate-500 sm:block">{user?.full_name}</span>
            <button
              className="btn-ghost !py-1.5"
              onClick={async () => {
                await logout();
                router.push(user ? loginFor(user.role) : "/login");
              }}
            >
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
    </div>
  );
}
