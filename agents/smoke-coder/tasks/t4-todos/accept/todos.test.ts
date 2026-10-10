import { describe, expect, it } from "vitest";
import request from "supertest";
import { createApp } from "../../app";

const create = (title: unknown) => request(createApp()).post("/api/todos").send({ title });

describe("todos", () => {
  it("creates a todo and trims the title", async () => {
    const res = await create("  buy milk ");
    expect(res.status).toBe(201);
    expect(res.body).toMatchObject({ title: "buy milk", done: false });
    expect(res.body.id).toBeDefined();
  });
  it.each([[undefined], [""], ["   "], [42]])("rejects title %s", async (title) => {
    const res = await create(title);
    expect(res.status).toBe(400);
    expect(typeof res.body.error).toBe("string");
  });
  it("gives each todo a distinct id", async () => {
    const a = await create("a");
    const b = await create("b");
    expect(a.body.id).not.toEqual(b.body.id);
  });
  it("lists todos in creation order", async () => {
    const first = await create("order-1");
    const second = await create("order-2");
    const list = (await request(createApp()).get("/api/todos")).body as { id: unknown }[];
    const ids = list.map((t) => t.id);
    expect(ids.indexOf(first.body.id)).toBeGreaterThanOrEqual(0);
    expect(ids.indexOf(first.body.id)).toBeLessThan(ids.indexOf(second.body.id));
  });
  it("gets one todo or 404", async () => {
    const made = await create("find me");
    const found = await request(createApp()).get(`/api/todos/${made.body.id}`);
    expect(found.status).toBe(200);
    expect(found.body.title).toBe("find me");
    expect((await request(createApp()).get("/api/todos/does-not-exist")).status).toBe(404);
  });
  it("deletes a todo, then 404s", async () => {
    const made = await create("delete me");
    expect((await request(createApp()).delete(`/api/todos/${made.body.id}`)).status).toBe(204);
    expect((await request(createApp()).get(`/api/todos/${made.body.id}`)).status).toBe(404);
    expect((await request(createApp()).delete(`/api/todos/${made.body.id}`)).status).toBe(404);
  });
});
