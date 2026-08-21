"use client";

import { useEffect, useState } from "react";

export type LocationValue = {
  latitude: number;
  longitude: number;
  source: "EXIF_GPS" | "DEVICE_GPS" | "CUSTOMER_SELECTED";
};

function sourceLabel(source: LocationValue["source"]) {
  if (source === "EXIF_GPS") return "Taken from the GPS tag in your photographs";
  if (source === "DEVICE_GPS") return "Taken from this device’s GPS";
  return "Entered by you";
}

export function MapPicker({
  value,
  onChange,
  photoCount = 0,
}: {
  value: LocationValue | null;
  onChange: (v: LocationValue) => void;
  photoCount?: number;
}) {
  const [manual, setManual] = useState({
    lat: value?.latitude?.toString() ?? "",
    lng: value?.longitude?.toString() ?? "",
  });
  const [showOverride, setShowOverride] = useState(false);

  useEffect(() => {
    if (!value) return;
    setManual({ lat: String(value.latitude), lng: String(value.longitude) });
  }, [value]);

  const fromPhotos = value?.source === "EXIF_GPS";

  return (
    <div className="space-y-3">
      {fromPhotos ? (
        <div className="rounded-xl bg-accent-500/15 px-4 py-3 text-sm">
          <p className="font-semibold">Location came from your photos</p>
          <p className="mt-1 text-slate-600">
            {sourceLabel("EXIF_GPS")}. You do not need to type coordinates.
          </p>
          <p className="mt-1 font-mono text-xs text-slate-500">
            {value.latitude.toFixed(6)}, {value.longitude.toFixed(6)}
          </p>
        </div>
      ) : (
        <div className="rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-600">
          {photoCount > 0
            ? "None of the uploaded photos contained GPS. Use original camera-roll pictures (not screenshots or WhatsApp forwards), or fall back to this device’s GPS."
            : "Upload accident photos first. Location is read from the GPS stored in those files."}
        </div>
      )}

      {value && (
        <iframe
          title="Accident location"
          className="h-56 w-full rounded-xl border border-slate-200"
          src={`https://www.openstreetmap.org/export/embed.html?bbox=${value.longitude - 0.02}%2C${value.latitude - 0.02}%2C${value.longitude + 0.02}%2C${value.latitude + 0.02}&layer=mapnik&marker=${value.latitude}%2C${value.longitude}`}
        />
      )}

      {!fromPhotos && (
        <button
          className="btn-primary"
          type="button"
          onClick={() => {
            navigator.geolocation.getCurrentPosition(
              (pos) => {
                onChange({
                  latitude: pos.coords.latitude,
                  longitude: pos.coords.longitude,
                  source: "DEVICE_GPS",
                });
              },
              () => alert("Device location is unavailable. Choose original photos from your camera roll instead."),
            );
          }}
        >
          Use device GPS
        </button>
      )}

      <button className="btn-ghost text-xs" type="button" onClick={() => setShowOverride((v) => !v)}>
        {showOverride ? "Hide manual entry" : "Enter a different location"}
      </button>

      {showOverride && (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            <label>
              <span className="label">Latitude</span>
              <input className="input" value={manual.lat} onChange={(e) => setManual({ ...manual, lat: e.target.value })} />
            </label>
            <label>
              <span className="label">Longitude</span>
              <input className="input" value={manual.lng} onChange={(e) => setManual({ ...manual, lng: e.target.value })} />
            </label>
          </div>
          <button
            type="button"
            className="btn-ghost"
            onClick={() => {
              const latitude = Number(manual.lat);
              const longitude = Number(manual.lng);
              if (Number.isNaN(latitude) || Number.isNaN(longitude)) return;
              onChange({ latitude, longitude, source: "CUSTOMER_SELECTED" });
            }}
          >
            Save map location
          </button>
        </>
      )}

      <p className="text-xs text-slate-500">
        Location is only stored when it is actually obtained. Photo GPS is preferred over device GPS or a pin you drop.
      </p>
    </div>
  );
}
