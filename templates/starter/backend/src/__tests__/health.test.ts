import { describe, expect, it } from "vitest";
import request from "supertest";
import { createApp } from "../app";

// Boot/health-check smoke test, per STANDARDS-CODING.md's test-gate shape.
// Real Managed Apps add unit tests for business logic alongside this.
describe("GET /api/health", () => {
  it("responds 200 with a status payload", async () => {
    const app = createApp();

    const response = await request(app).get("/api/health");

    expect(response.status).toBe(200);
    expect(response.body).toEqual({ status: "ok" });
  });
});
