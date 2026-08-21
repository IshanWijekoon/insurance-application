"use client";

import { Shell } from "@/components/Shell";
import { useRequireRole } from "@/lib/auth";

export default function ClientLayout({ children }: { children: React.ReactNode }) {
  const { loading } = useRequireRole(["CUSTOMER"]);
  if (loading) return <div className="p-10 text-sm text-slate-500">Loading…</div>;
  return (
    <Shell
      portal="Client portal"
      links={[
        { href: "/client", label: "Home" },
        { href: "/client/claims", label: "My reports" },
        { href: "/client/vehicles", label: "Vehicles" },
        { href: "/client/notifications", label: "Updates" },
      ]}
    >
      {children}
    </Shell>
  );
}
