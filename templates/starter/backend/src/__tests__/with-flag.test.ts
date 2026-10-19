import { describe, expect, it } from "vitest";
import { featureKey } from "../feature-flags";
import { getFeatureFlagClient } from "../feature-flags";
import { withFlag } from "./with-flag";

const read = () => getFeatureFlagClient().getBooleanValue(featureKey("demo"), false);

describe("withFlag", () => {
  it("turns the flag on inside, and restores it after", async () => {
    await withFlag("demo", true, async () => expect(await read()).toBe(true));
    expect(await read()).toBe(false);
  });

  it("turns the flag off inside", async () => {
    await withFlag("demo", false, async () => expect(await read()).toBe(false));
  });

  it("returns what fn returns and restores the flag when fn throws", async () => {
    expect(await withFlag("demo", true, () => 7)).toBe(7);
    await expect(
      withFlag("demo", true, () => {
        throw new Error("boom");
      }),
    ).rejects.toThrow("boom");
    expect(await read()).toBe(false);
  });
});
