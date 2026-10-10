import { describe, expect, it } from "vitest";
import { median } from "../../lib/stats";

describe("median (acceptance)", () => {
  it("odd length", () => expect(median([9, 1, 5])).toBe(5));
  it("even length is the mean of the two middle values", () => expect(median([4, 1, 3, 2])).toBe(2.5));
  it("single value", () => expect(median([7])).toBe(7));
  it("empty returns null", () => expect(median([])).toBeNull());
  it("does not modify its input", () => {
    const input = [3, 1, 2];
    median(input);
    expect(input).toEqual([3, 1, 2]);
  });
  it("handles negatives and duplicates", () => expect(median([-2, -2, 4, 10])).toBe(1));
});
