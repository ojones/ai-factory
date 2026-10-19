// Every flag in flags.json is checked in one place and tested both ways: a withFlag(slug, false, ...) test and a withFlag(slug, true, ...) test,
// so dark mode is unit tested before review. The Orchestrator owns this file in every app (a coder commit that touches it is rejected; template
// sync copies it in). `npm run check` runs it. Its cases are in agents/lint-fixtures/cases.json ("flagCases").
import { readFileSync, readdirSync, existsSync } from "node:fs";
import { join, relative } from "node:path";

const TEST_FILE = /(\.test\.|\.spec\.|\/tests?\/|\/__tests__\/)/;
const SOURCE_FILE = /\.(ts|tsx|js|jsx|mjs)$/;
const SKIPPED_DIRS = new Set(["node_modules", "dist", ".git"]);

function stripComments(text) {
  return text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
}

function count(text, pattern) {
  return (text.match(pattern) ?? []).length;
}

// slugs: the slugs in flags.json. files: { path: content } of the app's source and test files. Returns the problems, one string each.
export function flagProblems(slugs, files) {
  const problems = [];
  const code = Object.entries(files).map(([path, text]) => [path, stripComments(text)]);
  for (const slug of slugs) {
    const lit = `["'\`]${slug.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}["'\`]`;
    const tests = code.filter(([path]) => TEST_FILE.test(path));
    const off = tests.some(([, text]) => new RegExp(`withFlag\\(\\s*${lit}\\s*,\\s*false\\b`).test(text));
    const on = tests.some(([, text]) => new RegExp(`withFlag\\(\\s*${lit}\\s*,\\s*true\\b`).test(text));
    if (!off)
      problems.push(
        `Flag "${slug}" has no flag-off test: add a test inside withFlag("${slug}", false, ...) that shows the old behaviour is unchanged.`,
      );
    if (!on)
      problems.push(
        `Flag "${slug}" has no flag-on test: add a test inside withFlag("${slug}", true, ...) that shows the new behaviour.`,
      );
    const checks = code
      .filter(([path]) => !TEST_FILE.test(path))
      .reduce((n, [, text]) => n + count(text, new RegExp(`isFeatureEnabled\\([^)]*${lit}`, "g")), 0);
    if (checks > 1)
      problems.push(
        `Flag "${slug}" is checked in ${checks} places: check it once, at the single entry point of the change.`,
      );
  }
  return problems;
}

function collect(root, dir, out) {
  if (!existsSync(dir)) return;
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (SKIPPED_DIRS.has(entry.name)) continue;
    const full = join(dir, entry.name);
    if (entry.isDirectory()) collect(root, full, out);
    else if (SOURCE_FILE.test(entry.name)) out[relative(root, full).split("\\").join("/")] = readFileSync(full, "utf8");
  }
}

function main() {
  const root = process.cwd();
  const manifest = join(root, "flags.json");
  const slugs = existsSync(manifest) ? JSON.parse(readFileSync(manifest, "utf8")).map((f) => f.slug) : [];
  const files = {};
  for (const dir of ["backend", "frontend"]) collect(root, join(root, dir), files);
  const problems = flagProblems(slugs, files);
  for (const p of problems) console.error(p);
  process.exit(problems.length ? 1 : 0);
}

if (process.argv[1] && process.argv[1].endsWith("check-flags.mjs")) {
  if (process.argv.includes("--stdin")) {
    const { slugs, files } = JSON.parse(readFileSync(0, "utf8"));
    console.log(JSON.stringify(flagProblems(slugs, files)));
  } else main();
}
