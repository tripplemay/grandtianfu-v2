import { describe, expect, it } from "vitest";
import { resizeRoom, roomResizeLimits } from "./editing";
import type { SpatialModel } from "./model";

function singleRoomModel(): SpatialModel {
  return {
    schema_version: "2.0",
    profile: "orthogonal_v1",
    model_id: "resize-model",
    revision: 1,
    status: "confirmed",
    units: { length: "mm", angle: "deg" },
    coordinates: { origin: "south-west", handedness: "right" },
    source: {
      asset_id: "asset",
      kind: "fixture",
      sha256: "hash",
      provenance: "test",
    },
    confidence: 1,
    rooms: [
      {
        id: "room",
        name: "Room",
        kind: "living",
        rect: [100.25, 200.5, 4000.75, 3000.125],
        boundary_wall_ids: ["n", "s", "w", "e"],
      },
    ],
    walls: [
      {
        id: "n",
        axis: "h",
        x: 100.25,
        y: 200.5,
        length: 4000.75,
        thickness: 120,
        bottom_z: 0,
        top_z: 2700,
      },
      {
        id: "s",
        axis: "h",
        x: 100.25,
        y: 3200.625,
        length: 4000.75,
        thickness: 120,
        bottom_z: 0,
        top_z: 2700,
      },
      {
        id: "w",
        axis: "v",
        x: 100.25,
        y: 200.5,
        length: 3000.125,
        thickness: 120,
        bottom_z: 0,
        top_z: 2700,
      },
      {
        id: "e",
        axis: "v",
        x: 4101,
        y: 200.5,
        length: 3000.125,
        thickness: 120,
        bottom_z: 0,
        top_z: 2700,
      },
    ],
    openings: [
      {
        id: "window",
        host_wall_id: "n",
        kind: "window",
        offset: 1000,
        width: 800,
        height: 1200,
        bottom_z: 800,
      },
    ],
    furniture_instances: [],
    cameras: [],
    materials: [],
  };
}

function mergeModel(): SpatialModel {
  const model = singleRoomModel();
  model.rooms.push({
    id: "other",
    name: "Other",
    kind: "room",
    rect: [4101, 200.5, 2000, 3000.125],
    boundary_wall_ids: ["e", "other-n", "other-s", "other-e"],
  });
  model.walls.push(
    {
      id: "other-n",
      axis: "h",
      x: 4101,
      y: 200.5,
      length: 2000,
      thickness: 120,
      bottom_z: 0,
      top_z: 2700,
    },
    {
      id: "other-s",
      axis: "h",
      x: 4101,
      y: 3200.625,
      length: 2000,
      thickness: 120,
      bottom_z: 0,
      top_z: 2700,
    },
    {
      id: "other-e",
      axis: "v",
      x: 6101,
      y: 200.5,
      length: 3000.125,
      thickness: 120,
      bottom_z: 0,
      top_z: 2700,
    },
  );
  return model;
}

describe("room editing", () => {
  it("resizes a single room and synchronizes its boundary walls", () => {
    const model = singleRoomModel();
    const next = resizeRoom(model, "room", 4500.875, 2800.25);
    expect(next).not.toBe(model);
    expect(next.rooms[0].rect).toEqual([100.25, 200.5, 4500.875, 2800.25]);
    expect(
      next.walls.map(({ id, x, y, length }) => ({ id, x, y, length })),
    ).toEqual([
      { id: "n", x: 100.25, y: 200.5, length: 4500.875 },
      { id: "s", x: 100.25, y: 3000.75, length: 4500.875 },
      { id: "w", x: 100.25, y: 200.5, length: 2800.25 },
      { id: "e", x: 4601.125, y: 200.5, length: 2800.25 },
    ]);
    expect(next.openings).toEqual(model.openings);
    expect(next.furniture_instances).toEqual(model.furniture_instances);
    expect(model.rooms[0].rect).toEqual([100.25, 200.5, 4000.75, 3000.125]);
    expect(model.walls[1].y).toBe(3200.625);
  });

  it("reports shared-wall dimensions as blocked and rejects only those changes", () => {
    const model = mergeModel();
    const limits = roomResizeLimits(model, "room");
    expect(limits.x).toBe(100.25);
    expect(limits.y).toBe(200.5);
    expect(limits.maxX).toBe(4101);
    expect(limits.maxY).toBe(3200.625);
    expect(limits.canResizeWidth).toBe(false);
    expect(limits.canResizeHeight).toBe(false);
    expect(() => resizeRoom(model, "room", 4000.75, 3001)).toThrow(/shared/);
    expect(() => resizeRoom(model, "room", 4001, 3000.125)).toThrow(/shared/);
  });

  it("allows an unchanged shared dimension and preserves exact decimals", () => {
    const model = mergeModel();
    const next = resizeRoom(model, "room", 4000.75, 3000.125);
    expect(next.rooms[0].rect).toEqual(model.rooms[0].rect);
    expect(next.walls).toEqual(model.walls);
    expect(next).not.toBe(model);
  });

  it("rejects non-positive and non-finite dimensions", () => {
    const model = singleRoomModel();
    expect(() => resizeRoom(model, "room", 0, 3000)).toThrow(/finite/);
    expect(() => resizeRoom(model, "room", Number.NaN, 3000)).toThrow(/finite/);
  });
});
