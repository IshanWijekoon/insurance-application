import { lkr, moneyRange, pct } from "@/lib/format";
import type { Estimate } from "@/lib/types";
import { Disclaimer } from "./Badge";

export function EstimateBreakdown({ estimate }: { estimate: Estimate }) {
  return (
    <div className="card overflow-hidden">
      <div className="border-b border-slate-100 px-5 py-4">
        <h3 className="font-semibold">AI damage estimate</h3>
        <p className="mt-1 text-xs text-slate-500">Every figure traces to a researched source or a published labour/paint rate.</p>
      </div>
      <div className="divide-y divide-slate-100">
        {estimate.lines.map((line) => (
          <details key={line.canonical_part} className="px-5 py-3">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-3">
              <div>
                <p className="text-sm font-semibold">{line.display_name}</p>
                <p className="text-xs text-slate-500">
                  {line.action} {line.part_price_available ? "" : "· part price unavailable"}
                </p>
              </div>
              <p className="text-sm font-semibold tabular-nums">
                {lkr(line.line_min, line.currency)} – {lkr(line.line_max, line.currency)}
              </p>
            </summary>
            <p className="mt-2 text-xs leading-relaxed text-slate-600">{line.basis}</p>
          </details>
        ))}
      </div>
      <div className="grid gap-3 border-t border-slate-100 px-5 py-4 sm:grid-cols-3">
        <div>
          <p className="text-xs text-slate-500">Labour</p>
          <p className="text-sm font-semibold">{lkr(estimate.labour_min)} – {lkr(estimate.labour_max)}</p>
        </div>
        <div>
          <p className="text-xs text-slate-500">Paint</p>
          <p className="text-sm font-semibold">{lkr(estimate.paint_min)} – {lkr(estimate.paint_max)}</p>
        </div>
        <div>
          <p className="text-xs text-slate-500">Total (preliminary)</p>
          <p className="text-lg font-bold text-navy-900">{moneyRange(estimate.total)}</p>
          {estimate.total.confidence != null && (
            <p className="text-xs text-slate-500">Confidence {pct(estimate.total.confidence)}</p>
          )}
        </div>
      </div>
      {estimate.is_partial && (
        <p className="px-5 pb-3 text-xs text-amber-800">
          Incomplete: {estimate.unpriced_parts.join(", ") || "some parts"} could not be priced from approved sources.
        </p>
      )}
      {estimate.damage_to_value_ratio != null && (
        <p className="px-5 pb-3 text-xs text-slate-500">
          Damage-to-value ratio {pct(estimate.damage_to_value_ratio)} — an assessment signal only, never an automatic total-loss decision.
        </p>
      )}
      <div className="px-5 pb-5">
        <Disclaimer>{estimate.disclaimer}</Disclaimer>
      </div>
    </div>
  );
}
