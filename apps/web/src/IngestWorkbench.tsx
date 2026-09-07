import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  Camera as CameraIcon,
  Check,
  FileImage,
  LoaderCircle,
  Upload,
  X,
} from "lucide-react";
import {
  cameraError,
  readyToReview,
  reviewChecks,
  reviewObjects,
  validScale,
  type IngestResult,
  roiCandidates,
  type RoiCandidate,
  type ReviewCheck,
} from "./ingestion";
import { openingRect, wallRect, type Camera, type SpatialModel } from "./model";

function Modal({
  title,
  children,
  onClose,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  return (
    <dialog
      ref={ref}
      className="workflow-dialog"
      aria-label={title}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <div className="workflow-heading">
        <h2>{title}</h2>
        <button
          type="button"
          className="icon-button"
          aria-label="关闭"
          title="关闭"
          onClick={onClose}
        >
          <X size={18} />
        </button>
      </div>
      {children}
    </dialog>
  );
}

export function ImportDialog({
  onClose,
  onImport,
}: {
  onClose: () => void;
  onImport: (file: File, scale: number, signal: AbortSignal) => Promise<void>;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState("");
  const [scale, setScale] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [imageReady, setImageReady] = useState(false);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => {
    if (!file) return;
    const next = URL.createObjectURL(file);
    setUrl(next);
    setImageReady(false);
    return () => URL.revokeObjectURL(next);
  }, [file]);
  useEffect(() => () => controller.current?.abort(), []);
  async function submit() {
    if (!file || !validScale(scale) || !imageReady || busy) return;
    controller.current = new AbortController();
    setBusy(true);
    setError("");
    try {
      await onImport(file, Number(scale), controller.current.signal);
      if (!controller.current.signal.aborted) onClose();
    } catch (err) {
      if (!controller.current.signal.aborted)
        setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title="导入户型图" onClose={onClose}>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <label className="select-field">
          PNG / JPEG
          <input
            data-testid="ingest-file"
            type="file"
            accept="image/png,image/jpeg"
            disabled={busy}
            required
            onChange={(event) => {
              const next = event.target.files?.[0] ?? null;
              setError("");
              setFile(null);
              setUrl("");
              if (next && !["image/png", "image/jpeg"].includes(next.type))
                setError("文件类型必须为 PNG 或 JPEG");
              else if (next && next.size > 20 * 1024 * 1024)
                setError("文件不能超过 20 MiB");
              else setFile(next);
            }}
          />
        </label>
        {url ? (
          <img
            className="import-image"
            src={url}
            alt="待导入户型图"
            onLoad={() => setImageReady(true)}
            onError={() => {
              setImageReady(false);
              setError("图像无法解码");
            }}
          />
        ) : (
          <div className="import-empty">
            <FileImage size={32} />
          </div>
        )}
        <label className="select-field">
          比例 (mm/px)
          <input
            data-testid="ingest-scale"
            aria-label="比例 (mm/px)"
            type="number"
            min="0.000001"
            max="10000"
            step="any"
            value={scale}
            disabled={busy}
            required
            onChange={(event) => setScale(event.target.value)}
          />
        </label>
        {file && (
          <div className="muted import-filename">
            {file.name} · {(file.size / 1024).toFixed(1)} KiB
          </div>
        )}
        {error && (
          <p className="workflow-error" role="alert">
            {error}
          </p>
        )}
        <div className="workflow-actions">
          <button type="button" className="button" onClick={onClose}>
            {busy ? "取消请求" : "取消"}
          </button>
          <button
            data-testid="ingest-submit"
            className="button primary"
            disabled={!file || !imageReady || !validScale(scale) || busy}
          >
            {busy ? (
              <LoaderCircle size={16} className="spin" />
            ) : (
              <Upload size={16} />
            )}
            {busy ? "解析中" : "导入并解析"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function IngestSource({
  model,
  result,
  onCrop,
}: {
  model: SpatialModel;
  result: IngestResult;
  onCrop: (roi: RoiCandidate["evidence_bbox"]) => Promise<IngestResult>;
}) {
  const [mode, setMode] = useState("overlay");
  const [dimensions, setDimensions] = useState({ width: 1, height: 1 });
  const [broken, setBroken] = useState(false);
  const [selectedRoi, setSelectedRoi] = useState<string | null>(null);
  const [cropBusy, setCropBusy] = useState(false);
  const [cropError, setCropError] = useState("");
  const scale = model.ingest?.mm_per_pixel ?? 0;
  // Overlay and source mode must remain on the immutable parent bitmap. The
  // normalized image is the only crop-local artifact.
  const src = mode === "source"
    ? (result.parent_source_url ?? result.source_url)
    : mode === "normalized"
      ? result.preprocessed_url
      : (result.parent_preprocessed_url ?? result.preprocessed_url);
  const candidates = roiCandidates(model);
  const selected = candidates.find((candidate) => candidate.id === selectedRoi);
  const parentIngestId =
    typeof model.ingest?.parent_ingest_id === "string"
      ? model.ingest.parent_ingest_id
      : null;
  const cropRoi: [number, number, number, number] | null = (() => {
    const value =
      model.ingest && typeof model.ingest.roi === "object" && model.ingest.roi
        ? (model.ingest.roi as { bbox?: unknown }).bbox
        : null;
    return Array.isArray(value) && value.length === 4 && value.every(
      (item): item is number => typeof item === "number" && Number.isFinite(item),
    )
      ? [value[0], value[1], value[2], value[3]]
      : null;
  })();
  useEffect(() => {
    setSelectedRoi(null);
    setCropError("");
  }, [model.ingest?.ingest_id]);
  async function cropSelected() {
    if (!selected || cropBusy) return;
    setCropBusy(true);
    setCropError("");
    try {
      await onCrop(selected.evidence_bbox);
    } catch (err) {
      setCropError(err instanceof Error ? err.message : String(err));
    } finally {
      setCropBusy(false);
    }
  }
  return (
    <div className="ingest-source" data-testid="ingest-source">
      <div className="source-toolbar" role="group" aria-label="源图视图">
        {[
          ["source", "原始位图"],
          ["normalized", "规范化位图"],
          ["overlay", "候选叠加"],
        ].map(([value, label]) => (
          <button
            type="button"
            key={value}
            className="source-tab"
            aria-pressed={mode === value}
            onClick={() => {
              setMode(value);
              setBroken(false);
            }}
          >
            {label}
          </button>
        ))}
        <span className="muted">{scale} mm/px</span>
      </div>
      <section className="roi-review" aria-label="人工选择户型区域">
        {parentIngestId && (
          <p className="workflow-status" data-testid="roi-derived-draft">
            这是从原始 ingest <code>{parentIngestId.slice(0, 12)}</code> 生成的新草稿；原图证据仍由原始 hash 追溯。
            {cropRoi && (
              <> 裁剪原图坐标：[{cropRoi.map((value) => Math.round(Number(value))).join(", ")}] px。</>
            )}
          </p>
        )}
        <div className="roi-review-heading">
          <div>
            <strong>户型区域候选</strong>
            <p className="muted">
              候选只是原图证据，不是房间事实。请选择一个区域后重新识别。
            </p>
          </div>
          <span className="muted" data-testid="roi-count">
            {candidates.length} 个候选
          </span>
        </div>
        {candidates.length ? (
          <div className="roi-candidate-list" role="listbox" aria-label="户型区域候选">
            {candidates.map((candidate) => {
              const [x, y, width, height] = candidate.evidence_bbox;
              const active = candidate.id === selectedRoi;
              return (
                <button
                  type="button"
                  role="option"
                  aria-selected={active}
                  data-testid={`roi-candidate-${candidate.id}`}
                  className={`roi-candidate ${active ? "selected" : ""}`}
                  key={candidate.id}
                  disabled={cropBusy}
                  onClick={() => {
                    setSelectedRoi(candidate.id);
                    setCropError("");
                  }}
                >
                  <span>
                    候选 {candidate.rank ?? candidate.id}
                    {candidate.confidence !== undefined
                      ? ` · ${Math.round(candidate.confidence * 100)}%`
                      : ""}
                  </span>
                  <small>
                    原图坐标 x={Math.round(x)}, y={Math.round(y)}, w={Math.round(width)}, h={Math.round(height)} px
                  </small>
                </button>
              );
            })}
          </div>
        ) : (
          <p className="muted" data-testid="roi-empty">当前没有可安全选择的候选区域。</p>
        )}
        <div className="roi-review-actions">
          <button
            type="button"
            className="button primary"
            data-testid="roi-crop-submit"
            disabled={!selected || cropBusy}
            onClick={() => void cropSelected()}
          >
            {cropBusy ? <LoaderCircle size={16} className="spin" /> : <FileImage size={16} />}
            {cropBusy ? "裁剪并重新识别中" : "裁剪并重新识别"}
          </button>
          <span className="muted">
            {selected ? "将生成新的草稿版本，原图证据保留" : "未选择候选，审核仍不可用"}
          </span>
        </div>
        {cropBusy && (
          <p className="workflow-status" role="status" data-testid="roi-crop-status">
            正在按原图坐标裁剪，等待 CPU worker 生成新的 ingest 草稿……
          </p>
        )}
        {cropError && (
          <p className="workflow-error" role="alert" data-testid="roi-crop-error">
            裁剪识别失败：{cropError}
          </p>
        )}
        {selected && !cropBusy && !cropError && (
          <p className="muted" data-testid="roi-selected-status">
            已选择候选 {selected.rank ?? selected.id}；坐标将原样提交，原图 hash 必须匹配。
          </p>
        )}
      </section>
      <div className="source-image-scroll">
        {src && !broken ? (
          <div
            className="source-image-frame"
            style={{
              aspectRatio: `${dimensions.width} / ${dimensions.height}`,
            }}
          >
            <img
              src={src}
              alt={mode === "normalized" ? "规范化户型位图" : "原始户型位图"}
              onLoad={(event) =>
                setDimensions({
                  width: event.currentTarget.naturalWidth,
                  height: event.currentTarget.naturalHeight,
                })
              }
              onError={() => setBroken(true)}
            />
            {mode === "overlay" && scale > 0 && (
              <svg
                className="candidate-overlay"
                data-testid="candidate-overlay"
                viewBox={`0 0 ${dimensions.width * scale} ${dimensions.height * scale}`}
                aria-label="空间候选叠加"
              >
                {model.rooms.map((room) => (
                  <rect
                    key={room.id}
                    x={room.rect[0]}
                    y={room.rect[1]}
                    width={room.rect[2]}
                    height={room.rect[3]}
                    fill="#0c99601c"
                    stroke="#16875c"
                    strokeWidth={scale}
                  />
                ))}
                {model.walls.map((wall) => (
                  <rect
                    key={wall.id}
                    {...wallRect(wall)}
                    fill="#2259b566"
                    stroke="#2259b5"
                    strokeWidth={scale}
                  />
                ))}
                {model.openings.map((opening) => {
                  const wall = model.walls.find(
                    (item) => item.id === opening.host_wall_id,
                  );
                  return wall ? (
                    <rect
                      key={opening.id}
                      {...openingRect(opening, wall)}
                      fill="#d42d7466"
                      stroke="#d42d74"
                      strokeWidth={scale * 2}
                    />
                  ) : null;
                })}
                {candidates.map((candidate) => {
                  const [x, y, width, height] = candidate.evidence_bbox;
                  const active = candidate.id === selectedRoi;
                  return (
                    <rect
                      key={`roi-${candidate.id}`}
                      data-testid={`roi-overlay-${candidate.id}`}
                      x={x * scale}
                      y={y * scale}
                      width={width * scale}
                      height={height * scale}
                      fill={active ? "#ef9f2d24" : "transparent"}
                      stroke={active ? "#c06a12" : "#c08b3e"}
                      strokeWidth={Math.max(scale, 2)}
                      strokeDasharray={`${Math.max(scale * 3, 8)} ${Math.max(scale * 2, 5)}`}
                    />
                  );
                })}
              </svg>
            )}
          </div>
        ) : (
          <p className="workflow-error" role="status">
            {broken ? "源图加载失败" : "暂无规范化图像"}
          </p>
        )}
      </div>
    </div>
  );
}

export function ReviewDialog({
  model,
  dirty,
  busy,
  valid,
  onClose,
  onConfirm,
}: {
  model: SpatialModel;
  dirty: boolean;
  busy: boolean;
  valid: boolean;
  onClose: () => void;
  onConfirm: (
    ids: string[],
    checks: Record<ReviewCheck, boolean>,
  ) => Promise<void>;
}) {
  const [reviewed, setReviewed] = useState<Set<string>>(new Set());
  const [checks, setChecks] = useState<Set<ReviewCheck>>(new Set());
  const [error, setError] = useState("");
  const objects = reviewObjects(model);
  const blockers = Array.isArray(model.ingest?.hard_blockers)
    ? model.ingest.hard_blockers.filter(
      (item): item is { message: string } =>
          typeof item === "object" &&
          item !== null &&
          typeof (item as { message?: unknown }).message === "string",
      )
    : [];
  const ready = valid && readyToReview(model, reviewed, checks, dirty) && !busy;
  useEffect(() => {
    setReviewed(new Set());
    setChecks(new Set());
  }, [model]);
  return (
    <Modal title="人工校核" onClose={onClose}>
      <div className="review-summary">
        <span>v{model.revision}</span>
        <span>{objects.length} 个对象</span>
        <span>{model.ingest?.mm_per_pixel} mm/px</span>
      </div>
      {dirty && (
        <p className="workflow-error" role="status">
          存在未保存修改
        </p>
      )}
      {blockers.map((blocker, index) => (
        <p className="workflow-error" role="alert" key={`${blocker.message}-${index}`}>
          需要先处理：{blocker.message}
        </p>
      ))}
      <fieldset disabled={busy || dirty}>
        <label className="check-row review-all">
          <input
            data-testid="review-all"
            type="checkbox"
            checked={
              objects.length > 0 &&
              objects.every((item) => reviewed.has(item.id))
            }
            onChange={(event) =>
              setReviewed(
                event.target.checked
                  ? new Set(objects.map((item) => item.id))
                  : new Set(),
              )
            }
          />
          全部对象
        </label>
        <div className="review-object-list">
          {objects.map((item) => (
            <label className="check-row" key={item.id}>
              <input
                type="checkbox"
                aria-label={`审核 ${item.id}`}
                checked={reviewed.has(item.id)}
                onChange={(event) =>
                  setReviewed((current) => {
                    const next = new Set(current);
                    if (event.target.checked) next.add(item.id);
                    else next.delete(item.id);
                    return next;
                  })
                }
              />
              <span>
                {item.label}
                <small>
                  {item.provenance ?? "未记录来源"} ·{" "}
                  {item.confidence === undefined
                    ? "置信度未知"
                    : `${Math.round(item.confidence * 100)}%`}
                </small>
              </span>
            </label>
          ))}
        </div>
        <div className="review-checks">
          {Object.entries(reviewChecks).map(([key, label]) => (
            <label className="check-row" key={key}>
              <input
                type="checkbox"
                data-testid={`review-${key}`}
                checked={checks.has(key as ReviewCheck)}
                onChange={(event) =>
                  setChecks((current) => {
                    const next = new Set(current);
                    if (event.target.checked) next.add(key as ReviewCheck);
                    else next.delete(key as ReviewCheck);
                    return next;
                  })
                }
              />
              {label}
            </label>
          ))}
        </div>
      </fieldset>
      {error && (
        <p className="workflow-error" role="alert">
          {error}
        </p>
      )}
      <div className="workflow-actions">
        <button
          type="button"
          className="button"
          disabled={busy}
          onClick={onClose}
        >
          取消
        </button>
        <button
          type="button"
          data-testid="review-submit"
          className="button primary"
          disabled={!ready}
          onClick={async () => {
            setError("");
            try {
              await onConfirm(
                [...reviewed],
                Object.fromEntries(
                  Object.keys(reviewChecks).map((key) => [
                    key,
                    checks.has(key as ReviewCheck),
                  ]),
                ) as Record<ReviewCheck, boolean>,
              );
              onClose();
            } catch (err) {
              setError(err instanceof Error ? err.message : String(err));
            }
          }}
        >
          {busy ? (
            <LoaderCircle size={16} className="spin" />
          ) : (
            <Check size={16} />
          )}
          确认校核
        </button>
      </div>
    </Modal>
  );
}

export function CameraDialog({
  initial,
  onClose,
  onSave,
}: {
  initial?: Camera;
  onClose: () => void;
  onSave: (camera: Camera) => void;
}) {
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      ["position", "look_at", "up"].flatMap((group) =>
        ["x", "y", "z"].map((axis) => [
          `${group}.${axis}`,
          initial
            ? String(initial[group as "position"][axis as "x"])
            : group === "up"
              ? axis === "z"
                ? "1"
                : "0"
              : "",
        ]),
      ),
    ),
  );
  const camera: Camera = {
    id: initial?.id ?? "camera-main",
    projection: "perspective",
    image_size: initial?.image_size ?? { width: 800, height: 600 },
    position: { x: 0, y: 0, z: 0 },
    look_at: { x: 0, y: 0, z: 0 },
    up: { x: 0, y: 0, z: 1 },
  };
  for (const group of ["position", "look_at", "up"] as const)
    for (const axis of ["x", "y", "z"] as const)
      camera[group][axis] = Number(values[`${group}.${axis}`]);
  const complete = Object.values(values).every((value) => value.trim() !== "");
  const error = complete ? cameraError(camera) : "";
  return (
    <Modal title="固定相机" onClose={onClose}>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (complete && !error) {
            onSave(camera);
            onClose();
          }
        }}
      >
        {(
          [
            ["position", "位置 (mm)"],
            ["look_at", "目标点 (mm)"],
            ["up", "上方向"],
          ] as const
        ).map(([group, label]) => (
          <div className="field-section" key={group}>
            <h4>{label}</h4>
            <div className="camera-grid">
              {(["x", "y", "z"] as const).map((axis) => (
                <label className="select-field" key={axis}>
                  {axis.toUpperCase()}
                  <input
                    type="number"
                    step="any"
                    min={-1e9}
                    max={1e9}
                    required
                    aria-label={`${label} ${axis.toUpperCase()}`}
                    data-testid={`camera-${group}-${axis}`}
                    value={values[`${group}.${axis}`]}
                    onChange={(event) =>
                      setValues((current) => ({
                        ...current,
                        [`${group}.${axis}`]: event.target.value,
                      }))
                    }
                  />
                </label>
              ))}
            </div>
          </div>
        ))}
        {error && (
          <p className="workflow-error" role="alert">
            {error}
          </p>
        )}
        <div className="workflow-actions">
          <button type="button" className="button" onClick={onClose}>
            取消
          </button>
          <button
            className="button primary"
            data-testid="camera-save"
            disabled={!complete || !!error}
          >
            <CameraIcon size={16} />
            应用相机
          </button>
        </div>
      </form>
    </Modal>
  );
}
