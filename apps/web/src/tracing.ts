export type PixelRect = [number, number, number, number];
export type TraceRoom = { name: string; kind: string; rect: PixelRect };
export type TraceInput = {
  bbox: PixelRect;
  rooms: TraceRoom[];
  wall_thickness_mm: number;
  wall_height_mm: number;
};

export function rectInput(values: string[], bounds: PixelRect, integer = false): PixelRect | null {
  if (values.length !== 4 || values.some((v) => !v.trim())) return null;
  const rect = values.map(Number) as PixelRect;
  if (rect.some((v) => !Number.isFinite(v) || (integer && !Number.isInteger(v)))) return null;
  const [x, y, w, h] = rect;
  if (w <= 0 || h <= 0 || x < bounds[0] || y < bounds[1] ||
    x + w > bounds[0] + bounds[2] + 1e-6 || y + h > bounds[1] + bounds[3] + 1e-6) return null;
  return rect;
}

export function dragRect(start: [number, number], end: [number, number], integer = false): PixelRect {
  const round = (n: number) => Math.round(n * 1e6) / 1e6;
  const x = integer ? Math.floor(Math.min(start[0], end[0])) : round(Math.min(start[0], end[0]));
  const y = integer ? Math.floor(Math.min(start[1], end[1])) : round(Math.min(start[1], end[1]));
  const right = integer ? Math.ceil(Math.max(start[0], end[0])) : round(Math.max(start[0], end[0]));
  const bottom = integer ? Math.ceil(Math.max(start[1], end[1])) : round(Math.max(start[1], end[1]));
  return [x, y, round(right - x), round(bottom - y)];
}

export function traceError(rooms: TraceRoom[], bbox: PixelRect | null): string {
  if (!bbox) return "户型区域无效";
  if (!rooms.length) return "尚无人工房间";
  if (rooms.length > 64) return "房间数量不得超过 64";
  for (let i = 0; i < rooms.length; i++) {
    const room = rooms[i];
    if (!room.name.trim() || room.name.length > 120) return "房间名称须为 1 至 120 字符";
    if (!rectInput(room.rect.map(String), bbox)) return `${room.name} 超出户型区域`;
    for (const other of rooms.slice(i + 1)) {
      const [x, y, w, h] = room.rect;
      const [ox, oy, ow, oh] = other.rect;
      if (Math.min(x + w, ox + ow) - Math.max(x, ox) > 1e-6 &&
        Math.min(y + h, oy + oh) - Math.max(y, oy) > 1e-6) return `${room.name} 与 ${other.name} 重叠`;
    }
  }
  return "";
}
