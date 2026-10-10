import { describe, expect, it } from "vitest";
import { median } from "../lib/stats";

describe("median", () => {
  it("returns the middle value of an odd-length array", () => {
    expect(median([3, 1, 2])).toBe(2);
  });
});
