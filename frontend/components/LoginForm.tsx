"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ApiError } from "@/lib/api";
import { homeFor, useAuth } from "@/lib/auth";
import type { Role } from "@/lib/types";

export function LoginForm({
  portal,
}: {
  portal: "client" | "agent";
}) {
  const { login, logout } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  const allowed: Role[] = portal === "client" ? ["CUSTOMER"] : ["AGENT", "ADMIN"];
  const otherHref = portal === "client" ? "/login/agent" : "/login";
  const otherLabel = portal === "client" ? "Agent portal" : "Client portal";

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setPending(true);
    try {
      const user = await login(email, password);
      if (!allowed.includes(user.role)) {
        await logout();
        setError(
          portal === "client"
            ? "This is the client portal. Agents sign in through the agent portal."
            : "This is the agent portal. Clients sign in through the client portal.",
        );
        return;
      }
      router.push(homeFor(user.role));
    } catch (err) {
      setError(err instanceof ApiError ? err.displayMessage() : "Unable to sign in.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="mx-auto flex w-full max-w-md flex-col justify-center px-6 py-16">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-accent-600">
        {portal === "client" ? "Client portal" : "Agent portal"}
      </p>
      <h1 className="mt-2 text-2xl font-semibold">
        {portal === "client" ? "Report an accident" : "Review client reports"}
      </h1>
      <p className="mt-1 text-sm text-slate-500">
        {portal === "client"
          ? "Clients file a report here. An insurance agent reviews it afterwards."
          : "Agents review reports submitted by clients. Clients cannot sign in here."}
      </p>
      <label className="mt-8">
        <span className="label">Email</span>
        <input className="input" type="text" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
      </label>
      <label className="mt-4">
        <span className="label">Password</span>
        <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
      </label>
      {error && <p className="mt-3 text-sm text-rose-600">{error}</p>}
      <button className="btn-primary mt-6" type="submit" disabled={pending}>
        {pending ? "Signing in…" : "Continue"}
      </button>
      {portal === "client" && (
        <p className="mt-4 text-sm text-slate-500">
          New client? <Link href="/register" className="font-semibold text-navy-900">Create an account</Link>
        </p>
      )}
      <p className="mt-4 text-sm text-slate-500">
        {portal === "client" ? "Are you an agent?" : "Are you a client?"}{" "}
        <Link href={otherHref} className="font-semibold text-navy-900">{otherLabel}</Link>
      </p>
      <p className="mt-8 text-xs text-slate-400">
        {portal === "client"
          ? "Demo client: customer@insure.local / ChangeMe123!"
          : "Demo agent: agent@insure.local / ChangeMe123!"}
      </p>
    </form>
  );
}
