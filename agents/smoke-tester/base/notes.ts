import { Router } from "express";
import { isFeatureEnabled } from "../feature-flags";

type Note = { id: number; text: string };

export function notesRouter(): Router {
  const router = Router();
  const notes: Note[] = [];
  let nextId = 1;

  router.use("/api/notes", async (_req, res, next) => {
    if (!(await isFeatureEnabled(res, "notes-api"))) {
      res.status(404).json({ error: "not found" });
      return;
    }
    next();
  });

  router.post("/api/notes", (req, res) => {
    const text = req.body?.text;
    if (typeof text !== "string" || text.trim() === "") {
      res.status(400).json({ error: "text must be a non-empty string" });
      return;
    }
    const note = { id: nextId++, text: text.trim() };
    notes.push(note);
    res.status(201).json(note);
  });

  router.get("/api/notes", (_req, res) => {
    res.json(notes);
  });

  router.get("/api/notes/:id", (req, res) => {
    const id = Number(req.params.id);
    if (!Number.isInteger(id) || id < 1) {
      res.status(400).json({ error: "id must be a positive whole number" });
      return;
    }
    const note = notes.find((n) => n.id === id);
    if (!note) {
      res.status(404).json({ error: "note not found" });
      return;
    }
    res.json(note);
  });

  return router;
}
