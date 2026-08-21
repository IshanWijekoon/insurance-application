"use client";

import { useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { useRequireRole } from "@/lib/auth";
import { get } from "@/lib/api";

export default function AdminPage() {
  const { loading } = useRequireRole(["ADMIN"]);
  const [analytics, setAnalytics] = useState<Record<string, unknown> | null>(null);
  const [sources, setSources] = useState<{ id: string; name: string; base_url: string; is_enabled: boolean; robots_allows: boolean | null }[]>([]);
  const [ai, setAi] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    if (loading) return;
    get("/api/v1/admin/analytics").then(setAnalytics);
    get("/api/v1/admin/market-sources").then(setSources as never);
    get("/api/v1/admin/ai-config").then(setAi);
  }, [loading]);

  if (loading) return null;

  return (
    <Shell portal="Admin" links={[{ href: "/admin", label: "Overview" }]}>
      <div className="space-y-6">
        <h1 className="text-2xl font-semibold">Administration</h1>
        <div className="grid gap-4 md:grid-cols-4">
          {analytics &&
            ["total_claims", "approved", "rejected", "awaiting_review"].map((k) => (
              <div key={k} className="card p-4">
                <p className="text-xs text-slate-500">{k.replaceAll("_", " ")}</p>
                <p className="text-2xl font-semibold">{String(analytics[k])}</p>
              </div>
            ))}
        </div>
        <section className="card p-5">
          <h2 className="font-semibold">AI providers</h2>
          <p className="mt-2 text-sm text-slate-600">Active: {String(ai?.ai_provider)} / vision {String(ai?.vision_provider)}</p>
          <p className="text-xs text-slate-500">API keys are never displayed. Configure them through environment variables.</p>
        </section>
        <section className="card overflow-hidden">
          <div className="border-b px-5 py-4 font-semibold">Market source whitelist</div>
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-2">Name</th>
                <th>URL</th>
                <th>Enabled</th>
                <th>robots.txt</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {sources.map((s) => (
                <tr key={s.id}>
                  <td className="px-4 py-2">{s.name}</td>
                  <td className="text-accent-700">{s.base_url}</td>
                  <td>{s.is_enabled ? "yes" : "no"}</td>
                  <td>{s.robots_allows == null ? "unchecked" : s.robots_allows ? "allowed" : "disallowed"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
    </Shell>
  );
}
