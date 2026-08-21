export type GpsFix = { latitude: number; longitude: number };

function isJpeg(bytes: Uint8Array): boolean {
  return bytes.length > 2 && bytes[0] === 0xff && bytes[1] === 0xd8;
}

function readAscii(view: DataView, offset: number, length: number): string {
  let out = "";
  for (let i = 0; i < length; i++) {
    const code = view.getUint8(offset + i);
    if (code === 0) break;
    out += String.fromCharCode(code);
  }
  return out;
}

function gpsFromJpeg(buffer: ArrayBuffer): GpsFix | null {
  const bytes = new Uint8Array(buffer);
  if (!isJpeg(bytes)) return null;
  const view = new DataView(buffer);
  let offset = 2;
  while (offset + 4 < view.byteLength) {
    if (view.getUint8(offset) !== 0xff) break;
    const marker = view.getUint8(offset + 1);
    const size = view.getUint16(offset + 2, false);
    if (marker === 0xe1 && size >= 8) {
      const start = offset + 4;
      if (readAscii(view, start, 4) === "Exif") {
        const fix = gpsFromTiff(view, start + 6);
        if (fix) return fix;
      }
    }
    if (marker === 0xda) break;
    offset += 2 + size;
  }
  return null;
}

function gpsFromTiff(view: DataView, tiffStart: number): GpsFix | null {
  if (tiffStart + 8 > view.byteLength) return null;
  const endian = readAscii(view, tiffStart, 2);
  const little = endian === "II";
  if (!little && endian !== "MM") return null;
  const magic = view.getUint16(tiffStart + 2, little);
  if (magic !== 42) return null;
  const ifd0 = tiffStart + view.getUint32(tiffStart + 4, little);
  const gpsOffset = findTagOffset(view, ifd0, tiffStart, little, 0x8825);
  if (gpsOffset == null) return null;
  return readGpsIfd(view, tiffStart + gpsOffset, tiffStart, little);
}

function findTagOffset(
  view: DataView,
  ifd: number,
  tiffStart: number,
  little: boolean,
  tagId: number,
): number | null {
  if (ifd + 2 > view.byteLength) return null;
  const count = view.getUint16(ifd, little);
  for (let i = 0; i < count; i++) {
    const entry = ifd + 2 + i * 12;
    if (entry + 12 > view.byteLength) return null;
    if (view.getUint16(entry, little) !== tagId) continue;
    return view.getUint32(entry + 8, little);
  }
  return null;
}

function readGpsIfd(view: DataView, ifd: number, tiffStart: number, little: boolean): GpsFix | null {
  if (ifd + 2 > view.byteLength) return null;
  const count = view.getUint16(ifd, little);
  let latRef = "N";
  let lngRef = "E";
  let lat: number | null = null;
  let lng: number | null = null;
  for (let i = 0; i < count; i++) {
    const entry = ifd + 2 + i * 12;
    if (entry + 12 > view.byteLength) return null;
    const tag = view.getUint16(entry, little);
    const type = view.getUint16(entry + 2, little);
    const components = view.getUint32(entry + 4, little);
    const valueOffset = entry + 8;
    if (tag === 1 && type === 2) {
      latRef = String.fromCharCode(view.getUint8(valueOffset)) || "N";
    } else if (tag === 3 && type === 2) {
      lngRef = String.fromCharCode(view.getUint8(valueOffset)) || "E";
    } else if (tag === 2 && type === 5 && components === 3) {
      lat = readDms(view, tiffStart + view.getUint32(valueOffset, little), little);
    } else if (tag === 4 && type === 5 && components === 3) {
      lng = readDms(view, tiffStart + view.getUint32(valueOffset, little), little);
    }
  }
  if (lat == null || lng == null || (lat === 0 && lng === 0)) return null;
  if (latRef.toUpperCase().startsWith("S")) lat = -Math.abs(lat);
  if (lngRef.toUpperCase().startsWith("W")) lng = -Math.abs(lng);
  if (lat < -90 || lat > 90 || lng < -180 || lng > 180) return null;
  return { latitude: Number(lat.toFixed(7)), longitude: Number(lng.toFixed(7)) };
}

function readDms(view: DataView, offset: number, little: boolean): number | null {
  if (offset + 24 > view.byteLength) return null;
  const parts = [0, 1, 2].map((i) => {
    const num = view.getUint32(offset + i * 8, little);
    const den = view.getUint32(offset + i * 8 + 4, little);
    return den ? num / den : 0;
  });
  return parts[0] + parts[1] / 60 + parts[2] / 3600;
}

export async function gpsFromImageFile(file: File): Promise<GpsFix | null> {
  try {
    return gpsFromJpeg(await file.arrayBuffer());
  } catch {
    return null;
  }
}

export async function firstGpsFromFiles(files: File[]): Promise<GpsFix | null> {
  for (const file of files) {
    const fix = await gpsFromImageFile(file);
    if (fix) return fix;
  }
  return null;
}
