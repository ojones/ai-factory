import path from "node:path";

export function dataPath(name: string): string {
  return path.join(process.env.DATA_DIR ?? "./data", name);
}
