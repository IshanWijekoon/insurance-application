"use client";

import { FormEvent, useEffect, useState } from "react";
import { get, post } from "@/lib/api";
import type { Page, Vehicle } from "@/lib/types";

export default function VehiclesPage() {
  const [items, setItems] = useState<Vehicle[]>([]);
  const [form, setForm] = useState({ make: "", model: "", year: "", registration_number: "", color: "" });

  function reload() {
    get<Page<Vehicle>>("/api/v1/vehicles").then((p) => setItems(p.items));
  }
  useEffect(() => { reload(); }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    await post("/api/v1/vehicles", {
      ...form,
      year: form.year ? Number(form.year) : null,
    });
    setForm({ make: "", model: "", year: "", registration_number: "", color: "" });
    reload();
  }

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <form onSubmit={onSubmit} className="card space-y-3 p-5 lg:col-span-1">
        <h1 className="font-semibold">Add a vehicle</h1>
        <p className="text-xs text-slate-500">Every field is optional. Enter only what you know.</p>
        {Object.keys(form).map((key) => (
          <label key={key}>
            <span className="label">{key.replaceAll("_", " ")}</span>
            <input className="input" value={(form as Record<string, string>)[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })} />
          </label>
        ))}
        <button className="btn-primary w-full" type="submit">Save vehicle</button>
      </form>
      <div className="grid gap-3 lg:col-span-2">
        {items.map((v) => (
          <div key={v.id} className="card p-5">
            <p className="font-semibold">{v.display_name}</p>
            <p className="text-sm text-slate-500">{v.registration_number || "No registration on file"} · {v.color || "colour unknown"}</p>
          </div>
        ))}
        {items.length === 0 && <p className="text-sm text-slate-500">No vehicles in your garage yet.</p>}
      </div>
    </div>
  );
}
