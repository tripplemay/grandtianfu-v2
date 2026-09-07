import { useEffect, useRef, useState, type PointerEvent } from "react";
import { Crop, FileImage, LoaderCircle, MousePointer2, PencilRuler, Plus, Redo2, Scan, Trash2, Undo2, X } from "lucide-react";
import { roiCandidates, type IngestResult } from "./ingestion";
import { openingRect, wallRect, type SpatialModel } from "./model";
import { dragRect, rectInput, traceError, type PixelRect, type TraceInput, type TraceRoom } from "./tracing";

type Rooms = { current: TraceRoom[]; past: TraceRoom[][]; future: TraceRoom[][] };
const axes = ["x", "y", "w", "h"];
const kinds = { unknown: "未分类", living: "客厅", dining: "餐厅", bedroom: "卧室", kitchen: "厨房", bathroom: "卫生间", balcony: "阳台", corridor: "走廊", other: "其他" };
const emptyFields = ["", "", "", ""];

function RectFields({ prefix, values, onChange, disabled }: {
  prefix: string; values: string[]; onChange: (values: string[]) => void; disabled: boolean;
}) {
  return <div className="pixel-fields">{axes.map((axis, index) => <label key={axis}>
    {axis.toUpperCase()} (px)
    <input type="number" step="any" aria-label={`${prefix} ${axis}`} data-testid={`${prefix}-${axis}`}
      value={values[index]} disabled={disabled} onChange={(event) => onChange(values.map((v, i) => i === index ? event.target.value : v))} />
  </label>)}</div>;
}

export function SourceEditor({ model, result, onCrop, onTrace, onDirtyChange, disabled = false }: {
  model: SpatialModel; result: IngestResult; disabled?: boolean;
  onCrop: (bbox: PixelRect) => Promise<IngestResult>;
  onTrace: (input: TraceInput) => Promise<IngestResult>;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const [mode, setMode] = useState("overlay");
  const initial = model.ingest?.trace as TraceInput | undefined;
  const [tool, setTool] = useState("inspect");
  const [dimensions, setDimensions] = useState({ width: 1, height: 1 });
  const [broken, setBroken] = useState(false);
  const [readySrc, setReadySrc] = useState("");
  const [roiFields, setRoiFields] = useState<string[]>(initial?.bbox.map(String) ?? emptyFields);
  const [selectedRoi, setSelectedRoi] = useState<string | null>(null);
  const [rooms, setRooms] = useState<Rooms>({ current: initial?.rooms ?? [], past: [], future: [] });
  const [selectedRoom, setSelectedRoom] = useState<number | null>(null);
  const [roomFields, setRoomFields] = useState<string[]>(emptyFields);
  const [roomName, setRoomName] = useState("");
  const [roomKind, setRoomKind] = useState("unknown");
  const [thickness, setThickness] = useState(initial ? String(initial.wall_thickness_mm) : "");
  const [height, setHeight] = useState(initial ? String(initial.wall_height_mm) : "");
  const [pending, setPending] = useState<"crop" | "trace" | null>(null);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<PixelRect | null>(null);
  const start = useRef<{ point: [number, number]; pointer: number } | null>(null);
  const scale = model.ingest?.mm_per_pixel ?? 0;
  const pixelSize = model.ingest?.pixel_size as { width: number; height: number } | undefined;
  const bounds: PixelRect = [0, 0, pixelSize?.width ?? dimensions.width, pixelSize?.height ?? dimensions.height];
  const bbox = rectInput(roiFields, bounds, true);
  const roomRect = bbox ? rectInput(roomFields, bbox) : null;
  const candidates = roiCandidates(model);
  const src = mode === "source" ? result.source_url : mode === "normalized"
    ? result.preprocessed_url : (result.overlay_url ?? result.parent_preprocessed_url ?? result.preprocessed_url);
  const inactive = disabled || pending !== null;
  const roomEditPending = selectedRoom === null ? roomFields.some(Boolean) || !!roomName.trim() : !!rooms.current[selectedRoom] && (
    JSON.stringify(roomFields) !== JSON.stringify(rooms.current[selectedRoom].rect.map(String)) ||
    roomName !== rooms.current[selectedRoom].name || roomKind !== rooms.current[selectedRoom].kind);
  const topologyError = traceError(rooms.current, bbox);
  const validHeights = thickness.trim() !== "" && height.trim() !== "" &&
    Number.isFinite(Number(thickness)) && Number.isFinite(Number(height)) && Number(thickness) > 0 && Number(height) > 0;
  const parentId = model.ingest?.parent_ingest_id;
  const aspect = mode === "overlay" ? bounds[2] / bounds[3] : dimensions.width / dimensions.height;
  const changed = JSON.stringify(rooms.current) !== JSON.stringify(initial?.rooms ?? []) ||
    roomEditPending || (rooms.current.length > 0 && (
      JSON.stringify(roiFields) !== JSON.stringify(initial?.bbox.map(String) ?? emptyFields) ||
      thickness !== (initial ? String(initial.wall_thickness_mm) : "") || height !== (initial ? String(initial.wall_height_mm) : "")));

  useEffect(() => {
    onDirtyChange(changed);
  }, [onDirtyChange, changed]);
  useEffect(() => () => onDirtyChange(false), [onDirtyChange]);

  useEffect(() => {
    setBroken(false);
    setError("");
  }, [src]);

  function saveRooms(next: TraceRoom[]) {
    setRooms((value) => ({ current: next, past: [...value.past, value.current].slice(-100), future: [] }));
    setError("");
  }
  function selectRoom(index: number | null) {
    setSelectedRoom(index);
    const room = index === null ? null : rooms.current[index];
    setRoomFields(room ? room.rect.map(String) : emptyFields);
    setRoomName(room?.name ?? "");
    setRoomKind(room?.kind ?? "unknown");
  }
  function editRoi(values: string[]) {
    setRoiFields(values);
    setSelectedRoi(null);
    setError("");
  }
  function commitRoom() {
    if (!roomRect || !roomName.trim() || roomName.length > 120 || inactive) return;
    const room = { name: roomName.trim(), kind: roomKind, rect: roomRect };
    const next = selectedRoom === null ? [...rooms.current, room] : rooms.current.map((r, i) => i === selectedRoom ? room : r);
    const issue = traceError(next, bbox);
    if (issue) { setError(issue); return; }
    saveRooms(next);
    setSelectedRoom(next.length && selectedRoom === null ? next.length - 1 : selectedRoom);
    setRoomName(room.name);
    setRoomFields(room.rect.map(String));
  }
  async function submit(action: "crop" | "trace") {
    if (inactive || !bbox || (action === "trace" && (topologyError || !validHeights || roomEditPending))) return;
    setPending(action);
    setError("");
    try {
      if (action === "crop") await onCrop(bbox);
      else await onTrace({ bbox, rooms: rooms.current, wall_thickness_mm: Number(thickness), wall_height_mm: Number(height) });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally { setPending(null); }
  }
  function point(event: PointerEvent<SVGSVGElement>): [number, number] {
    const box = event.currentTarget.getBoundingClientRect();
    return [Math.max(0, Math.min(bounds[2], (event.clientX - box.left) / box.width * bounds[2])),
      Math.max(0, Math.min(bounds[3], (event.clientY - box.top) / box.height * bounds[3]))];
  }
  function begin(event: PointerEvent<SVGSVGElement>) {
    if (inactive || tool === "inspect" || readySrc !== src || broken || !event.isPrimary || event.button !== 0 || (tool === "room" && (!bbox || roomEditPending))) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    start.current = { point: point(event), pointer: event.pointerId };
    setPreview(null);
  }
  function move(event: PointerEvent<SVGSVGElement>) {
    if (start.current?.pointer !== event.pointerId) return;
    setPreview(dragRect(start.current.point, point(event), tool === "roi"));
  }
  function finish(event: PointerEvent<SVGSVGElement>) {
    if (!start.current || start.current.pointer !== event.pointerId) return;
    const rect = dragRect(start.current.point, point(event), tool === "roi");
    start.current = null;
    setPreview(null);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    if (rect[2] < 1 || rect[3] < 1) return;
    if (tool === "roi") editRoi(rect.map(String));
    else {
      const next = [...rooms.current, { name: `房间 ${rooms.current.length + 1}`, kind: "unknown", rect }];
      const issue = traceError(next, bbox);
      if (issue) { setError(issue); return; }
      saveRooms(next);
      setSelectedRoom(next.length - 1);
      setRoomFields(rect.map(String));
      setRoomName(next[next.length - 1].name);
      setRoomKind("unknown");
    }
  }
  function undo(redo = false) {
    setRooms((value) => {
      const from = redo ? value.future : value.past;
      if (!from.length) return value;
      return redo
        ? { current: from[0], past: [...value.past, value.current], future: from.slice(1) }
        : { current: from[from.length - 1], past: from.slice(0, -1), future: [value.current, ...value.future] };
    });
    selectRoom(null);
    setError("");
  }
  return <div className="ingest-source source-editor" data-testid="ingest-source">
    <div className="source-toolbar" role="group" aria-label="源图视图">
      {[["source", "原始位图"], ["normalized", "规范化位图"], ["overlay", "候选叠加"]].map(([value, label]) =>
        <button type="button" key={value} className="source-tab" aria-pressed={mode === value} disabled={!!pending}
          onClick={() => { setMode(value); setBroken(false); }}>{label}</button>)}
      <span className="muted">{scale} mm/px</span>
    </div>
    <section className="roi-review" aria-label="人工选择户型区域">
      {initial && <p className={model.status === "confirmed" && model.review?.topology_confirmation ? "workflow-status" : "workflow-error"} role="status" data-testid="trace-topology-blocker">{model.status === "confirmed" && model.review?.topology_confirmation ? "人工描绘区域已确认" : "描图草稿待门窗、连通性与 merge 拓扑校核"}</p>}
      {typeof parentId === "string" && <p className="workflow-status" data-testid="roi-derived-draft">父任务 <code>{parentId.slice(0, 12)}</code> · 派生草稿</p>}
      <div className="roi-review-heading"><strong>户型区域</strong><span className="muted" data-testid="roi-count">{candidates.length} 个候选</span></div>
      {candidates.length ? <div className="roi-candidate-list" role="listbox" aria-label="户型区域候选">{candidates.map((c) =>
        <button key={c.id} type="button" role="option" aria-selected={c.id === selectedRoi} disabled={inactive}
          className={`roi-candidate ${c.id === selectedRoi ? "selected" : ""}`} data-testid={`roi-candidate-${c.id}`}
          onClick={() => { setRoiFields(c.evidence_bbox.map(String)); setSelectedRoi(c.id); setMode("overlay"); setError(""); }}>
          <span>候选 {c.rank ?? c.id} · {Math.round((c.confidence ?? 0) * 100)}%</span>
          <small>{c.evidence_bbox.join(", ")} px</small>
        </button>)}</div> : <p className="muted" data-testid="roi-empty">无区域候选</p>}
      <RectFields prefix="roi" values={roiFields} onChange={editRoi} disabled={inactive} />
      {roiFields.some(Boolean) && !bbox && <p className="workflow-error" role="alert">区域须为整图内的正整数尺寸</p>}
      <div className="roi-review-actions">
        <button type="button" className="icon-button" title="选取整图" aria-label="选取整图" disabled={inactive}
          onClick={() => { editRoi(bounds.map(String)); setMode("overlay"); }}><Scan size={18} /></button>
        <button type="button" className="button primary" data-testid="roi-crop-submit" disabled={!bbox || inactive || roomEditPending || rooms.current.length > 0}
          onClick={() => void submit("crop")}>{pending === "crop" ? <LoaderCircle size={16} className="spin" /> : <FileImage size={16} />}裁剪并重新识别</button>
        {selectedRoi && <span className="muted" data-testid="roi-selected-status">已选择候选区域</span>}
      </div>
      {pending && <p role="status" className="workflow-status" data-testid="roi-crop-status">{pending === "crop" ? "裁剪识别中" : "生成描图草稿中"}</p>}
      {error && <p role="alert" className="workflow-error" data-testid="roi-crop-error">{error}</p>}
    </section>
    <div className="trace-toolbar" role="group" aria-label="描图工具">
      {[["inspect", MousePointer2, "选择"], ["roi", Crop, "绘制户型区域"], ["room", PencilRuler, "绘制矩形房间"]].map(([value, Icon, label]) => {
        const Symbol = Icon as typeof Crop;
        return <button key={String(value)} type="button" className="icon-button" title={String(label)} aria-label={String(label)}
          aria-pressed={tool === value} disabled={inactive || (value === "room" && !bbox)} onClick={() => { setTool(String(value)); setMode("overlay"); }}><Symbol size={18} /></button>;
      })}
      <button className="icon-button" title="撤销描图" aria-label="撤销描图" disabled={inactive || !rooms.past.length} onClick={() => undo()}><Undo2 size={18} /></button>
      <button className="icon-button" title="重做描图" aria-label="重做描图" disabled={inactive || !rooms.future.length} onClick={() => undo(true)}><Redo2 size={18} /></button>
      <span className="muted">{rooms.current.length} 个人工房间</span>
    </div>
    <div className="source-image-scroll">
      {src && !broken ? <div className="source-image-frame" style={{ aspectRatio: String(aspect), maxWidth: `calc(max(160px, 100dvh - 360px) * ${aspect})`, margin: "0 auto" }}>
        <img src={src} alt={mode === "normalized" ? "规范化户型位图" : "原始户型位图"} draggable={false}
          onLoad={(e) => { setDimensions({ width: e.currentTarget.naturalWidth, height: e.currentTarget.naturalHeight }); setReadySrc(src); }} onError={() => setBroken(true)} />
        {mode === "overlay" && scale > 0 && readySrc === src && <svg className={`candidate-overlay trace-surface ${tool !== "inspect" ? "drawing" : ""}`} data-testid="candidate-overlay"
          viewBox={`0 0 ${bounds[2]} ${bounds[3]}`} aria-label="空间候选叠加"
          onPointerDown={begin} onPointerMove={move} onPointerUp={finish}
          onPointerCancel={() => { start.current = null; setPreview(null); }}>
          <g transform={`scale(${1 / scale})`} opacity={rooms.current.length ? 0.25 : 1}>
            {model.rooms.map((r) => <rect key={r.id} x={r.rect[0]} y={r.rect[1]} width={r.rect[2]} height={r.rect[3]} fill="#0c99601c" stroke="#16875c" strokeWidth={scale} />)}
            {model.walls.map((w) => <rect key={w.id} {...wallRect(w)} fill="#2259b566" />)}
            {model.openings.map((o) => { const wall = model.walls.find((w) => w.id === o.host_wall_id); return wall ? <rect key={o.id} {...openingRect(o, wall)} fill="#d42d7466" /> : null; })}
          </g>
          {candidates.map((c) => <rect key={c.id} data-testid={`roi-overlay-${c.id}`} x={c.evidence_bbox[0]} y={c.evidence_bbox[1]} width={c.evidence_bbox[2]} height={c.evidence_bbox[3]} fill="none" stroke="#a07028" strokeWidth={1} vectorEffect="non-scaling-stroke" strokeDasharray="5 4" />)}
          {bbox && <rect data-testid="manual-roi-overlay" x={bbox[0]} y={bbox[1]} width={bbox[2]} height={bbox[3]} fill="none" stroke="#bf7516" strokeWidth={2} vectorEffect="non-scaling-stroke" />}
          {rooms.current.map((r, index) => <rect key={index} data-testid={`trace-room-overlay-${index}`} x={r.rect[0]} y={r.rect[1]} width={r.rect[2]} height={r.rect[3]}
            fill={selectedRoom === index ? "#268f713d" : "#268f711a"} stroke="#136e59" strokeWidth={2} vectorEffect="non-scaling-stroke"
            onClick={() => { if (tool === "inspect" && !inactive && !roomEditPending) selectRoom(index); }} />)}
          {preview && <rect x={preview[0]} y={preview[1]} width={preview[2]} height={preview[3]} fill="#d29b281c" stroke="#ae7114" strokeWidth={2} vectorEffect="non-scaling-stroke" />}
        </svg>}
      </div> : <p className="workflow-error">源图加载失败</p>}
    </div>
    <section className="trace-properties" aria-label="人工房间描图">
      <div className="roi-review-heading"><strong>人工房间 · 草稿</strong>
        <button className="icon-button" title="新增房间" aria-label="新增房间" disabled={inactive || !bbox || roomEditPending || rooms.current.length >= 64} onClick={() => selectRoom(null)}><Plus size={18} /></button>
      </div>
      {rooms.current.length > 0 && <div className="trace-room-list">{rooms.current.map((r, index) => <button key={index} type="button" className="source-tab"
        data-testid={`trace-room-select-${index}`} aria-pressed={selectedRoom === index} disabled={inactive || roomEditPending} onClick={() => selectRoom(index)}>{r.name}</button>)}</div>}
      <div className="trace-name-fields">
        <label>房间名称<input aria-label="描图房间名称" data-testid="trace-room-name" value={roomName} maxLength={120} disabled={inactive || !bbox} onChange={(e) => setRoomName(e.target.value)} /></label>
        <label>类型<select aria-label="描图房间类型" value={roomKind} disabled={inactive || !bbox} onChange={(e) => setRoomKind(e.target.value)}>{Object.entries(kinds).map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select></label>
      </div>
      <RectFields prefix="trace-room" values={roomFields} onChange={setRoomFields} disabled={inactive || !bbox} />
      <div className="roi-review-actions">
        <button type="button" className="button" data-testid="trace-room-apply" disabled={inactive || !roomRect || !roomName.trim() || (selectedRoom === null && rooms.current.length >= 64)} onClick={commitRoom}><Plus size={16} />{selectedRoom === null ? "添加房间" : "应用修改"}</button>
        <button className="icon-button" aria-label="取消房间修改" title="取消房间修改" disabled={inactive || !roomEditPending} onClick={() => selectRoom(selectedRoom)}><X size={18} /></button>
        <button className="icon-button" aria-label="删除描图房间" title="删除描图房间" disabled={inactive || selectedRoom === null}
          onClick={() => { saveRooms(rooms.current.filter((_, i) => i !== selectedRoom)); selectRoom(null); }}><Trash2 size={18} /></button>
      </div>
      <div className="trace-name-fields">
        <label>墙厚 (mm)<input type="number" min="0" step="any" data-testid="trace-wall-thickness" value={thickness} disabled={inactive} onChange={(e) => setThickness(e.target.value)} /></label>
        <label>墙高 (mm)<input type="number" min="0" step="any" data-testid="trace-wall-height" value={height} disabled={inactive} onChange={(e) => setHeight(e.target.value)} /></label>
      </div>
      {rooms.current.length > 0 && topologyError && <p className="workflow-error" role="alert">{topologyError}</p>}
      {roomEditPending && <p className="workflow-status">房间修改尚未应用</p>}
      <button type="button" className="button primary" data-testid="trace-submit" disabled={inactive || !!topologyError || !validHeights || roomEditPending}
        onClick={() => void submit("trace")}><PencilRuler size={16} />生成描图草稿</button>
    </section>
  </div>;
}
