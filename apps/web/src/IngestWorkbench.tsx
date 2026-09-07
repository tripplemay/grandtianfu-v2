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
  reviewBlockers,
  reviewChecksFor,
  reviewObjects,
  validScale,
  type IngestResult,
  type ReviewCheck,
} from "./ingestion";
import { type Camera, type SpatialModel } from "./model";

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
  const reviewChecks = reviewChecksFor(model);
  const blockers = reviewBlockers(model).filter(
      (item): item is { message: string } =>
          typeof item === "object" &&
          item !== null &&
          typeof (item as { message?: unknown }).message === "string",
      );
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
      {model.ingest?.topology !== undefined && <p className="workflow-status" data-testid="topology-review-scope">确认范围：人工描绘区域</p>}
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
