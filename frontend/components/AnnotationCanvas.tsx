"use client";

import { useEffect, useRef, useState } from "react";

type Tool = "RECTANGLE" | "POLYGON" | "CIRCLE" | "FREEHAND";

export type Region = {
  annotation_type: Tool;
  label: string;
  points: number[][];
};

export function AnnotationCanvas({
  src,
  onChange,
}: {
  src: string;
  onChange: (regions: Region[]) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);
  const [tool, setTool] = useState<Tool>("RECTANGLE");
  const [regions, setRegions] = useState<Region[]>([]);
  const [draft, setDraft] = useState<number[][]>([]);
  const history = useRef<Region[][]>([]);

  function redraw(extra: number[][] = []) {
    const canvas = canvasRef.current;
    const img = imgRef.current;
    if (!canvas || !img) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    ctx.drawImage(img, 0, 0);
    ctx.strokeStyle = "#12a78e";
    ctx.lineWidth = Math.max(4, img.naturalWidth / 200);
    ctx.fillStyle = "rgba(18,167,142,0.18)";
    for (const region of [...regions, extra.length ? { annotation_type: tool, label: "draft", points: extra } : null]) {
      if (!region || region.points.length === 0) continue;
      drawRegion(ctx, region.annotation_type as Tool, region.points);
    }
  }

  function drawRegion(ctx: CanvasRenderingContext2D, type: Tool, points: number[][]) {
    ctx.beginPath();
    if (type === "RECTANGLE" && points.length >= 2) {
      const [a, b] = points;
      ctx.rect(a[0], a[1], b[0] - a[0], b[1] - a[1]);
    } else if (type === "CIRCLE" && points.length >= 2) {
      const [a, b] = points;
      const r = Math.hypot(b[0] - a[0], b[1] - a[1]);
      ctx.arc(a[0], a[1], r, 0, Math.PI * 2);
    } else {
      ctx.moveTo(points[0][0], points[0][1]);
      points.slice(1).forEach((p) => ctx.lineTo(p[0], p[1]));
      if (type === "POLYGON") ctx.closePath();
    }
    ctx.fill();
    ctx.stroke();
  }

  function pos(e: React.PointerEvent) {
    const canvas = canvasRef.current!;
    const rect = canvas.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * canvas.width;
    const y = ((e.clientY - rect.top) / rect.height) * canvas.height;
    return [x, y];
  }

  function commit(points: number[][]) {
    history.current.push(regions);
    const next = [...regions, { annotation_type: tool, label: "customer_selected_damage", points }];
    setRegions(next);
    onChange(next);
    setDraft([]);
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {(["RECTANGLE", "CIRCLE", "POLYGON", "FREEHAND"] as Tool[]).map((t) => (
          <button key={t} className={tool === t ? "btn-primary !py-1.5 text-xs" : "btn-ghost !py-1.5 text-xs"} onClick={() => setTool(t)}>
            {t.toLowerCase()}
          </button>
        ))}
        <button
          className="btn-ghost !py-1.5 text-xs"
          onClick={() => {
            const prev = history.current.pop();
            if (prev) {
              setRegions(prev);
              onChange(prev);
            }
          }}
        >
          Undo
        </button>
        <button
          className="btn-ghost !py-1.5 text-xs"
          onClick={() => {
            history.current.push(regions);
            setRegions([]);
            onChange([]);
          }}
        >
          Clear
        </button>
      </div>
      <canvas
        ref={canvasRef}
        className="w-full touch-none rounded-xl border border-slate-200 bg-slate-100"
        onPointerDown={(e) => {
          const p = pos(e);
          if (tool === "POLYGON") {
            const next = [...draft, p];
            setDraft(next);
            redraw(next);
            return;
          }
          setDraft([p]);
        }}
        onPointerMove={(e) => {
          if (!draft.length || tool === "POLYGON") return;
          if (tool === "FREEHAND") {
            const next = [...draft, pos(e)];
            setDraft(next);
            redraw(next);
            return;
          }
          redraw([draft[0], pos(e)]);
        }}
        onPointerUp={(e) => {
          if (tool === "POLYGON") return;
          if (draft.length) commit(tool === "FREEHAND" ? draft : [draft[0], pos(e)]);
        }}
        onDoubleClick={() => {
          if (tool === "POLYGON" && draft.length >= 3) commit(draft);
        }}
      />
      <img
        ref={(el) => {
          imgRef.current = el;
        }}
        src={src}
        alt=""
        className="hidden"
        onLoad={() => redraw()}
      />
      <p className="text-xs text-slate-500">Draw around damaged areas. Double-tap to close a polygon.</p>
    </div>
  );
}

export function useImageObjectUrl() {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);
  return { url, setUrl };
}
