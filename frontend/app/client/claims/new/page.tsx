"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AnnotationCanvas, type Region } from "@/components/AnnotationCanvas";
import { MapPicker, type LocationValue } from "@/components/MapPicker";
import { get, patch, post } from "@/lib/api";
import { firstGpsFromFiles } from "@/lib/exif";
import type { ClaimDetail, ClaimImage, Page, PartCatalogItem, Vehicle } from "@/lib/types";

const STEPS = [
  "Vehicle",
  "Details",
  "Accident",
  "Photos",
  "Mark damage",
  "Location",
  "Review",
  "Submit",
];

const ROLES = ["FRONT", "REAR", "LEFT", "RIGHT", "DAMAGE_CLOSEUP", "NUMBER_PLATE", "OTHER"] as const;

export default function NewClaimPage() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [parts, setParts] = useState<PartCatalogItem[]>([]);
  const [claim, setClaim] = useState<ClaimDetail | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [form, setForm] = useState({
    vehicle_id: "",
    stated_make: "",
    stated_model: "",
    stated_year: "",
    stated_color: "",
    stated_registration: "",
    customer_vehicle_description: "",
    accident_description: "",
    reported_parts: [] as string[],
    free_text_parts: "",
  });
  const [role, setRole] = useState<(typeof ROLES)[number]>("FRONT");
  const [annotating, setAnnotating] = useState<ClaimImage | null>(null);
  const [regions, setRegions] = useState<Region[]>([]);
  const [location, setLocation] = useState<LocationValue | null>(null);
  const [photoGpsHint, setPhotoGpsHint] = useState("");

  useEffect(() => {
    get<Page<Vehicle>>("/api/v1/vehicles").then((p) => setVehicles(p.items));
    get<PartCatalogItem[]>("/api/v1/claims/part-catalog").then(setParts);
  }, []);

  async function ensureClaim() {
    if (claim) return claim;
    const created = await post<ClaimDetail>("/api/v1/claims", {
      vehicle_id: form.vehicle_id || null,
      stated_make: form.stated_make || null,
      stated_model: form.stated_model || null,
      stated_year: form.stated_year ? Number(form.stated_year) : null,
      stated_color: form.stated_color || null,
      stated_registration: form.stated_registration || null,
      customer_vehicle_description: form.customer_vehicle_description || null,
      accident_description: form.accident_description || null,
    });
    setClaim(created);
    return created;
  }

  async function persistDraft(current = claim) {
    const target = current ?? (await ensureClaim());
    await patch(`/api/v1/claims/${target.id}`, {
      vehicle_id: form.vehicle_id || null,
      stated_make: form.stated_make || null,
      stated_model: form.stated_model || null,
      stated_year: form.stated_year ? Number(form.stated_year) : null,
      stated_color: form.stated_color || null,
      stated_registration: form.stated_registration || null,
      customer_vehicle_description: form.customer_vehicle_description || null,
      accident_description: form.accident_description || null,
    });
    await post(`/api/v1/claims/${target.id}/damage-report`, {
      reported_parts: form.reported_parts,
      free_text_parts: form.free_text_parts || null,
    });
    if (location && location.source !== "EXIF_GPS") {
      await post(`/api/v1/claims/${target.id}/location`, location);
    }
    const fresh = await get<ClaimDetail>(`/api/v1/claims/${target.id}`);
    setClaim(fresh);
    if (!location || location.source === "EXIF_GPS" || fresh.location?.source === "EXIF_GPS") {
      applyLocationFromClaim(fresh);
    }
    return fresh;
  }

  function applyLocationFromClaim(detail: ClaimDetail) {
    if (detail.location) {
      setLocation({
        latitude: detail.location.latitude,
        longitude: detail.location.longitude,
        source: (detail.location.source as LocationValue["source"]) || "EXIF_GPS",
      });
      return;
    }
    const photo = detail.images.find(
      (img) => img.image_metadata?.gps_latitude != null && img.image_metadata?.gps_longitude != null,
    );
    if (photo?.image_metadata?.gps_latitude != null && photo.image_metadata.gps_longitude != null) {
      setLocation({
        latitude: photo.image_metadata.gps_latitude,
        longitude: photo.image_metadata.gps_longitude,
        source: "EXIF_GPS",
      });
    }
  }

  async function next() {
    setError("");
    setSaving(true);
    try {
      if (step === 0) {
        const selected = vehicles.find((v) => v.id === form.vehicle_id);
        if (selected) {
          setForm((f) => ({
            ...f,
            stated_make: f.stated_make || selected.make || "",
            stated_model: f.stated_model || selected.model || "",
            stated_year: f.stated_year || (selected.year ? String(selected.year) : ""),
            stated_color: f.stated_color || selected.color || "",
            stated_registration: f.stated_registration || selected.registration_number || "",
          }));
        }
        await ensureClaim();
      } else if (step < 7) {
        await persistDraft();
      }
      setStep((s) => Math.min(s + 1, STEPS.length - 1));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save this step.");
    } finally {
      setSaving(false);
    }
  }

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    const list = Array.from(files);
    const clientGps = await firstGpsFromFiles(list);
    setPhotoGpsHint(
      clientGps
        ? `GPS found in the selected photo: ${clientGps.latitude.toFixed(5)}, ${clientGps.longitude.toFixed(5)}`
        : "No GPS in these files. Choose original photos from your camera roll — screenshots and WhatsApp forwards usually have location removed.",
    );
    const current = await persistDraft();
    const data = new FormData();
    list.forEach((f) => data.append("files", f));
    data.append("image_role", role);
    const uploaded = await post<ClaimImage[]>(`/api/v1/claims/${current.id}/images`, data);
    const fresh = await get<ClaimDetail>(`/api/v1/claims/${current.id}`);
    setClaim(fresh);
    applyLocationFromClaim(fresh);
    if (uploaded[0]) setAnnotating(uploaded[0]);
  }

  async function saveAnnotations() {
    if (!claim || !annotating) return;
    await post(`/api/v1/claims/${claim.id}/images/${annotating.id}/annotations`, {
      regions,
      replace_existing: true,
    });
    setClaim(await get<ClaimDetail>(`/api/v1/claims/${claim.id}`));
    setAnnotating(null);
    setRegions([]);
  }

  async function submit() {
    setSaving(true);
    setError("");
    try {
      const current = await persistDraft();
      await post(`/api/v1/claims/${current.id}/submit`);
      router.push(`/client/claims/${current.id}/processing`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Submission failed.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Report an accident</h1>
        <p className="text-sm text-slate-500">Fill in what you know. An agent will review this report. Optional fields can be left blank.</p>
      </div>
      <ol className="grid grid-cols-4 gap-2 text-[11px] font-semibold uppercase tracking-wide sm:grid-cols-8">
        {STEPS.map((label, i) => (
          <li key={label} className={`rounded-lg px-2 py-2 text-center ${i === step ? "bg-navy-900 text-white" : i < step ? "bg-accent-500/20 text-accent-700" : "bg-white text-slate-400"}`}>
            {i + 1}
            <span className="mt-1 block truncate normal-case tracking-normal">{label}</span>
          </li>
        ))}
      </ol>

      <div className="card p-5">
        {step === 0 && (
          <div className="space-y-3">
            <p className="font-semibold">Select a vehicle from your garage, or skip and type details next.</p>
            <select className="input" value={form.vehicle_id} onChange={(e) => setForm({ ...form, vehicle_id: e.target.value })}>
              <option value="">I&apos;ll enter details manually</option>
              {vehicles.map((v) => (
                <option key={v.id} value={v.id}>{v.display_name} {v.registration_number || ""}</option>
              ))}
            </select>
          </div>
        )}

        {step === 1 && (
          <div className="grid gap-3 sm:grid-cols-2">
            {[
              ["stated_make", "Make"],
              ["stated_model", "Model"],
              ["stated_year", "Year"],
              ["stated_color", "Colour"],
              ["stated_registration", "Registration"],
            ].map(([key, label]) => (
              <label key={key}>
                <span className="label">{label}</span>
                <input className="input" value={(form as Record<string, string>)[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })} />
              </label>
            ))}
            <label className="sm:col-span-2">
              <span className="label">Tell us about your vehicle</span>
              <textarea className="input min-h-24" value={form.customer_vehicle_description} onChange={(e) => setForm({ ...form, customer_vehicle_description: e.target.value })} placeholder="Toyota Prius 2018, silver. Involved in an accident yesterday." />
            </label>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-4">
            <label>
              <span className="label">Describe what happened</span>
              <textarea className="input min-h-32" value={form.accident_description} onChange={(e) => setForm({ ...form, accident_description: e.target.value })} placeholder="I was driving near Colombo when another vehicle hit the front-left side..." />
            </label>
            <p className="text-sm font-semibold">Which parts do you think are damaged?</p>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {parts.slice(0, 12).map((p) => (
                <label key={p.code} className="flex items-center gap-2 rounded-xl border border-slate-200 px-3 py-2 text-sm">
                  <input
                    type="checkbox"
                    checked={form.reported_parts.includes(p.code)}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        reported_parts: e.target.checked
                          ? [...form.reported_parts, p.code]
                          : form.reported_parts.filter((c) => c !== p.code),
                      })
                    }
                  />
                  {p.display_name}
                </label>
              ))}
            </div>
            <label>
              <span className="label">Additional parts (free text)</span>
              <input className="input" value={form.free_text_parts} onChange={(e) => setForm({ ...form, free_text_parts: e.target.value })} />
            </label>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-4">
            <div className="rounded-xl bg-slate-50 p-4 text-sm">
              <p className="font-semibold">📸 Photograph the whole vehicle, then the damage.</p>
              <ul className="mt-2 list-disc pl-5 text-slate-600">
                <li>Keep the vehicle visible and in focus</li>
                <li>Use good lighting and avoid heavy crop of the damaged area</li>
                <li>Close-ups should still show surrounding bodywork</li>
              </ul>
            </div>
            <p className="text-sm text-slate-600">
              Choose original photos from your camera roll. Location is read from the GPS stored in the file — you will not need to type it.
            </p>
            <label>
              <span className="label">This photo is</span>
              <select className="input" value={role} onChange={(e) => setRole(e.target.value as typeof role)}>
                {ROLES.map((r) => <option key={r}>{r}</option>)}
              </select>
            </label>
            <div className="flex flex-wrap gap-2">
              <label className="btn-primary cursor-pointer">
                Choose from gallery
                <input
                  className="hidden"
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  multiple
                  onChange={(e) => {
                    void upload(e.target.files);
                    e.target.value = "";
                  }}
                />
              </label>
              <label className="btn-ghost cursor-pointer">
                Take photo
                <input
                  className="hidden"
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  capture="environment"
                  onChange={(e) => {
                    void upload(e.target.files);
                    e.target.value = "";
                  }}
                />
              </label>
            </div>
            {photoGpsHint && <p className="text-sm text-slate-600">{photoGpsHint}</p>}
            <div className="grid grid-cols-3 gap-2">
              {claim?.images.map((img) => (
                <button key={img.id} type="button" className="overflow-hidden rounded-xl border" onClick={() => setAnnotating(img)}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={img.url || ""} alt="" className="h-24 w-full object-cover" />
                  <p className="px-2 py-1 text-[10px] uppercase text-slate-500">{img.image_role}</p>
                  {img.image_metadata?.gps_latitude != null && img.image_metadata?.gps_longitude != null && (
                    <p className="px-2 pb-1 text-[10px] text-accent-700">GPS</p>
                  )}
                </button>
              ))}
            </div>
          </div>
        )}

        {step === 4 && (
          <div className="space-y-3">
            <p className="text-sm text-slate-600">Select a photo and draw around the damaged area.</p>
            <div className="flex flex-wrap gap-2">
              {claim?.images.map((img) => (
                <button key={img.id} type="button" className={`rounded-lg border px-2 py-1 text-xs ${annotating?.id === img.id ? "border-navy-900" : ""}`} onClick={() => { setAnnotating(img); setRegions([]); }}>
                  {img.image_role}
                </button>
              ))}
            </div>
            {annotating?.url && (
              <>
                <AnnotationCanvas src={annotating.url} onChange={setRegions} />
                <label>
                  <span className="label">What is damaged in this photo?</span>
                  <input className="input" defaultValue={annotating.customer_note || ""} onBlur={async (e) => {
                    const data = new FormData();
                    data.append("files", new Blob());
                    await patch(`/api/v1/claims/${claim!.id}`, {});
                    annotating.customer_note = e.target.value;
                  }} />
                </label>
                <button type="button" className="btn-primary" onClick={saveAnnotations}>Save markings</button>
              </>
            )}
          </div>
        )}

        {step === 5 && (
          <MapPicker value={location} onChange={setLocation} photoCount={claim?.images.length || 0} />
        )}

        {step === 6 && (
          <div className="space-y-3 text-sm">
            <p><span className="text-slate-500">Vehicle:</span> {[form.stated_make, form.stated_model, form.stated_year].filter(Boolean).join(" ") || "To be identified from photographs"}</p>
            <p><span className="text-slate-500">Registration:</span> {form.stated_registration || "Not provided"}</p>
            <p><span className="text-slate-500">Photos:</span> {claim?.images.length || 0}</p>
            <p>
              <span className="text-slate-500">Location:</span>{" "}
              {location
                ? `${location.latitude.toFixed(5)}, ${location.longitude.toFixed(5)} (${location.source === "EXIF_GPS" ? "from photos" : location.source === "DEVICE_GPS" ? "device GPS" : "entered"})`
                : "Not obtained"}
            </p>
            <p><span className="text-slate-500">Reported parts:</span> {form.reported_parts.join(", ") || "None selected"}</p>
            <p className="whitespace-pre-wrap text-slate-700">{form.accident_description || "No written description."}</p>
          </div>
        )}

        {step === 7 && (
          <div className="space-y-3">
            <p className="text-sm">Submitting starts AI analysis in the background. You will see live progress. The result is a <strong>preliminary estimate</strong>, not a settlement.</p>
            <button className="btn-accent w-full" disabled={saving} onClick={submit}>Submit claim</button>
          </div>
        )}

        {error && <p className="mt-4 text-sm text-rose-600">{error}</p>}
      </div>

      <div className="flex justify-between">
        <button className="btn-ghost" disabled={step === 0} onClick={() => setStep((s) => s - 1)}>Back</button>
        {step < 7 && (
          <button className="btn-primary" disabled={saving} onClick={next}>{saving ? "Saving…" : "Continue"}</button>
        )}
      </div>
    </div>
  );
}
