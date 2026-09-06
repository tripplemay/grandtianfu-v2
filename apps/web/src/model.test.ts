import { describe, expect, it } from "vitest";
import {
  clientToWorld,
  formatMm,
  furnitureBounds,
  modelBounds,
  openingRect,
  type Furniture,
  type SpatialModel,
  updateFurniture,
  wallRect,
} from "./model";

const furniture = (rotation_z = 0): Furniture => ({
  id: "chair-1",
  catalog_id: "chair",
  transform: { x: 1200.25, y: 800.5, z: 0, rotation_z },
  dimensions: { width: 900.75, depth: 500.5, height: 800 },
  room_id: "living",
  attachment: "free",
  asset_ref: { kind: "parametric", ref: "chair" },
  provenance: "test",
  confidence: 1,
});

const model: SpatialModel = {
  schema_version: "2.0",
  profile: "orthogonal_v1",
  model_id: "model-1",
  revision: 1,
  status: "confirmed",
  units: { length: "mm", angle: "deg" },
  coordinates: { origin: "south-west", handedness: "right" },
  source: {
    asset_id: "asset-1",
    kind: "fixture",
    sha256: "hash",
    provenance: "test",
  },
  confidence: 1,
  rooms: [
    {
      id: "living",
      name: "Living",
      kind: "living",
      rect: [0, 0, 6000, 4000],
      boundary_wall_ids: ["north", "south", "west", "east"],
    },
  ],
  walls: [
    {
      id: "north",
      axis: "h",
      x: 0,
      y: 0,
      length: 6000,
      thickness: 200,
      bottom_z: 0,
      top_z: 2700,
    },
    {
      id: "south",
      axis: "h",
      x: 0,
      y: 4000,
      length: 6000,
      thickness: 200,
      bottom_z: 0,
      top_z: 2700,
    },
    {
      id: "west",
      axis: "v",
      x: 0,
      y: 0,
      length: 4000,
      thickness: 200,
      bottom_z: 0,
      top_z: 2700,
    },
    {
      id: "east",
      axis: "v",
      x: 6000,
      y: 0,
      length: 4000,
      thickness: 200,
      bottom_z: 0,
      top_z: 2700,
    },
  ],
  openings: [],
  furniture_instances: [furniture()],
  cameras: [],
  materials: [],
};

describe("model geometry", () => {
  it("computes full room and centred wall extents", () => {
    expect(modelBounds(model)).toEqual({
      x: -100,
      y: -100,
      width: 6200,
      height: 4200,
    });
    expect(wallRect(model.walls[0])).toEqual({
      x: 0,
      y: -100,
      width: 6000,
      height: 200,
    });
    expect(wallRect(model.walls[2])).toEqual({
      x: -100,
      y: 0,
      width: 200,
      height: 4000,
    });
  });

  it.each([0, 180, 360])("keeps width/depth for %d degrees", (rotation) => {
    expect(furnitureBounds(furniture(rotation))).toEqual({
      x: 1200.25,
      y: 800.5,
      width: 900.75,
      height: 500.5,
    });
  });

  it.each([90, 270, -90])("swaps width/depth for %d degrees", (rotation) => {
    expect(furnitureBounds(furniture(rotation))).toEqual({
      x: 1200.25,
      y: 800.5,
      width: 500.5,
      height: 900.75,
    });
  });

  it("places openings along horizontal and vertical walls", () => {
    const opening = {
      id: "window",
      host_wall_id: "north",
      kind: "window",
      offset: 1200,
      width: 1500,
      height: 1200,
      bottom_z: 900,
    };
    expect(openingRect(opening, model.walls[0])).toEqual({
      x: 1200,
      y: -100,
      width: 1500,
      height: 200,
    });
    expect(
      openingRect({ ...opening, host_wall_id: "west" }, model.walls[2]),
    ).toEqual({ x: -100, y: 1200, width: 200, height: 1500 });
  });
});

describe("pure interaction helpers", () => {
  it("inverts pan, zoom, rotation and non-uniform affine transforms", () => {
    const matrix = { a: 2, b: 0.5, c: -0.25, d: 3, e: 120, f: -80 };
    const world = { x: 37.25, y: 91.5 };
    const client = {
      x: matrix.a * world.x + matrix.c * world.y + matrix.e,
      y: matrix.b * world.x + matrix.d * world.y + matrix.f,
    };
    expect(clientToWorld(client.x, client.y, matrix).x).toBeCloseTo(
      world.x,
      10,
    );
    expect(clientToWorld(client.x, client.y, matrix).y).toBeCloseTo(
      world.y,
      10,
    );
  });

  it("rejects singular transforms", () => {
    expect(() =>
      clientToWorld(1, 2, { a: 1, b: 2, c: 2, d: 4, e: 0, f: 0 }),
    ).toThrow(/singular/);
  });

  it("formats millimetres deterministically", () => {
    expect(formatMm(1234567.25)).toBe("1,234,567.25 mm");
    expect(formatMm(-0)).toBe("0 mm");
  });

  it("updates immutably and preserves omitted coordinates", () => {
    const next = updateFurniture(model, "chair-1", {
      transform: { rotation_z: 90 },
    });
    expect(next).not.toBe(model);
    expect(next.furniture_instances).not.toBe(model.furniture_instances);
    expect(next.furniture_instances[0].transform).toEqual({
      x: 1200.25,
      y: 800.5,
      z: 0,
      rotation_z: 90,
    });
    expect(model.furniture_instances[0].transform.rotation_z).toBe(0);
    expect(model.furniture_instances[0].dimensions.width).toBe(900.75);
  });

  it("round-trips decimal JSON without snapping", () => {
    const encoded = JSON.stringify(model);
    const decoded = JSON.parse(encoded) as SpatialModel;
    expect(decoded.furniture_instances[0].transform.x).toBe(1200.25);
    expect(decoded.furniture_instances[0].dimensions.width).toBe(900.75);
  });
});
