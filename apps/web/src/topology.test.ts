import { describe, expect, it } from "vitest";
import { topologyFieldError, topologyReviewIds } from "./topology";
import type { SpatialModel } from "./model";

const model = {
  rooms: [{ id: "r1" }, { id: "r2" }],
  walls: [{ id: "w1", length: 3000, top_z: 2800 }],
  openings: [{ id: "o0" }],
} as unknown as SpatialModel;

describe("topology review helpers", () => {
  it("validates opening span against its host wall", () => {
    expect(topologyFieldError({ host_wall_id: "w1", kind: "door", offset: 100, width: 900, height: 2100, bottom_z: 0 }, model)).toBe("");
    expect(topologyFieldError({ host_wall_id: "w1", kind: "door", offset: 2500, width: 900, height: 2100, bottom_z: 0 }, model)).toContain("长度");
  });

  it("builds a complete review set without duplicate ids", () => {
    expect(topologyReviewIds(model, [{ id: "o1", host_wall_id: "w1", kind: "door", offset: 0, width: 900, height: 2100, bottom_z: 0 }], [{ id: "m1", room_ids: ["r1", "r2"] }])).toEqual(["r1", "r2", "w1", "o0", "o1", "m1"]);
  });
});
