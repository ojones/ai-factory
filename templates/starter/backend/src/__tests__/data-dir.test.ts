import { afterEach, describe, expect, it } from "vitest";
import { dataPath } from "../data-dir";

describe("dataPath", () => {
  afterEach(() => {
    delete process.env.DATA_DIR;
  });

  it("puts files under DATA_DIR when it is set", () => {
    process.env.DATA_DIR = "/data";

    expect(dataPath("app.db")).toBe("/data/app.db");
  });

  it("falls back to ./data for local development", () => {
    expect(dataPath("app.db")).toBe("data/app.db");
  });
});
