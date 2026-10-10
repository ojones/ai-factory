import { Router } from "express";
import { isFeatureEnabled } from "../feature-flags";

export const greetingRouter = Router();

greetingRouter.get("/api/greeting", async (_req, res) => {
  if (!(await isFeatureEnabled(res, "greeting"))) {
    res.status(404).json({ error: "not found" });
    return;
  }
  res.json({ message: "hello" });
});
