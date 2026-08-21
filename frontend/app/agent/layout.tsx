"use client";

import { Shell } from "@/components/Shell";
import { useRequireRole } from "@/lib/auth";

export default function AgentLayout({ children }: { children: React.ReactNode }) {
  const { loading } = useRequireRole(["AGENT", "ADMIN"]);
  if (loading) return <div className="p-10 text-sm text-slate-500">Loading…</div>;
  return (
    <Shell
      portal="Agent portal"
      links={[
        { href: "/agent", label: "Client reports" },
        { href: "/agent/watch", label: "Watch" },
      ]}
    >
      {children}
    </Shell>
  );
}
