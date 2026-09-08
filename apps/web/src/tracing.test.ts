import { describe, expect, it } from "vitest";
import { dragRect, rectInput, traceError } from "./tracing";

describe("parent-space trace input", () => {
  it("rejects blanks, non-finite, fractional ROI and out-of-bounds rectangles", () => {
    for (const values of [["", "0", "4", "4"], ["0", "0", "NaN", "4"],
      ["-1", "0", "4", "4"], ["0", "0", "101", "4"], ["0", "0", "1.5", "4"]]) {
      expect(rectInput(values, [0, 0, 100, 100], true)).toBeNull();
    }
    expect(rectInput(["10.25", "20", "40.5", "30"], [10, 10, 90, 90])).toEqual([10.25, 20, 40.5, 30]);
  });
  it("normalizes reverse drag and keeps pixel precision", () => {
    expect(dragRect([90.1, 80.2], [10.2, 20.3], true)).toEqual([10, 20, 81, 61]);
    expect(dragRect([20.25, 10.5], [10, 5])).toEqual([10, 5, 10.25, 5.5]);
  });
  it("rejects overlap but allows shared sides and disjoint rooms", () => {
    const left = { name: "Left", kind: "unknown", rect: [10, 10, 20, 20] as [number, number, number, number] };
    expect(traceError([left, { ...left, name: "Right", rect: [30, 10, 20, 20] }], [0, 0, 100, 100])).toBe("");
    expect(traceError([left, { ...left, name: "Other", rect: [29, 10, 20, 20] }], [0, 0, 100, 100])).toContain("重叠");
    expect(traceError([left], [12, 12, 80, 80])).toContain("超出");
  });
});
