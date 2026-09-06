import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  Armchair,
  Check,
  ChevronRight,
  Download,
  History,
  Layers,
  LoaderCircle,
  Plus,
  Redo2,
  RefreshCw,
  Save,
  SlidersHorizontal,
  Trash2,
  Undo2,
  X,
} from "lucide-react";
import { PlanCanvas, type Selection } from "./PlanCanvas";
import { resizeRoom, roomResizeLimits } from "./editing";
import {
  updateFurniture,
  type Envelope,
  type Furniture,
  type Revision,
  type SpatialModel,
} from "./model";

type Summary = {
  model_id: string;
  title: string;
  latest_revision: number;
  status: string;
  hash: string;
};
type Validation = { key: string; errors: string[]; pending: boolean };
type Timeline = {
  model: SpatialModel;
  past: SpatialModel[];
  future: SpatialModel[];
};
type Dialog = {
  title: string;
  body: string;
  command: string;
  action: () => void;
};
const statusNames: Record<string, string> = {
  draft: "草稿",
  confirmed: "已确认",
  locked: "已锁定",
};
const catalog = {
  sofa: { name: "沙发", width: 2200, depth: 900, height: 850 },
  coffee_table: { name: "茶几", width: 1200, depth: 700, height: 450 },
  bed: { name: "床", width: 1800, depth: 2000, height: 550 },
};
const furnitureName = (item: Furniture) =>
  catalog[item.catalog_id as keyof typeof catalog]?.name ?? item.catalog_id;
const roomName = (name: string) =>
  ({ Living: "客厅", Foyer: "门厅" })[name] ?? name;
const serial = (model: SpatialModel) => JSON.stringify(model);
const FieldValidity = createContext<(key: string, valid: boolean) => void>(
  () => {},
);
const FieldTransaction = createContext<() => () => void>(() => () => {});

class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  const data = await response.json();
  if (!response.ok) {
    const detail =
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail ?? data);
    throw new ApiError(
      response.status === 409
        ? "保存冲突：已有更新的版本。当前编辑已保留，请重新载入后核对。"
        : detail,
      response.status,
    );
  }
  return data as T;
}

function NumberField({
  label,
  value,
  onChange,
  disabled = false,
  min,
  title,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  disabled?: boolean;
  min?: number;
  title?: string;
}) {
  const [text, setText] = useState(String(value));
  const focusStart = useRef(value);
  const begin = useContext(FieldTransaction);
  const cancel = useRef<() => void>(() => {});
  const report = useContext(FieldValidity);
  useEffect(() => setText(String(value)), [value]);
  const valid =
    text.trim() !== "" &&
    Number.isFinite(Number(text)) &&
    Math.abs(Number(text)) <= 1e9 &&
    (min === undefined || Number(text) >= min);
  useEffect(() => {
    report(label, valid);
    return () => report(label, true);
  }, [label, valid, report]);
  function commit() {
    if (valid && Number(text) !== value) onChange(Number(text));
  }
  return (
    <label className="number-field" title={title}>
      <span>{label}</span>
      <div className="number-input">
        <input
          aria-label={label}
          type="number"
          step="any"
          min={min ?? -1e9}
          max={1e9}
          disabled={disabled}
          value={text}
          aria-invalid={!valid}
          required
          onFocus={() => {
            focusStart.current = value;
            cancel.current = begin();
          }}
          onChange={(event) => {
            const next = event.target.value;
            setText(next);
            if (
              next.trim() !== "" &&
              Number.isFinite(Number(next)) &&
              Math.abs(Number(next)) <= 1e9 &&
              (min === undefined || Number(next) >= min) &&
              Number(next) !== value
            )
              onChange(Number(next));
          }}
          onBlur={commit}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              commit();
              if (valid) {
                focusStart.current = Number(text);
                cancel.current = begin();
              }
            }
            if (event.key === "Escape") {
              setText(String(focusStart.current));
              cancel.current();
            }
          }}
        />
        <span>mm</span>
      </div>
      {!valid && (
        <small className="field-error">数值范围 {min ?? -1e9} 至 1e9</small>
      )}
    </label>
  );
}

function IconButton({
  label,
  children,
  onClick,
  disabled = false,
}: {
  label: string;
  children: ReactNode;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      className="icon-button"
      type="button"
      title={label}
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

export default function App() {
  const [models, setModels] = useState<Summary[]>([]);
  const [loaded, setLoaded] = useState<Envelope | null>(null);
  const [latest, setLatest] = useState<Envelope | null>(null);
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [selection, setSelection] = useState<Selection>(null);
  const [validation, setValidation] = useState<Validation>({
    key: "",
    errors: [],
    pending: true,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [mobilePanel, setMobilePanel] = useState("plan");
  const [addKind, setAddKind] = useState<keyof typeof catalog>("coffee_table");
  const [invalidFields, setInvalidFields] = useState<Set<string>>(new Set());
  const [fieldEpoch, setFieldEpoch] = useState(0);
  const reportField = useCallback(
    (key: string, valid: boolean) =>
      setInvalidFields((current) => {
        if (current.has(key) === !valid) return current;
        const next = new Set(current);
        if (valid) next.delete(key);
        else next.add(key);
        return next;
      }),
    [],
  );
  const inspector = useRef<HTMLFormElement>(null);
  const modalRef = useRef<HTMLDialogElement>(null);
  const model = timeline?.model;
  const modelKey = model ? serial(model) : "";
  const dirty =
    (!!loaded && modelKey !== serial(loaded.model)) || invalidFields.size > 0;
  const historical =
    !!loaded && !!latest && loaded.model.revision !== latest.model.revision;
  const readOnly = historical || busy || model?.status === "locked";
  const validating = validation.pending || validation.key !== modelKey;
  const valid =
    !validating && validation.errors.length === 0 && invalidFields.size === 0;

  function install(envelope: Envelope) {
    setLoaded(envelope);
    setTimeline({ model: envelope.model, past: [], future: [] });
    setSelection(null);
  }

  async function load(id?: string, revision?: number) {
    setBusy(true);
    setError("");
    try {
      const summaries = await request<Summary[]>("/api/models");
      setModels(summaries);
      const target = id ?? summaries[0]?.model_id;
      if (!target) throw new Error("没有可用的空间模型");
      const base = `/api/models/${encodeURIComponent(target)}`;
      const [head, history] = await Promise.all([
        request<Envelope>(`${base}/latest`),
        request<Revision[]>(`${base}/revisions`),
      ]);
      const current =
        revision && revision !== head.model.revision
          ? await request<Envelope>(`${base}/revisions/${revision}`)
          : head;
      setLatest(head);
      setRevisions(history);
      install(current);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);
  useEffect(() => {
    if (!model) return;
    const controller = new AbortController();
    setValidation({ key: modelKey, errors: [], pending: true });
    const timer = window.setTimeout(async () => {
      try {
        const result = await request<{
          ok: boolean;
          errors: { message: string }[];
        }>(`/api/models/${encodeURIComponent(model.model_id)}/validate`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model }),
          signal: controller.signal,
        });
        if (!controller.signal.aborted)
          setValidation({
            key: modelKey,
            errors: result.errors.map((item) => item.message),
            pending: false,
          });
      } catch (err) {
        if (!controller.signal.aborted)
          setValidation({
            key: modelKey,
            errors: [err instanceof Error ? err.message : String(err)],
            pending: false,
          });
      }
    }, 180);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [modelKey]);

  useEffect(() => {
    function preventLeave(event: BeforeUnloadEvent) {
      if (dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    }
    window.addEventListener("beforeunload", preventLeave);
    return () => window.removeEventListener("beforeunload", preventLeave);
  }, [dirty]);
  useEffect(() => {
    if (dialog) modalRef.current?.showModal();
    else modalRef.current?.close();
  }, [dialog]);

  function guard(action: () => void) {
    if (dirty)
      setDialog({
        title: "放弃未保存的修改？",
        body: "当前编辑尚未形成新版本。",
        command: "放弃修改",
        action,
      });
    else action();
  }

  function edit(next: SpatialModel) {
    if (readOnly || !timeline || serial(next) === serial(timeline.model))
      return;
    setTimeline({
      model: next,
      past: [...timeline.past, timeline.model],
      future: [],
    });
    setNotice("");
  }

  function undo() {
    if (!timeline?.past.length || readOnly) return;
    const past = [...timeline.past];
    const previous = past.pop()!;
    setTimeline({
      model: previous,
      past,
      future: [timeline.model, ...timeline.future],
    });
  }
  function redo() {
    if (!timeline?.future.length || readOnly) return;
    const [next, ...future] = timeline.future;
    setTimeline({
      model: next,
      past: [...timeline.past, timeline.model],
      future,
    });
  }

  async function save(action: "save" | "confirm", restore = false) {
    if (
      !model ||
      !latest ||
      busy ||
      (!restore && !inspector.current?.reportValidity())
    )
      return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const base = `/api/models/${encodeURIComponent(model.model_id)}`;
      const result = await request<Envelope>(`${base}/revisions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model,
          expected_revision: latest.model.revision,
          expected_hash: latest.hash,
          action,
          note: restore
            ? `Restore revision ${model.revision}`
            : action === "confirm"
              ? "Human confirmed in 2D workbench"
              : "Edited in 2D workbench",
        }),
      });
      setLatest(result);
      install(result);
      setRevisions((items) => [
        {
          revision: result.model.revision,
          status: result.model.status,
          hash: result.hash,
          note: result.note,
          created_at: result.created_at,
        },
        ...items,
      ]);
      setNotice(
        `v${result.model.revision} ${action === "confirm" ? "已确认" : "已保存"}`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  function choose(item: Selection) {
    if (invalidFields.size)
      setDialog({
        title: "放弃未完成的数值输入？",
        body: "当前字段包含无效数值，其余模型编辑仍保留。",
        command: "放弃输入",
        action: () => {
          setSelection(item);
          setInvalidFields(new Set());
          setFieldEpoch((value) => value + 1);
        },
      });
    else setSelection(item);
  }
  function addFurniture() {
    if (!model || readOnly) return;
    const selectedRoom =
      selection?.kind === "room"
        ? model.rooms.find((room) => room.id === selection.id)
        : undefined;
    const room = selectedRoom ?? model.rooms[0];
    if (!room) return;
    const { width, depth, height } = catalog[addKind];
    const id = `${addKind}-${crypto.randomUUID().slice(0, 8)}`;
    edit({
      ...model,
      furniture_instances: [
        ...model.furniture_instances,
        {
          id,
          catalog_id: addKind,
          transform: {
            x: room.rect[0] + 300,
            y: room.rect[1] + 300,
            z: 0,
            rotation_z: 0,
          },
          dimensions: { width, depth, height },
          room_id: room.id,
          attachment: "free",
          asset_ref: { kind: "parametric", ref: addKind },
          provenance: "human",
          confidence: 1,
        },
      ],
    });
    setSelection({ kind: "furniture", id });
    setMobilePanel("properties");
  }

  function download() {
    if (!loaded) return;
    const url = URL.createObjectURL(
      new Blob(
        [
          JSON.stringify(
            { ...loaded.model, content_hash: loaded.hash },
            null,
            2,
          ),
        ],
        { type: "application/json" },
      ),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `${loaded.model.model_id}-v${loaded.model.revision}.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  const furniture = model?.furniture_instances.find(
    (item) => selection?.kind === "furniture" && item.id === selection.id,
  );
  const room = model?.rooms.find(
    (item) => selection?.kind === "room" && item.id === selection.id,
  );
  const wall = model?.walls.find(
    (item) => selection?.kind === "wall" && item.id === selection.id,
  );
  const opening = model?.openings.find(
    (item) => selection?.kind === "opening" && item.id === selection.id,
  );
  const limits = room && model ? roomResizeLimits(model, room.id) : null;

  function changeRoomSize(width: number, height: number) {
    if (!model || !room) return;
    try {
      edit(resizeRoom(model, room.id, width, height));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  function addOpening(kind: "door" | "window") {
    if (!model || !wall || readOnly) return;
    const id = `${kind}-${crypto.randomUUID().slice(0, 8)}`;
    edit({
      ...model,
      openings: [
        ...model.openings,
        {
          id,
          host_wall_id: wall.id,
          kind,
          offset: 200,
          width: 900,
          height: kind === "door" ? 2100 : 1200,
          bottom_z: kind === "door" ? 0 : 900,
        },
      ],
    });
    setSelection({ kind: "opening", id });
  }

  return (
    <div className="workbench" data-panel={mobilePanel}>
      <header className="app-header">
        <a
          href="/"
          className="brand"
          onClick={(event) => {
            event.preventDefault();
            guard(() => {
              void load(model?.model_id);
            });
          }}
        >
          <span className="brand-mark">
            <Layers size={22} />
          </span>
          <span>
            阅天府<small>GRANDTIANFU</small>
          </span>
        </a>
        <div className="project-heading">
          <span className="project-title">空间工作台</span>
          <span className="project-meta">
            {model?.profile ?? "orthogonal_v1"}
            <span className="dot" />
            毫米
          </span>
        </div>
        <div className="header-actions">
          <span
            className={`status-badge ${dirty ? "draft" : (model?.status ?? "draft")}`}
          >
            {dirty ? "未保存" : statusNames[model?.status ?? "draft"]}
          </span>
          <button
            className="button"
            onClick={() => {
              void save("save");
            }}
            disabled={!dirty || !valid || readOnly}
          >
            <Save size={16} />
            保存
          </button>
          <button
            className="button primary"
            disabled={
              readOnly || !valid || (!dirty && model?.status === "confirmed")
            }
            onClick={() =>
              setDialog({
                title: "确认当前空间模型？",
                body: "确认将创建一个新的人工确认版本。",
                command: "确认版本",
                action: () => {
                  void save("confirm");
                },
              })
            }
          >
            <Check size={16} />
            确认版本
          </button>
        </div>
      </header>

      <div className="document-bar">
        <div className="document-name">
          <span className="live-dot" />
          <select
            aria-label="空间模型"
            value={model?.model_id ?? ""}
            disabled={busy}
            onChange={(event) =>
              guard(() => {
                void load(event.target.value);
              })
            }
          >
            {models.map((item) => (
              <option key={item.model_id} value={item.model_id}>
                {item.model_id === model?.model_id
                  ? model.rooms.map((room) => roomName(room.name)).join(" / ")
                  : item.title}
              </option>
            ))}
          </select>
        </div>
        <div className="document-actions">
          <History size={15} />
          <select
            aria-label="历史版本"
            value={loaded?.model.revision ?? ""}
            disabled={busy}
            onChange={(event) =>
              guard(() => {
                void load(model?.model_id, Number(event.target.value));
              })
            }
          >
            {revisions.map((item) => (
              <option value={item.revision} key={item.revision}>
                v{item.revision} · {statusNames[item.status]}
                {item.revision === latest?.model.revision ? " · 最新" : ""}
              </option>
            ))}
          </select>
          <IconButton
            label="重新载入最新版本"
            disabled={busy}
            onClick={() =>
              guard(() => {
                void load(model?.model_id);
              })
            }
          >
            <RefreshCw size={16} />
          </IconButton>
          <IconButton
            label="导出当前已保存版本 JSON"
            disabled={!loaded || busy}
            onClick={download}
          >
            <Download size={16} />
          </IconButton>
        </div>
      </div>

      {(error || notice || historical) && (
        <div
          className={`message-bar ${error ? "error" : historical ? "history" : "success"}`}
          role={error ? "alert" : "status"}
        >
          <span>
            {error ||
              (historical
                ? `正在查看历史版本 v${loaded?.model.revision} · 只读`
                : notice)}
          </span>
          {historical && !error && (
            <button
              className="text-button"
              disabled={busy || !valid}
              onClick={() =>
                setDialog({
                  title: `恢复 v${loaded?.model.revision}？`,
                  body: "历史记录保持不变，恢复内容将另存为新的草稿版本。",
                  command: "恢复为新版本",
                  action: () => {
                    void save("save", true);
                  },
                })
              }
            >
              恢复为新版本
              <ChevronRight size={14} />
            </button>
          )}
          {error && (
            <IconButton label="关闭错误提示" onClick={() => setError("")}>
              <X size={16} />
            </IconButton>
          )}
        </div>
      )}

      {!model ? (
        <main className="loading-state">
          {busy ? (
            <LoaderCircle className="spin" size={25} />
          ) : (
            <button
              className="button"
              onClick={() => {
                void load();
              }}
            >
              <RefreshCw size={16} />
              重试
            </button>
          )}
        </main>
      ) : (
        <main className="workspace">
          <aside className="layers-pane">
            <div className="pane-heading">
              <h2>模型图层</h2>
              <span>{model.rooms.length} 个房间</span>
            </div>
            <div className="layer-scroll">
              <div className="section-label">房间与家具</div>
              {model.rooms.map((item) => (
                <div key={item.id} className="room-tree">
                  <button
                    className={`tree-row ${selection?.id === item.id ? "selected" : ""}`}
                    onClick={() => choose({ kind: "room", id: item.id })}
                  >
                    <span className="room-swatch" />
                    <span>
                      {roomName(item.name)}
                      <small>
                        {((item.rect[2] * item.rect[3]) / 1e6).toFixed(2)} m²
                      </small>
                    </span>
                    <ChevronRight size={14} />
                  </button>
                  {item.merge_group_id && (
                    <div className="merge-label">
                      merge · {item.merge_group_id}
                    </div>
                  )}
                  {model.furniture_instances
                    .filter((f) => f.room_id === item.id)
                    .map((f) => (
                      <button
                        key={f.id}
                        className={`tree-row child ${selection?.id === f.id ? "selected" : ""}`}
                        onClick={() => choose({ kind: "furniture", id: f.id })}
                      >
                        <Armchair size={15} />
                        <span>
                          {furnitureName(f)}
                          <small>{f.id}</small>
                        </span>
                      </button>
                    ))}
                </div>
              ))}
              <details className="layer-group">
                <summary>
                  墙体<span>{model.walls.length}</span>
                </summary>
                {model.walls.map((item) => (
                  <button
                    className={`tree-row ${selection?.id === item.id ? "selected" : ""}`}
                    key={item.id}
                    onClick={() => choose({ kind: "wall", id: item.id })}
                  >
                    <span className="wall-swatch" />
                    <span>{item.id}</span>
                  </button>
                ))}
              </details>
              <details className="layer-group">
                <summary>
                  门窗与开口<span>{model.openings.length}</span>
                </summary>
                {model.openings.map((item) => (
                  <button
                    className={`tree-row ${selection?.id === item.id ? "selected" : ""}`}
                    key={item.id}
                    onClick={() => choose({ kind: "opening", id: item.id })}
                  >
                    <span className="opening-swatch" />
                    <span>{item.id}</span>
                  </button>
                ))}
              </details>
            </div>
            <div className="catalog-add">
              <select
                aria-label="新增家具类型"
                value={addKind}
                disabled={readOnly}
                onChange={(event) =>
                  setAddKind(event.target.value as keyof typeof catalog)
                }
              >
                {Object.entries(catalog).map(([key, item]) => (
                  <option key={key} value={key}>
                    {item.name}
                  </option>
                ))}
              </select>
              <IconButton
                label="添加家具"
                disabled={readOnly}
                onClick={addFurniture}
              >
                <Plus size={17} />
              </IconButton>
            </div>
          </aside>

          <section className="plan-pane" aria-label="平面视图">
            <div className="plan-heading">
              <div>
                <span className="view-tab">二维平面</span>
                <span className="muted">
                  {model.rooms.length} 房间 / {model.furniture_instances.length}{" "}
                  家具
                </span>
              </div>
              <div className="edit-history">
                <IconButton
                  label="撤销"
                  disabled={readOnly || !timeline?.past.length}
                  onClick={undo}
                >
                  <Undo2 size={17} />
                </IconButton>
                <IconButton
                  label="重做"
                  disabled={readOnly || !timeline?.future.length}
                  onClick={redo}
                >
                  <Redo2 size={17} />
                </IconButton>
              </div>
            </div>
            <PlanCanvas
              model={model}
              selection={selection}
              onSelect={choose}
              onEdit={edit}
              readOnly={readOnly}
            />
          </section>

          <aside className="properties-pane">
            <div className="pane-heading">
              <h2>对象属性</h2>
              <SlidersHorizontal size={16} />
            </div>
            <FieldTransaction.Provider
              value={() => {
                const before = timeline;
                return () => setTimeline(before);
              }}
            >
              <FieldValidity.Provider value={reportField}>
                <form
                  ref={inspector}
                  className="inspector"
                  key={`${loaded?.model.revision}-${selection?.kind}-${selection?.id}-${fieldEpoch}`}
                  onSubmit={(event) => event.preventDefault()}
                >
                  {!selection && (
                    <div className="model-summary">
                      <div className="section-label">空间模型</div>
                      <h3>客厅与门厅</h3>
                      <dl>
                        <dt>轮廓</dt>
                        <dd>正交墙体</dd>
                        <dt>房间</dt>
                        <dd>{model.rooms.length}</dd>
                        <dt>合并组</dt>
                        <dd>
                          {
                            new Set(
                              model.rooms
                                .map((r) => r.merge_group_id)
                                .filter(Boolean),
                            ).size
                          }
                        </dd>
                        <dt>来源</dt>
                        <dd>{model.source.provenance}</dd>
                        <dt>版本</dt>
                        <dd>v{model.revision}</dd>
                      </dl>
                    </div>
                  )}
                  {selection && (
                    <div className="object-heading">
                      <span className="section-label">
                        {
                          {
                            furniture: "家具实例",
                            room: "房间",
                            wall: "墙体",
                            opening: "开口",
                          }[selection.kind]
                        }
                      </span>
                      <h3>
                        {furniture
                          ? furnitureName(furniture)
                          : room
                            ? roomName(room.name)
                            : opening
                              ? ({ door: "门", window: "窗", passage: "通道" }[
                                  opening.kind
                                ] ?? opening.kind)
                              : wall?.id}
                      </h3>
                      <code>{selection.id}</code>
                    </div>
                  )}
                  <fieldset disabled={readOnly}>
                    {furniture && (
                      <>
                        <div className="field-section">
                          <h4>落位坐标</h4>
                          <div className="field-grid">
                            {(["x", "y", "z"] as const).map((axis) => (
                              <NumberField
                                key={axis}
                                label={axis.toUpperCase()}
                                value={furniture.transform[axis]}
                                onChange={(value) =>
                                  edit(
                                    updateFurniture(model, furniture.id, {
                                      transform: { [axis]: value },
                                      provenance: "human",
                                      confidence: 1,
                                    }),
                                  )
                                }
                              />
                            ))}
                          </div>
                        </div>
                        <div className="field-section">
                          <h4>实际尺寸</h4>
                          <div className="field-grid">
                            {(
                              [
                                ["width", "宽度"],
                                ["depth", "深度"],
                                ["height", "高度"],
                              ] as const
                            ).map(([key, label]) => (
                              <NumberField
                                key={key}
                                label={label}
                                value={furniture.dimensions[key]}
                                min={1}
                                onChange={(value) =>
                                  edit(
                                    updateFurniture(model, furniture.id, {
                                      dimensions: { [key]: value },
                                      provenance: "human",
                                      confidence: 1,
                                    }),
                                  )
                                }
                              />
                            ))}
                          </div>
                        </div>
                        <label className="select-field">
                          朝向
                          <select
                            aria-label="朝向"
                            value={
                              ((furniture.transform.rotation_z % 360) + 360) %
                              360
                            }
                            onChange={(event) =>
                              edit(
                                updateFurniture(model, furniture.id, {
                                  transform: {
                                    rotation_z: Number(event.target.value),
                                  },
                                  provenance: "human",
                                  confidence: 1,
                                }),
                              )
                            }
                          >
                            {[0, 90, 180, 270].map((angle) => (
                              <option value={angle} key={angle}>
                                {angle}°
                              </option>
                            ))}
                          </select>
                        </label>
                        <label className="select-field">
                          所属房间
                          <select
                            aria-label="所属房间"
                            value={furniture.room_id}
                            onChange={(event) =>
                              edit(
                                updateFurniture(model, furniture.id, {
                                  room_id: event.target.value,
                                }),
                              )
                            }
                          >
                            {model.rooms.map((item) => (
                              <option value={item.id} key={item.id}>
                                {roomName(item.name)}
                              </option>
                            ))}
                          </select>
                        </label>
                        <button
                          className="button danger"
                          type="button"
                          onClick={() => {
                            edit({
                              ...model,
                              furniture_instances:
                                model.furniture_instances.filter(
                                  (item) => item.id !== furniture.id,
                                ),
                            });
                            setSelection(null);
                          }}
                        >
                          <Trash2 size={15} />
                          删除家具
                        </button>
                      </>
                    )}
                    {room && (
                      <>
                        <label className="select-field">
                          房间名称
                          <input
                            aria-label="房间名称"
                            value={room.name}
                            required
                            onChange={(event) =>
                              edit({
                                ...model,
                                rooms: model.rooms.map((item) =>
                                  item.id === room.id
                                    ? { ...item, name: event.target.value }
                                    : item,
                                ),
                              })
                            }
                          />
                        </label>
                        <div className="field-section">
                          <h4>房间边界</h4>
                          <div className="field-grid">
                            <NumberField
                              label="起点 X"
                              value={room.rect[0]}
                              disabled
                              onChange={() => {}}
                            />
                            <NumberField
                              label="起点 Y"
                              value={room.rect[1]}
                              disabled
                              onChange={() => {}}
                            />
                            <NumberField
                              label="房间宽度"
                              value={room.rect[2]}
                              disabled={!limits?.canResizeWidth}
                              title={
                                !limits?.canResizeWidth
                                  ? "共享边界锁定"
                                  : undefined
                              }
                              min={1}
                              onChange={(value) =>
                                changeRoomSize(value, room.rect[3])
                              }
                            />
                            <NumberField
                              label="房间深度"
                              value={room.rect[3]}
                              disabled={!limits?.canResizeHeight}
                              title={
                                !limits?.canResizeHeight
                                  ? "共享边界锁定"
                                  : undefined
                              }
                              min={1}
                              onChange={(value) =>
                                changeRoomSize(room.rect[2], value)
                              }
                            />
                          </div>
                        </div>
                        <dl>
                          <dt>合并组</dt>
                          <dd>{room.merge_group_id ?? "无"}</dd>
                          <dt>面积</dt>
                          <dd>
                            {((room.rect[2] * room.rect[3]) / 1e6).toFixed(2)}{" "}
                            m²
                          </dd>
                        </dl>
                      </>
                    )}
                    {wall && (
                      <>
                        <div className="field-section">
                          <h4>墙体尺寸</h4>
                          <div className="field-grid">
                            <NumberField
                              label="墙体长度"
                              value={wall.length}
                              disabled
                              onChange={() => {}}
                            />
                            {(
                              [
                                ["thickness", "墙厚"],
                                ["top_z", "墙顶标高"],
                              ] as const
                            ).map(([key, label]) => (
                              <NumberField
                                key={key}
                                label={label}
                                value={wall[key]}
                                min={1}
                                onChange={(value) =>
                                  edit({
                                    ...model,
                                    walls: model.walls.map((item) =>
                                      item.id === wall.id
                                        ? { ...item, [key]: value }
                                        : item,
                                    ),
                                  })
                                }
                              />
                            ))}
                          </div>
                        </div>
                        <div className="opening-actions">
                          <button
                            type="button"
                            className="button"
                            onClick={() => addOpening("door")}
                          >
                            <Plus size={14} />门
                          </button>
                          <button
                            type="button"
                            className="button"
                            onClick={() => addOpening("window")}
                          >
                            <Plus size={14} />窗
                          </button>
                        </div>
                      </>
                    )}
                    {opening && (
                      <>
                        <label className="select-field">
                          宿主墙
                          <select
                            aria-label="宿主墙"
                            value={opening.host_wall_id}
                            onChange={(event) =>
                              edit({
                                ...model,
                                openings: model.openings.map((item) =>
                                  item.id === opening.id
                                    ? {
                                        ...item,
                                        host_wall_id: event.target.value,
                                      }
                                    : item,
                                ),
                              })
                            }
                          >
                            {model.walls.map((item) => (
                              <option value={item.id} key={item.id}>
                                {item.id}
                              </option>
                            ))}
                          </select>
                        </label>
                        <div className="field-grid">
                          {(
                            [
                              ["offset", "沿墙偏移"],
                              ["width", "开口宽度"],
                              ["height", "开口高度"],
                              ["bottom_z", "窗台标高"],
                            ] as const
                          ).map(([key, label]) => (
                            <NumberField
                              key={key}
                              label={label}
                              value={opening[key]}
                              min={key === "width" || key === "height" ? 1 : 0}
                              onChange={(value) =>
                                edit({
                                  ...model,
                                  openings: model.openings.map((item) =>
                                    item.id === opening.id
                                      ? { ...item, [key]: value }
                                      : item,
                                  ),
                                })
                              }
                            />
                          ))}
                        </div>
                        <button
                          className="button danger"
                          type="button"
                          onClick={() => {
                            edit({
                              ...model,
                              openings: model.openings.filter(
                                (item) => item.id !== opening.id,
                              ),
                            });
                            setSelection(null);
                          }}
                        >
                          <Trash2 size={15} />
                          删除开口
                        </button>
                      </>
                    )}
                  </fieldset>
                </form>
              </FieldValidity.Provider>
            </FieldTransaction.Provider>
            <div
              className={`validation-panel ${!validating && !valid ? "invalid" : ""}`}
              role="status"
            >
              <div>
                {validating ? (
                  <LoaderCircle size={15} className="spin" />
                ) : valid ? (
                  <Check size={15} />
                ) : (
                  <X size={15} />
                )}
                <strong>
                  {invalidFields.size
                    ? "数值输入未完成"
                    : validating
                      ? "几何校验中"
                      : valid
                        ? "几何校验通过"
                        : `${validation.errors.length} 项几何错误`}
                </strong>
              </div>
              {!validating &&
                validation.errors.map((item, index) => (
                  <p key={index}>{item}</p>
                ))}
            </div>
          </aside>
        </main>
      )}

      <nav className="mobile-tabs" aria-label="工作区域">
        {[
          ["layers", "图层", Layers],
          ["plan", "平面", Armchair],
          ["properties", "属性", SlidersHorizontal],
        ].map(([key, label, Icon]) => {
          const Component = Icon as typeof Layers;
          return (
            <button
              key={String(key)}
              aria-pressed={mobilePanel === key}
              onClick={() => setMobilePanel(String(key))}
            >
              <Component size={17} />
              {String(label)}
            </button>
          );
        })}
      </nav>
      <footer className="status-bar">
        <span>
          <span className="live-dot" />
          {busy ? "处理中" : dirty ? "本地编辑 · 尚未保存" : "SpatialModel"}
        </span>
        <code title={loaded?.hash}>
          SHA-256 {loaded?.hash.slice(0, 12) ?? "..."}
        </code>
        <span>v{loaded?.model.revision ?? "-"} · mm / deg</span>
      </footer>
      <dialog
        ref={modalRef}
        className="confirm-dialog"
        onCancel={(event) => {
          event.preventDefault();
          setDialog(null);
        }}
      >
        <h2>{dialog?.title}</h2>
        <p>{dialog?.body}</p>
        <div>
          <button className="button" autoFocus onClick={() => setDialog(null)}>
            取消
          </button>
          <button
            className="button primary"
            onClick={() => {
              const action = dialog?.action;
              setDialog(null);
              action?.();
            }}
          >
            {dialog?.command}
          </button>
        </div>
      </dialog>
    </div>
  );
}
