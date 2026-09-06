/**
 * Frontend types and pure geometry helpers for SpatialModel v2.
 *
 * Coordinates are millimetres in the canonical X-east/Y-south plane.  The
 * furniture transform follows the core model's footprint convention: x/y is
 * the minimum corner of the rotated axis-aligned footprint, not its centre.
 */

export type Point = { x: number; y: number };
export type Bounds = { x: number; y: number; width: number; height: number };
export type Rect = [number, number, number, number];

export type SpatialStatus = "draft" | "confirmed" | "locked";
export type WallAxis = "h" | "v";

export type Room = {
  id: string;
  name: string;
  kind: string;
  rect: Rect;
  boundary_wall_ids: string[];
  merge_group_id?: string;
  visible?: boolean;
};

export type Wall = {
  id: string;
  axis: WallAxis;
  x: number;
  y: number;
  length: number;
  thickness: number;
  bottom_z: number;
  top_z: number;
};

export type Opening = {
  id: string;
  host_wall_id: string;
  kind: string;
  offset: number;
  width: number;
  height: number;
  bottom_z: number;
  opening_direction?: string;
};

export type FurnitureTransform = {
  x: number;
  y: number;
  z: number;
  rotation_z: number;
};

export type FurnitureDimensions = {
  width: number;
  depth: number;
  height: number;
};

export type Furniture = {
  id: string;
  catalog_id: string;
  transform: FurnitureTransform;
  dimensions: FurnitureDimensions;
  room_id: string;
  attachment: "free" | "wall" | "fixed";
  asset_ref: { kind: string; ref: string };
  provenance: string;
  confidence: number;
  visible?: boolean;
  material_id?: string;
};

export type Camera = {
  id: string;
  projection: "perspective";
  image_size: { width: number; height: number };
  position: { x: number; y: number; z: number };
  look_at: { x: number; y: number; z: number };
  up: { x: number; y: number; z: number };
};

export type Material = {
  id: string;
  color?: string;
  texture?: string | Record<string, unknown>;
  provenance: string;
};

export type SpatialModel = {
  schema_version: "2.0";
  profile: "orthogonal_v1";
  model_id: string;
  revision: number;
  status: SpatialStatus;
  units: { length: "mm"; angle: "deg" };
  coordinates: { origin: string; handedness: "right" };
  source: {
    asset_id: string;
    kind: string;
    sha256: string;
    provenance: string;
  };
  confidence: number;
  rooms: Room[];
  walls: Wall[];
  openings: Opening[];
  furniture_instances: Furniture[];
  cameras: Camera[];
  materials: Material[];
  content_hash?: string;
};

export type Envelope = {
  model: SpatialModel;
  hash: string;
  note: string;
  created_at: string;
};

export type Revision = {
  revision: number;
  status: SpatialStatus;
  hash: string;
  note: string;
  created_at: string;
};

export type AffineMatrix = {
  a: number;
  b: number;
  c: number;
  d: number;
  e: number;
  f: number;
};

function extendBounds(current: Bounds | undefined, next: Bounds): Bounds {
  if (!current) return { ...next };
  const left = Math.min(current.x, next.x);
  const top = Math.min(current.y, next.y);
  const right = Math.max(current.x + current.width, next.x + next.width);
  const bottom = Math.max(current.y + current.height, next.y + next.height);
  return { x: left, y: top, width: right - left, height: bottom - top };
}

/** Return the extents of all room rectangles and wall centre-lines/thickness. */
export function modelBounds(model: SpatialModel): Bounds {
  let result: Bounds | undefined;
  for (const room of model.rooms) {
    const [x, y, width, height] = room.rect;
    result = extendBounds(result, { x, y, width, height });
  }
  for (const wall of model.walls) {
    result = extendBounds(result, wallRect(wall));
  }
  return result ?? { x: 0, y: 0, width: 0, height: 0 };
}

/** Return a furniture footprint without treating x/y as a centre point. */
export function furnitureBounds(item: Furniture): Bounds {
  const quarterTurns = Math.round(item.transform.rotation_z / 90);
  const rotated = Math.abs(quarterTurns) % 2 === 1;
  return {
    x: item.transform.x,
    y: item.transform.y,
    width: rotated ? item.dimensions.depth : item.dimensions.width,
    height: rotated ? item.dimensions.width : item.dimensions.depth,
  };
}

/** Format a millimetre value with stable ASCII grouping and no locale dependence. */
export function formatMm(value: number): string {
  if (!Number.isFinite(value))
    throw new RangeError("millimetre value must be finite");
  const normalized = Object.is(value, -0) ? 0 : value;
  const raw = String(normalized);
  const [integer, fraction] = raw.split(".");
  const grouped = integer.replace(/(\d)(?=(\d{3})+$)/g, "$1,");
  return `${grouped}${fraction ? `.${fraction}` : ""} mm`;
}

/** Convert SVG/client coordinates through an affine CTM without a DOM dependency. */
export function clientToWorld(
  clientX: number,
  clientY: number,
  matrix: AffineMatrix,
): Point {
  const determinant = matrix.a * matrix.d - matrix.b * matrix.c;
  if (!Number.isFinite(determinant) || Math.abs(determinant) < 1e-12) {
    throw new Error("cannot invert a singular affine matrix");
  }
  const translatedX = clientX - matrix.e;
  const translatedY = clientY - matrix.f;
  return {
    x: (matrix.d * translatedX - matrix.c * translatedY) / determinant,
    y: (-matrix.b * translatedX + matrix.a * translatedY) / determinant,
  };
}

/** Immutable furniture patch. Nested transforms/dimensions are merged by field. */
export type FurniturePatch = Omit<
  Partial<Furniture>,
  "transform" | "dimensions" | "asset_ref"
> & {
  transform?: Partial<FurnitureTransform>;
  dimensions?: Partial<FurnitureDimensions>;
  asset_ref?: Partial<Furniture["asset_ref"]>;
};

export function updateFurniture(
  model: SpatialModel,
  id: string,
  patch: FurniturePatch,
): SpatialModel {
  let found = false;
  const furniture_instances = model.furniture_instances.map((item) => {
    if (item.id !== id) {
      return {
        ...item,
        transform: { ...item.transform },
        dimensions: { ...item.dimensions },
        asset_ref: { ...item.asset_ref },
      };
    }
    found = true;
    return {
      ...item,
      ...patch,
      transform: { ...item.transform, ...(patch.transform ?? {}) },
      dimensions: { ...item.dimensions, ...(patch.dimensions ?? {}) },
      asset_ref: { ...item.asset_ref, ...(patch.asset_ref ?? {}) },
    };
  });
  if (!found) throw new Error(`unknown furniture instance: ${id}`);
  return {
    ...model,
    rooms: model.rooms.map((room) => ({
      ...room,
      boundary_wall_ids: [...room.boundary_wall_ids],
    })),
    walls: model.walls.map((wall) => ({ ...wall })),
    openings: model.openings.map((opening) => ({ ...opening })),
    furniture_instances,
    cameras: model.cameras.map((camera) => ({
      ...camera,
      image_size: { ...camera.image_size },
      position: { ...camera.position },
      look_at: { ...camera.look_at },
      up: { ...camera.up },
    })),
    materials: model.materials.map((material) => ({ ...material })),
  };
}

/** Plan-view rectangle for a wall centre-line and its thickness. */
export function wallRect(wall: Wall): Bounds {
  if (wall.axis === "h") {
    return {
      x: wall.x,
      y: wall.y - wall.thickness / 2,
      width: wall.length,
      height: wall.thickness,
    };
  }
  return {
    x: wall.x - wall.thickness / 2,
    y: wall.y,
    width: wall.thickness,
    height: wall.length,
  };
}

/** Plan-view opening rectangle on its host wall, positioned by wall offset. */
export function openingRect(opening: Opening, wall: Wall): Bounds {
  if (wall.axis === "h") {
    return {
      x: wall.x + opening.offset,
      y: wall.y - wall.thickness / 2,
      width: opening.width,
      height: wall.thickness,
    };
  }
  return {
    x: wall.x - wall.thickness / 2,
    y: wall.y + opening.offset,
    width: wall.thickness,
    height: opening.width,
  };
}
