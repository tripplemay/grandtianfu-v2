import type { Room, SpatialModel, Wall } from "./model";

const EPSILON = 1e-9;
const MIN_ROOM_SIZE = 1;

export type ResizeDimensionLimits = {
  current: number;
  min: number;
  max: number;
  canResize: boolean;
  reason?: string;
};

export type RoomResizeLimits = {
  roomId: string;
  x: number;
  y: number;
  maxX: number;
  maxY: number;
  width: ResizeDimensionLimits;
  height: ResizeDimensionLimits;
  canResizeWidth: boolean;
  canResizeHeight: boolean;
};

function same(a: number, b: number): boolean {
  return Math.abs(a - b) <= EPSILON;
}

function roomOrThrow(model: SpatialModel, roomId: string): Room {
  const room = model.rooms.find((candidate) => candidate.id === roomId);
  if (!room) throw new Error(`unknown room: ${roomId}`);
  return room;
}

function roomWalls(model: SpatialModel, room: Room): Wall[] {
  const byId = new Map(model.walls.map((wall) => [wall.id, wall]));
  return room.boundary_wall_ids.map((wallId) => {
    const wall = byId.get(wallId);
    if (!wall)
      throw new Error(`room ${room.id} references unknown wall: ${wallId}`);
    return wall;
  });
}

function sharedWallIds(model: SpatialModel, roomId: string): Set<string> {
  const ids = new Set<string>();
  for (const room of model.rooms) {
    if (room.id === roomId) continue;
    for (const wallId of room.boundary_wall_ids) ids.add(wallId);
  }
  return ids;
}

type AffectedWalls = { walls: Wall[]; reason?: string };

function affectedWalls(
  model: SpatialModel,
  room: Room,
  dimension: "width" | "height",
): AffectedWalls {
  const [x, y, width, height] = room.rect;
  const walls = roomWalls(model, room);
  const candidates = walls.filter((wall) => {
    if (dimension === "width") {
      return (
        (wall.axis === "h" && (same(wall.y, y) || same(wall.y, y + height))) ||
        (wall.axis === "v" && same(wall.x, x + width))
      );
    }
    return (
      (wall.axis === "v" && (same(wall.x, x) || same(wall.x, x + width))) ||
      (wall.axis === "h" && same(wall.y, y + height))
    );
  });
  if (candidates.length === 0) {
    return {
      walls: [],
      reason: `room ${room.id} has no complete ${dimension} boundary`,
    };
  }

  const shared = sharedWallIds(model, room.id);
  const sharedCandidate = candidates.find((wall) => shared.has(wall.id));
  if (sharedCandidate) {
    return {
      walls: candidates,
      reason: `${dimension} boundary wall ${sharedCandidate.id} is shared by another room`,
    };
  }

  // A segmented side needs topology-aware redistribution. Stage 2 refuses it
  // rather than silently changing a segment's length or moving an opening.
  const horizontal = candidates.filter((wall) => wall.axis === "h");
  const vertical = candidates.filter((wall) => wall.axis === "v");
  if (horizontal.length > 2 || vertical.length > 2) {
    return {
      walls: candidates,
      reason: `${dimension} boundary has unsupported wall segmentation`,
    };
  }
  return { walls: candidates };
}

function cloneModel(model: SpatialModel): SpatialModel {
  return {
    ...model,
    rooms: model.rooms.map((room) => ({
      ...room,
      rect: [...room.rect] as [number, number, number, number],
      boundary_wall_ids: [...room.boundary_wall_ids],
    })),
    walls: model.walls.map((wall) => ({ ...wall })),
    openings: model.openings.map((opening) => ({ ...opening })),
    furniture_instances: model.furniture_instances.map((item) => ({
      ...item,
      transform: { ...item.transform },
      dimensions: { ...item.dimensions },
      asset_ref: { ...item.asset_ref },
    })),
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

function dimensionLimits(
  model: SpatialModel,
  room: Room,
  dimension: "width" | "height",
): ResizeDimensionLimits {
  const current = dimension === "width" ? room.rect[2] : room.rect[3];
  const affected = affectedWalls(model, room, dimension);
  return {
    current,
    min: MIN_ROOM_SIZE,
    max: affected.reason ? current : Number.POSITIVE_INFINITY,
    canResize: !affected.reason,
    ...(affected.reason ? { reason: affected.reason } : {}),
  };
}

/** Return the dimensions a room can safely edit without changing shared topology. */
export function roomResizeLimits(
  model: SpatialModel,
  roomId: string,
): RoomResizeLimits {
  const room = roomOrThrow(model, roomId);
  const [x, y, width, height] = room.rect;
  const widthLimits = dimensionLimits(model, room, "width");
  const heightLimits = dimensionLimits(model, room, "height");
  return {
    roomId,
    x,
    y,
    maxX: x + width,
    maxY: y + height,
    width: widthLimits,
    height: heightLimits,
    canResizeWidth: widthLimits.canResize,
    canResizeHeight: heightLimits.canResize,
  };
}

/**
 * Resize one room as an immutable geometry transaction. Furniture and openings
 * are deliberately copied unchanged; the backend performs collision checks.
 */
export function resizeRoom(
  model: SpatialModel,
  roomId: string,
  width: number,
  height: number,
): SpatialModel {
  if (
    !Number.isFinite(width) ||
    !Number.isFinite(height) ||
    width <= 0 ||
    height <= 0
  ) {
    throw new Error("room width and height must be finite and > 0");
  }
  const room = roomOrThrow(model, roomId);
  const limits = roomResizeLimits(model, roomId);
  if (
    width < limits.width.min ||
    (width !== limits.width.current && !limits.canResizeWidth)
  ) {
    throw new Error(
      limits.width.reason ?? "room width is outside resize limits",
    );
  }
  if (
    height < limits.height.min ||
    (height !== limits.height.current && !limits.canResizeHeight)
  ) {
    throw new Error(
      limits.height.reason ?? "room height is outside resize limits",
    );
  }

  const next = cloneModel(model);
  const nextRoom = next.rooms.find((candidate) => candidate.id === roomId)!;
  const [x, y] = room.rect;
  nextRoom.rect = [x, y, width, height];
  const nextRoomWallIds = new Set(nextRoom.boundary_wall_ids);
  const nextWalls = next.walls.filter((wall) => nextRoomWallIds.has(wall.id));
  const oldWidth = room.rect[2];
  const oldHeight = room.rect[3];
  const widthChanged = width !== oldWidth;
  const heightChanged = height !== oldHeight;

  for (const wall of nextWalls) {
    const originalX = wall.x;
    const originalY = wall.y;
    if (widthChanged) {
      if (
        wall.axis === "h" &&
        (same(originalY, y) || same(originalY, y + oldHeight))
      ) {
        wall.x = x;
        wall.length = width;
      } else if (wall.axis === "v" && same(originalX, x + oldWidth)) {
        wall.x = x + width;
      }
    }
    if (heightChanged) {
      if (
        wall.axis === "v" &&
        (same(originalX, x) || same(originalX, x + oldWidth))
      ) {
        wall.y = y;
        wall.length = height;
      } else if (wall.axis === "h" && same(originalY, y + oldHeight)) {
        wall.x = x;
        wall.y = y + height;
      }
    }
  }
  return next;
}
