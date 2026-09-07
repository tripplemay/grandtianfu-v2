import type { Opening, SpatialModel } from "./model";

export type TopologyOpeningInput = Omit<Opening, "id" | "provenance" | "confidence"> & { id?: string };
export type TopologyMergeGroupInput = { id?: string; room_ids: string[] };
export type TopologyInput = {
  openings: TopologyOpeningInput[];
  merge_groups: TopologyMergeGroupInput[];
  reviewed_object_ids: string[];
};

export function topologyReviewIds(model: SpatialModel, openings: TopologyOpeningInput[], groups: TopologyMergeGroupInput[]) {
  return Array.from(new Set([
    ...model.rooms.map((room) => room.id),
    ...model.walls.map((wall) => wall.id),
    ...model.openings.map((opening) => opening.id),
    ...openings.map((opening) => opening.id).filter((id): id is string => !!id),
    ...groups.map((group) => group.id).filter((id): id is string => !!id),
  ]));
}

export function topologyFieldError(opening: TopologyOpeningInput, model: SpatialModel) {
  const wall = model.walls.find((item) => item.id === opening.host_wall_id);
  if (!wall) return "请选择有效的宿主墙体";
  if (![opening.offset, opening.width, opening.height, opening.bottom_z].every(Number.isFinite)) return "门窗参数必须是有限数值";
  if (opening.offset < 0 || opening.width <= 0 || opening.height <= 0 || opening.bottom_z < 0) return "偏移、宽度、高度和底标高必须为有效正值";
  if (opening.offset + opening.width > wall.length) return "门窗超出宿主墙体长度";
  if (opening.bottom_z + opening.height > wall.top_z) return "门窗超出墙体高度";
  return "";
}

export function sharedWallEvidence(model: SpatialModel, roomIds: string[], openings: TopologyOpeningInput[]) {
  const pairs = roomIds.slice(1).map((roomId) => {
    const left = model.rooms.find((room) => room.id === roomIds[0]);
    const right = model.rooms.find((room) => room.id === roomId);
    if (!left || !right) return { walls: [], openings: [] };
    const walls = model.walls.filter((wall) => {
      if (!left.boundary_wall_ids.includes(wall.id) || !right.boundary_wall_ids.includes(wall.id)) return false;
      const [x, y, width, height] = left.rect;
      const [ox, oy, owidth, oheight] = right.rect;
      if (wall.axis === "v") return Math.abs((x + width) - ox) < 1e-6 || Math.abs((ox + owidth) - x) < 1e-6;
      return Math.abs((y + height) - oy) < 1e-6 || Math.abs((oy + oheight) - y) < 1e-6;
    });
    const ids = walls.map((wall) => wall.id);
    const connectedOpenings = openings.filter((opening) => walls.some((wall) => {
      if (opening.host_wall_id !== wall.id) return false;
      const [x, y, width, height] = left.rect;
      const [ox, oy, owidth, oheight] = right.rect;
      const sharedStart = wall.axis === "v" ? Math.max(y, oy) : Math.max(x, ox);
      const sharedEnd = wall.axis === "v" ? Math.min(y + height, oy + oheight) : Math.min(x + width, ox + owidth);
      const wallStart = wall.axis === "v" ? wall.y : wall.x;
      const openingStart = wallStart + opening.offset;
      return Math.min(openingStart + opening.width, sharedEnd) - Math.max(openingStart, sharedStart) > 1e-6;
    })).map((opening) => opening.id).filter((id): id is string => !!id);
    return { walls: ids, openings: connectedOpenings };
  });
  return { walls: Array.from(new Set(pairs.flatMap((pair) => pair.walls))), openings: Array.from(new Set(pairs.flatMap((pair) => pair.openings))) };
}
