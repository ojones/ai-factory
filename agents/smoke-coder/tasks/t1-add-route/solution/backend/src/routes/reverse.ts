import { Router } from "express";

export const reverseRouter = Router();

reverseRouter.get("/api/reverse", (req, res) => {
  const text = req.query.text;
  if (typeof text !== "string" || text.length === 0 || text.length > 200) {
    res.status(400).json({ error: "text must be 1 to 200 characters" });
    return;
  }
  res.json({ reversed: Array.from(text).reverse().join("") });
});
