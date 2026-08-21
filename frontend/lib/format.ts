export function lkr(value: number | null | undefined, currency = "LKR") {
  if (value == null) return "Unavailable";
  return `${currency} ${Math.round(value).toLocaleString("en-LK")}`;
}

export function moneyRange(range: {
  status: string;
  min: number | null;
  max: number | null;
  currency: string | null;
} | null) {
  if (!range || range.status !== "AVAILABLE" || range.min == null || range.max == null) {
    return "Unavailable — manual verification required";
  }
  const c = range.currency || "LKR";
  if (range.min === range.max) return lkr(range.min, c);
  return `${lkr(range.min, c)} – ${lkr(range.max, c)}`;
}

export function pct(value: number | null | undefined) {
  if (value == null) return "—";
  return `${Math.round(value * 100)}%`;
}

export function prettyStatus(status: string) {
  return status.replaceAll("_", " ").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
}

export function formatWhen(iso: string | null | undefined) {
  if (!iso) return "Unavailable";
  return new Date(iso).toLocaleString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
