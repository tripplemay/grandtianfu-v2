import type { Camera, Envelope, SpatialModel } from "./model";

export type IngestResult = {
  ingest_id: string;
  model: SpatialModel;
  envelope: Envelope;
  manifest: Record<string, unknown>;
  source_url: string;
  preprocessed_url?: string;
  normalized_source_url?: string;
  overlay_url?: string;
  parent_source_url?: string | null;
  parent_preprocessed_url?: string | null;
};

export type RoiCandidate = {
  id: string;
  rank?: number;
  evidence_bbox: [number, number, number, number];
  confidence?: number;
  needs_review?: boolean;
  selection?: string;
  [key: string]: unknown;
};

/** Read ROI evidence without treating it as SpatialModel geometry. */
export function roiCandidates(model: SpatialModel): RoiCandidate[] {
  const ingest = model.ingest;
  const sources = [
    ingest && typeof ingest.preprocessing === "object"
      ? (ingest.preprocessing as { roi_candidates?: unknown }).roi_candidates
      : undefined,
    ingest && typeof ingest.evidence === "object"
      ? (ingest.evidence as { roi_candidates?: unknown }).roi_candidates
      : undefined,
  ];
  const seen = new Set<string>();
  const output: RoiCandidate[] = [];
  for (const source of sources) {
    if (!Array.isArray(source)) continue;
    for (const value of source) {
      if (!value || typeof value !== "object") continue;
      const candidate = value as Partial<RoiCandidate>;
      const bbox = candidate.evidence_bbox;
      if (
        typeof candidate.id !== "string" ||
        !Array.isArray(bbox) ||
        bbox.length !== 4 ||
        bbox.some((part) => typeof part !== "number" || !Number.isFinite(part)) ||
        bbox[2] <= 0 ||
        bbox[3] <= 0 ||
        seen.has(candidate.id)
      )
        continue;
      seen.add(candidate.id);
      output.push({
        ...candidate,
        id: candidate.id,
        evidence_bbox: bbox as RoiCandidate["evidence_bbox"],
      });
    }
  }
  return output.sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity));
}

export const reviewChecks = {
  scale: "比例与尺寸已核对",
  geometry: "房间边界与墙体已核对",
  openings: "门窗位置与类型已核对",
  heights: "墙高、开口高度与标高已核对",
};
const topologyChecks = {
  topology: "共享边界、连通关系与 Merge 组已核对",
  coverage: "所描绘区域内的房间与门窗完整（非自动全屋认证）",
};
export type ReviewCheck = keyof typeof reviewChecks | keyof typeof topologyChecks;

export function reviewChecksFor(model: SpatialModel) {
  return model.ingest?.topology ? { ...reviewChecks, ...topologyChecks } : reviewChecks;
}

export function canReviewTopology(model: SpatialModel) {
  const topology = model.ingest?.topology as { version?: string; reviewed_object_ids?: unknown } | undefined;
  return model.source?.provenance === "manual_topology" && topology?.version === "manual-topology-0.1" &&
    Array.isArray(topology.reviewed_object_ids) &&
    model.rooms.every((room) => room.kind?.trim() && room.kind.trim().toLowerCase() !== "unknown") &&
    model.openings.every((opening) => ["door", "window", "passage"].includes(opening.kind));
}

export function reviewBlockers(model: SpatialModel): unknown[] {
  const blockers = model.ingest?.hard_blockers ?? [];
  const legacy = model.ingest?.blockers;
  if (!Array.isArray(blockers)) return ["invalid_blockers"];
  const remaining = blockers.filter((blocker) => !(
    canReviewTopology(model) && typeof blocker === "object" && blocker !== null &&
    (blocker as { code?: string }).code === "manual_trace_requires_topology_review"));
  return legacy && (!Array.isArray(legacy) || legacy.length) ? [...remaining, legacy] : remaining;
}

export function reviewObjects(model: SpatialModel) {
  return [
    ...model.rooms.map((item) => ({ ...item, label: `房间 ${item.name}` })),
    ...model.walls.map((item) => ({ ...item, label: `墙体 ${item.id}` })),
    ...model.openings.map((item) => ({ ...item, label: `开口 ${item.id}` })),
    ...(model.ingest?.topology ? Array.from(new Set(model.rooms.map((room) => room.merge_group_id).filter((id): id is string => !!id)))
      .map((id) => ({ id, label: `Merge ${id}`, provenance: "manual_topology", confidence: undefined })) : []),
  ];
}

export function readyToReview(
  model: SpatialModel,
  reviewed: ReadonlySet<string>,
  checks: ReadonlySet<ReviewCheck>,
  dirty: boolean,
) {
  const objects = reviewObjects(model);
  return (
    !dirty &&
    model.status === "draft" &&
    reviewBlockers(model).length === 0 &&
    model.rooms.length > 0 &&
    model.walls.length > 0 &&
    objects.every((item) => reviewed.has(item.id)) &&
    Object.keys(reviewChecksFor(model)).every((key) => checks.has(key as ReviewCheck))
  );
}

export function validScale(text: string) {
  const value = Number(text);
  return (
    text.trim() !== "" && Number.isFinite(value) && value > 0 && value <= 10000
  );
}

export function cameraError(camera: Camera): string {
  const values = [
    ...Object.values(camera.position),
    ...Object.values(camera.look_at),
    ...Object.values(camera.up),
  ];
  if (values.some((value) => !Number.isFinite(value) || Math.abs(value) > 1e9))
    return "相机坐标必须是有限数值";
  const d = {
    x: camera.look_at.x - camera.position.x,
    y: camera.look_at.y - camera.position.y,
    z: camera.look_at.z - camera.position.z,
  };
  const u = camera.up;
  const cross = [
    d.y * u.z - d.z * u.y,
    d.z * u.x - d.x * u.z,
    d.x * u.y - d.y * u.x,
  ];
  if (Math.hypot(d.x, d.y, d.z) < 1e-9) return "相机位置不能等于目标点";
  if (Math.hypot(...cross) < 1e-9) return "相机上方向不能平行于视线";
  return "";
}
