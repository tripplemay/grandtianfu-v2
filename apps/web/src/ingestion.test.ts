import { describe, expect, it } from "vitest";
import {
  cameraError,
  readyToReview,
  reviewChecks,
  reviewChecksFor,
  reviewObjects,
  roiCandidates,
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
  it("blocks confirmation when recognition leaves structural candidates", () => {
    const blocked = {
      ...model,
      ingest: { ingest_id: "job", mm_per_pixel: 1, hard_blockers: [{ code: "partial_plan" }] },
    } as SpatialModel;
    expect(readyToReview(blocked, all, checks, false)).toBe(false);
  });
});

describe("manual topology confirmation", () => {
  const topologyModel = {
    ...model,
    source: { provenance: "manual_topology" },
    rooms: [{ id: "room-1", name: "Room", kind: "living", merge_group_id: "merge-1" }, { id: "room-2", name: "Dining", kind: "dining", merge_group_id: "merge-1" }],
    openings: [{ id: "door-1", kind: "door" }],
    ingest: { ingest_id: "topology-job", mm_per_pixel: 10,
      topology: { version: "manual-topology-0.1", reviewed_object_ids: ["room-1", "room-2", "wall-1", "door-1", "merge-1"] },
      hard_blockers: [{ code: "manual_trace_requires_topology_review" }] },
  } as unknown as SpatialModel;
  const all = new Set(reviewObjects(topologyModel).map((object) => object.id));
  const checks = new Set(Object.keys(reviewChecksFor(topologyModel)) as ReviewCheck[]);
  it("requires topology, coverage and merge group review", () => {
    expect(readyToReview(topologyModel, all, checks, false)).toBe(true);
    expect(readyToReview(topologyModel, all, new Set(Object.keys(reviewChecks) as ReviewCheck[]), false)).toBe(false);
    expect(readyToReview(topologyModel, new Set([...all].filter((id) => id !== "merge-1")), checks, false)).toBe(false);
  });
  it("cannot waive unknown blockers, legacy blockers or unclassified rooms", () => {
    expect(readyToReview({ ...topologyModel, ingest: { ...topologyModel.ingest!, hard_blockers: [{ code: "partial_plan" }] } }, all, checks, false)).toBe(false);
    expect(readyToReview({ ...topologyModel, ingest: { ...topologyModel.ingest!, blockers: ["incomplete"] } }, all, checks, false)).toBe(false);
    expect(readyToReview({ ...topologyModel, rooms: topologyModel.rooms.map((room) => ({ ...room, kind: "unknown" })) }, all, checks, false)).toBe(false);
  });
});

describe("ROI evidence", () => {
  it("reads and validates preprocessing candidates without promoting them to geometry", () => {
    const candidates = roiCandidates({
      ingest: {
        ingest_id: "job",
        mm_per_pixel: 10,
        preprocessing: {
          roi_candidates: [
            { id: "roi-2", rank: 2, evidence_bbox: [20, 30, 40, 50] },
            { id: "roi-1", rank: 1, evidence_bbox: [1, 2, 3, 4] },
            { id: "bad", evidence_bbox: [0, 0, -1, 2] },
          ],
        },
      },
      rooms: [],
      walls: [],
      openings: [],
    } as unknown as SpatialModel);
    expect(candidates.map((item) => item.id)).toEqual(["roi-1", "roi-2"]);
    expect(candidates[0].evidence_bbox).toEqual([1, 2, 3, 4]);
  });

  it("deduplicates evidence and falls back to the audit evidence path", () => {
    const candidates = roiCandidates({
      ingest: {
        ingest_id: "job",
        mm_per_pixel: 10,
        preprocessing: { roi_candidates: [{ id: "same", evidence_bbox: [1, 1, 5, 5] }] },
        evidence: {
          roi_candidates: [
            { id: "same", evidence_bbox: [2, 2, 5, 5] },
            { id: "other", evidence_bbox: [3, 3, 5, 5] },
          ],
        },
      },
      rooms: [],
      walls: [],
      openings: [],
    } as unknown as SpatialModel);
    expect(candidates.map((item) => item.id)).toEqual(["same", "other"]);
    expect(candidates[0].evidence_bbox).toEqual([1, 1, 5, 5]);
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
