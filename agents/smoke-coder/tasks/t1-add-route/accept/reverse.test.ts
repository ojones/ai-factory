import { describe, expect, it } from "vitest";
import request from "supertest";
import { createApp } from "../../app";

describe("GET /api/reverse", () => {
  it("reverses text", async () => {
    const res = await request(createApp()).get("/api/reverse").query({ text: "abc" });
    expect(res.status).toBe(200);
    expect(res.body).toEqual({ reversed: "cba" });
  });
  it("accepts exactly 200 characters", async () => {
    const res = await request(createApp()).get("/api/reverse").query({ text: "a".repeat(200) });
    expect(res.status).toBe(200);
  });
  it.each([[undefined], [""], ["a".repeat(201)]])("rejects %s with 400 and an error", async (text) => {
    const res = await request(createApp()).get("/api/reverse").query(text === undefined ? {} : { text });
    expect(res.status).toBe(400);
    expect(typeof res.body.error).toBe("string");
  });
  it("keeps health working", async () => {
    expect((await request(createApp()).get("/api/health")).status).toBe(200);
  });
});
