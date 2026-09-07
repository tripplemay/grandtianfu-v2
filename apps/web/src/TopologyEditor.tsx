import { DoorOpen, LoaderCircle, Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { IngestResult } from "./ingestion";
import type { SpatialModel } from "./model";
import { sharedWallEvidence, topologyFieldError, topologyReviewIds, type TopologyInput, type TopologyMergeGroupInput, type TopologyOpeningInput } from "./topology";

type Props = {
  model: SpatialModel;
  result: IngestResult;
  disabled?: boolean;
  onTopology: (input: TopologyInput) => Promise<IngestResult>;
  onDirtyChange: (dirty: boolean) => void;
};

const blank = (wallId = ""): TopologyOpeningInput => ({ host_wall_id: wallId, kind: "door", offset: 0, width: 900, height: 2100, bottom_z: 0 });

export function TopologyEditor({ model, result: _result, disabled = false, onTopology, onDirtyChange }: Props) {
  const rawOpenings = (model.ingest?.topology as { openings?: TopologyOpeningInput[] } | undefined)?.openings ?? model.openings;
  const initialOpenings = rawOpenings.map((item) => ({ id: item.id, host_wall_id: item.host_wall_id, kind: item.kind, offset: item.offset, width: item.width, height: item.height, bottom_z: item.bottom_z }));
  const initialGroups = (model.ingest?.topology as { merge_groups?: TopologyMergeGroupInput[] } | undefined)?.merge_groups ?? [];
  const [openings, setOpenings] = useState<TopologyOpeningInput[]>(initialOpenings.map((item) => ({ ...item })));
  const [groups, setGroups] = useState<TopologyMergeGroupInput[]>(initialGroups.map((item) => ({ ...item, room_ids: [...item.room_ids] })));
  const [draft, setDraft] = useState<TopologyOpeningInput>(blank(model.walls[0]?.id));
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [selectedRooms, setSelectedRooms] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const baseline = JSON.stringify({ openings: initialOpenings, groups: initialGroups });
  const dirty = JSON.stringify({ openings, groups }) !== baseline;
  const draftError = topologyFieldError(draft, model);
  const groupCandidates = useMemo(() => model.rooms.filter((room) => !groups.some((group) => group.room_ids.includes(room.id))), [groups, model.rooms]);
  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange]);
  useEffect(() => () => onDirtyChange(false), [onDirtyChange]);

  function addOpening() {
    if (draftError || disabled || pending) return;
    const next = { ...draft, id: draft.id ?? `topology-opening-${openings.length + 1}` };
    if (openings.some((item, index) => index !== editingIndex && item.host_wall_id === next.host_wall_id && Math.min(item.offset + item.width, next.offset + next.width) > Math.max(item.offset, next.offset))) {
      setError("门窗与同一墙体上的已有门窗重叠");
      return;
    }
    setOpenings((items) => editingIndex === null ? [...items, next] : items.map((item, index) => index === editingIndex ? next : item));
    setDraft(blank(model.walls[0]?.id));
    setEditingIndex(null);
    setError("");
  }
  function addGroup() {
    if (selectedRooms.length < 2 || disabled || pending) return;
    setGroups((items) => [...items, { id: `topology-merge-${items.length + 1}`, room_ids: selectedRooms }]);
    setSelectedRooms([]);
    setError("");
  }
  async function submit() {
    if (disabled || pending || groups.some((group) => group.room_ids.length < 2)) return;
    setPending(true); setError("");
    try {
      await onTopology({ openings, merge_groups: groups, reviewed_object_ids: topologyReviewIds(model, openings, groups) });
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setPending(false); }
  }
  return <div className="topology-editor" data-testid="topology-editor">
    <div className="topology-heading"><div><strong>门窗与空间连通性</strong><p className="muted">所有尺寸均为 mm；审核结果会生成不可变派生草稿。</p></div><DoorOpen size={22} /></div>
    <section className="topology-section" aria-label="门窗审核">
      <div className="roi-review-heading"><strong>门窗 / 开口</strong><span className="muted">{openings.length} 项</span></div>
      {openings.map((opening, index) => <div className="topology-row" key={opening.id ?? index} data-testid={`topology-opening-${index}`}>
        <span className="topology-id">{opening.id ?? `开口 ${index + 1}`}</span><span>{opening.kind}</span><span>{opening.host_wall_id}</span><span>{opening.offset} + {opening.width}</span>
        <span className="topology-row-actions"><button className="icon-button" type="button" title="编辑开口" aria-label="编辑开口" disabled={disabled || pending} onClick={() => { setDraft({ ...opening }); setEditingIndex(index); setError(""); }}><DoorOpen size={16} /></button><button className="icon-button" type="button" title="删除开口" aria-label="删除开口" disabled={disabled || pending} onClick={() => setOpenings((items) => items.filter((_, itemIndex) => itemIndex !== index))}><Trash2 size={16} /></button></span>
      </div>)}
      <div className="topology-form">
        <label>宿主墙体<select aria-label="宿主墙体" value={draft.host_wall_id} disabled={disabled || pending} onChange={(event) => setDraft({ ...draft, host_wall_id: event.target.value })}>{model.walls.map((wall) => <option key={wall.id} value={wall.id}>{wall.id} · {wall.length} mm</option>)}</select></label>
        <label>类型<select aria-label="开口类型" value={draft.kind} disabled={disabled || pending} onChange={(event) => setDraft({ ...draft, kind: event.target.value })}><option value="door">门</option><option value="window">窗</option><option value="passage">连通开口</option></select></label>
        {([['offset', '偏移'], ['width', '宽度'], ['height', '高度'], ['bottom_z', '底标高']] as const).map(([key, label]) => <label key={key}>{label}<input aria-label={label} type="number" min="0" step="any" value={draft[key]} disabled={disabled || pending} onChange={(event) => setDraft({ ...draft, [key]: Number(event.target.value) })} /></label>)}
      </div>
      {draftError && <p className="workflow-error" role="alert">{draftError}</p>}
      <button className="button" type="button" data-testid="topology-add-opening" disabled={disabled || pending || !!draftError} onClick={addOpening}><Plus size={16} />{editingIndex === null ? "加入审核" : "保存开口修改"}</button>
    </section>
    <section className="topology-section" aria-label="房间合并审核">
      <div className="roi-review-heading"><strong>Merge 房间</strong><span className="muted">{groups.length} 组</span></div>
      {groups.map((group, index) => { const evidence = sharedWallEvidence(model, group.room_ids, openings); return <div className="topology-row" key={group.id ?? index} data-testid={`topology-group-${index}`}><span className="topology-id">{group.id ?? `组 ${index + 1}`}</span><span>{group.room_ids.map((id) => model.rooms.find((room) => room.id === id)?.name ?? id).join(" + ")}<small className="topology-evidence">{evidence.walls.length ? `共享墙：${evidence.walls.join(", ")}${evidence.openings.length ? ` · 开口：${evidence.openings.join(", ")}` : ""}` : "需由审核开口提供连通证据"}</small></span><button className="icon-button" type="button" title="删除合并组" aria-label="删除合并组" disabled={disabled || pending} onClick={() => setGroups((items) => items.filter((_, itemIndex) => itemIndex !== index))}><Trash2 size={16} /></button></div>; })}
      <div className="topology-room-picker">{groupCandidates.map((room) => <label key={room.id}><input type="checkbox" checked={selectedRooms.includes(room.id)} disabled={disabled || pending} onChange={(event) => setSelectedRooms((items) => event.target.checked ? [...items, room.id] : items.filter((id) => id !== room.id))} />{room.name}</label>)}</div>
      <button className="button" type="button" data-testid="topology-add-group" disabled={disabled || pending || selectedRooms.length < 2} onClick={addGroup}><Plus size={16} />加入 Merge 组</button>
      <p className="muted">仅允许有共享边界或明确开口证据的相邻房间合并。</p>
    </section>
    {error && <p className="workflow-error" role="alert" data-testid="topology-error">{error}</p>}
    <button className="button primary" type="button" data-testid="topology-submit" disabled={disabled || pending} onClick={() => void submit()}>{pending ? <LoaderCircle size={16} className="spin" /> : <DoorOpen size={16} />}生成拓扑审核草稿</button>
    <p className="workflow-error" data-testid="topology-blocker">拓扑审核完成后仍需人工确认，当前不会进入家具摆放或照片级渲染。</p>
  </div>;
}
