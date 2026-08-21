"use client";

import Link from "next/link";
import { LoginForm } from "@/components/LoginForm";

export default function ClientLoginPage() {
  return (
    <div className="grid min-h-screen md:grid-cols-2">
      <div className="hidden bg-navy-950 p-12 text-white md:flex md:flex-col md:justify-between">
        <Link href="/" className="font-semibold">Aether Cover</Link>
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-accent-400">Client portal</p>
          <h2 className="mt-3 text-3xl font-semibold">You report. An agent decides.</h2>
          <p className="mt-3 text-slate-300">Photograph the vehicle, describe the accident, and submit. You will not make the insurance decision here.</p>
        </div>
      </div>
      <LoginForm portal="client" />
    </div>
  );
}
