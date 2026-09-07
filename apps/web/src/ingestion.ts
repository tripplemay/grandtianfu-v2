import type { Camera, Envelope, SpatialModel } from "./model";

export type IngestResult = {
  ingest_id: string;
  model: SpatialModel;
  envelope: Envelope;
  manifest: Record<string, unknown>;
  source_url: string;
  preprocessed_url?: string;
};

export const reviewChecks = {
  scale: "比例与尺寸已核对",
  geometry: "房间边界与墙体已核对",
  openings: "门窗位置与类型已核对",
  heights: "墙高、开口高度与标高已核对",
};
export type ReviewCheck = keyof typeof reviewChecks;

export function reviewObjects(model: SpatialModel) {
  return [
    ...model.rooms.map((item) => ({ ...item, label: `房间 ${item.name}` })),
    ...model.walls.map((item) => ({ ...item, label: `墙体 ${item.id}` })),
    ...model.openings.map((item) => ({ ...item, label: `开口 ${item.id}` })),
  ];
}

export function readyToReview(
  model: SpatialModel,
  reviewed: ReadonlySet<string>,
  checks: ReadonlySet<ReviewCheck>,
  dirty: boolean,
) {
  const objects = reviewObjects(model);
  const blockers = model.ingest?.hard_blockers;
  return (
    !dirty &&
    model.status === "draft" &&
    !(Array.isArray(blockers) && blockers.length > 0) &&
    model.rooms.length > 0 &&
    model.walls.length > 0 &&
    objects.every((item) => reviewed.has(item.id)) &&
    Object.keys(reviewChecks).every((key) => checks.has(key as ReviewCheck))
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
