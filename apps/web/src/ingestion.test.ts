import { describe, expect, it } from "vitest";
import {
  cameraError,
  readyToReview,
  reviewChecks,
  reviewObjects,
  validScale,
  type ReviewCheck,
} from "./ingestion";
import type { Camera, SpatialModel } from "./model";

const model = {
  status: "draft",
  rooms: [{ id: "room-1", name: "Room" }],
  walls: [{ id: "wall-1" }],
  openings: [{ id: "door-1" }],
} as SpatialModel;

describe("import review gates", () => {
  const all = new Set(reviewObjects(model).map((item) => item.id));
  const checks = new Set(Object.keys(reviewChecks) as ReviewCheck[]);
  it("requires explicit positive finite scale", () => {
    for (const value of ["", " ", "0", "-1", "Infinity", "NaN", "10001"])
      expect(validScale(value)).toBe(false);
    expect(validScale("10.125")).toBe(true);
  });
  it("requires every object and every review check", () => {
    expect(readyToReview(model, new Set(), checks, false)).toBe(false);
    expect(readyToReview(model, all, new Set(), false)).toBe(false);
    expect(readyToReview(model, all, checks, false)).toBe(true);
  });
  it("rejects unsaved, already confirmed, and empty geometry", () => {
    expect(readyToReview(model, all, checks, true)).toBe(false);
    expect(
      readyToReview({ ...model, status: "confirmed" }, all, checks, false),
    ).toBe(false);
    expect(readyToReview({ ...model, rooms: [] }, all, checks, false)).toBe(
      false,
    );
  });
});

describe("explicit camera", () => {
  const camera: Camera = {
    id: "camera-main",
    projection: "perspective",
    image_size: { width: 800, height: 600 },
    position: { x: 1000, y: 1000, z: 1800 },
    look_at: { x: 2000, y: 2000, z: 800 },
    up: { x: 0, y: 0, z: 1 },
  };
  it("validates view and up vectors", () => {
    expect(cameraError(camera)).toBe("");
    expect(cameraError({ ...camera, look_at: camera.position })).not.toBe("");
    expect(cameraError({ ...camera, up: { x: 1, y: 1, z: -1 } })).not.toBe("");
    expect(
      cameraError({ ...camera, position: { ...camera.position, z: Infinity } }),
    ).not.toBe("");
  });
});
