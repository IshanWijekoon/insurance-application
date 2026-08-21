"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

function passwordProblems(password: string): string[] {
  const issues: string[] = [];
  if (password.length < 10) issues.push("at least 10 characters");
  if (!/[a-z]/.test(password)) issues.push("a lowercase letter");
  if (!/[A-Z]/.test(password)) issues.push("an uppercase letter");
  if (!/\d/.test(password)) issues.push("a digit");
  return issues;
}

export default function RegisterPage() {
  const { register } = useAuth();
  const router = useRouter();
  const [form, setForm] = useState({ full_name: "", email: "", phone: "", password: "" });
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const missing = passwordProblems(form.password);
    if (missing.length) {
      setError(`Password must contain ${missing.join(", ")}.`);
      return;
    }
    setError("");
    setPending(true);
    try {
      await register({
        full_name: form.full_name.trim(),
        email: form.email.trim(),
        phone: form.phone.trim() || undefined,
        password: form.password,
      });
      router.push("/client");
    } catch (err) {
      setError(err instanceof ApiError ? err.displayMessage() : "Unable to register.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-lg flex-col justify-center px-6 py-16">
      <Link href="/" className="text-sm font-semibold">Aether Cover</Link>
      <h1 className="mt-6 text-2xl font-semibold">Create a client account</h1>
      <form onSubmit={onSubmit} className="mt-8 space-y-4">
        {(["full_name", "email", "phone", "password"] as const).map((key) => (
          <label key={key}>
            <span className="label">{key.replace("_", " ")}</span>
            <input
              className="input"
              type={key === "password" ? "password" : key === "email" ? "email" : "text"}
              value={form[key]}
              onChange={(e) => setForm({ ...form, [key]: e.target.value })}
              required={key !== "phone"}
              minLength={key === "password" ? 10 : undefined}
              autoComplete={key === "password" ? "new-password" : key === "email" ? "email" : "name"}
            />
          </label>
        ))}
        <p className="text-xs text-slate-500">
          Password needs 10+ characters including an uppercase letter, a lowercase letter and a digit. Example: ChangeMe123!
        </p>
        {error && <p className="text-sm text-rose-600">{error}</p>}
        <button className="btn-primary w-full" type="submit" disabled={pending}>
          {pending ? "Creating account…" : "Create account"}
        </button>
        <p className="text-sm text-slate-500">
          Already have an account? <Link href="/login" className="font-semibold text-navy-900">Sign in to the client portal</Link>
        </p>
      </form>
    </div>
  );
}
