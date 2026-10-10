import { Router } from "express";

interface Todo {
  id: string;
  title: string;
  done: boolean;
}

const todos: Todo[] = [];
let nextId = 1;

export const todosRouter = Router();

todosRouter.post("/api/todos", (req, res) => {
  const title = req.body?.title;
  if (typeof title !== "string" || title.trim() === "") {
    res.status(400).json({ error: "title must be a non-blank string" });
    return;
  }
  const todo: Todo = { id: String(nextId++), title: title.trim(), done: false };
  todos.push(todo);
  res.status(201).json(todo);
});

todosRouter.get("/api/todos", (_req, res) => {
  res.json(todos);
});

todosRouter.get("/api/todos/:id", (req, res) => {
  const todo = todos.find((t) => t.id === req.params.id);
  if (!todo) {
    res.status(404).json({ error: "not found" });
    return;
  }
  res.json(todo);
});

todosRouter.delete("/api/todos/:id", (req, res) => {
  const index = todos.findIndex((t) => t.id === req.params.id);
  if (index === -1) {
    res.status(404).json({ error: "not found" });
    return;
  }
  todos.splice(index, 1);
  res.status(204).end();
});
