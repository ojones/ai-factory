import { readFileSync } from "node:fs";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import request from "supertest";
import { OpenFeature, TypedInMemoryProvider } from "@openfeature/server-sdk";
import { createApp } from "../../app";

const TOKEN = "accept-preview-token";

function flags(killSwitchOn: boolean, greetingOn: boolean) {
  return new TypedInMemoryProvider({
    "test-app.global-kill-switch": { variants: { on: true, off: false }, defaultVariant: killSwitchOn ? "on" : "off" },
    "test-app.feature.greeting": { variants: { on: true, off: false }, defaultVariant: greetingOn ? "on" : "off" },
  });
}

describe("greeting behind its flag", () => {
  beforeEach(() => {
    process.env.PREVIEW_TOKEN = TOKEN;
  });
  afterEach(() => {
    delete process.env.PREVIEW_TOKEN;
  });

  it("is recorded in flags.json", () => {
    const list = JSON.parse(readFileSync(path.resolve(__dirname, "../../../../flags.json"), "utf8"));
    const entry = list.find((f: { slug: string }) => f.slug === "greeting");
    expect(entry).toBeTruthy();
    expect(String(entry.description).length).toBeGreaterThan(0);
  });
  it("is dark while the flag is off", async () => {
    OpenFeature.setProvider(flags(true, false));
    expect((await request(createApp()).get("/api/greeting")).status).toBe(404);
  });
  it("answers when the flag is on", async () => {
    OpenFeature.setProvider(flags(true, true));
    const res = await request(createApp()).get("/api/greeting");
    expect(res.status).toBe(200);
    expect(res.body).toEqual({ message: "hello" });
  });
  it("answers a preview-token request while the flag is off", async () => {
    OpenFeature.setProvider(flags(true, false));
    const res = await request(createApp()).get("/api/greeting").set("X-Preview-Token", TOKEN);
    expect(res.status).toBe(200);
  });
  it("is behind the kill switch", async () => {
    OpenFeature.setProvider(flags(false, true));
    expect((await request(createApp()).get("/api/greeting")).status).toBe(503);
  });
});
