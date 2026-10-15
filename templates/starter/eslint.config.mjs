// The Starter Template's lint rules. Keep this file additive: a rule is added or tightened, never loosened,
// so the learning loop can merge such changes without review (INV-15). The Orchestrator owns this file in every
// app (a coder commit that touches it is rejected; template sync copies it in), so a rule cannot be loosened to
// make a check pass. Every rule here has cases in agents/lint-fixtures/cases.json.
import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";

// A test must be able to fail. Anything whose name starts expect/assert/verify/should counts as an assertion (so a helper called
// `expectStatus` or `assertTodo` is fine, and so is node:assert and supertest's `.expect`); a test that calls none is an error, and a
// test whose only assertions are toBeTruthy/toBeDefined is a warning, because those pass for almost any value.
const ASSERTING = /^(expect|assert|verify|should)/i;
const WEAK = new Set(["toBeTruthy", "toBeDefined"]);
const TEST_NAMES = new Set(["it", "test"]);

function rootName(node) {
  while (node) {
    if (node.type === "Identifier") return node.name;
    node = node.type === "MemberExpression" ? node.object : node.type === "CallExpression" ? node.callee : null;
  }
  return null;
}

function isTestCall(node) {
  let callee = node.callee;
  if (callee.type === "CallExpression") callee = callee.callee; // it.each(rows)("name", fn)
  const head = callee.type === "MemberExpression" ? callee.object : callee;
  const isSkipped = callee.type === "MemberExpression" && ["skip", "todo"].includes(callee.property.name);
  return head.type === "Identifier" && TEST_NAMES.has(head.name) && !isSkipped
    && node.arguments.some((a) => a.type === "ArrowFunctionExpression" || a.type === "FunctionExpression");
}

function testAssertionRule(weakOnly, message) {
  return {
    meta: { type: "problem", schema: [] },
    create(context) {
      const frames = [];
      return {
        CallExpression(node) {
          if (isTestCall(node)) frames.push({ node, asserts: 0, weak: 0 });
          const frame = frames[frames.length - 1];
          if (!frame) return;
          const name = node.callee.type === "MemberExpression" ? node.callee.property.name : node.callee.name;
          if (name === "expect" || (ASSERTING.test(name ?? "") && name !== "expect")) frame.asserts += 1;
          else if (node.callee.type === "MemberExpression" && rootName(node.callee.object) !== "expect" && ASSERTING.test(rootName(node.callee.object) ?? "")) frame.asserts += 1;
          if (WEAK.has(name) && /^expect$/.test(rootName(node.callee.object) ?? "")) frame.weak += 1;
        },
        "CallExpression:exit"(node) {
          if (frames[frames.length - 1]?.node !== node) return;
          const { asserts, weak } = frames.pop();
          if (weakOnly ? asserts > 0 && weak === asserts : asserts === 0) context.report({ node, message });
        },
      };
    },
  };
}

const factory = {
  rules: {
    "test-asserts": testAssertionRule(false, "This test makes no assertion, so it cannot fail. Assert on what the code returns (expect(...), or a helper named expect*/assert*)."),
    "test-asserts-strongly": testAssertionRule(true, "This test's only assertions are toBeTruthy/toBeDefined, which pass for almost any value. Assert on the actual value (toBe, toEqual, toMatchObject, a status code)."),
  },
};

const readsSource = "A test checks behaviour, not source text: do not read application files in a test. Call the code or the route and assert on what it returns.";

export default tseslint.config(
  { ignores: ["**/dist/**", "**/node_modules/**"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  { languageOptions: { globals: { ...globals.node, ...globals.browser } } },
  {
    files: ["**/*.test.ts", "**/*.test.tsx", "**/__tests__/**/*.ts"],
    plugins: { factory },
    rules: {
      "factory/test-asserts": "error",
      "factory/test-asserts-strongly": "warn",
      "no-restricted-syntax": [
        "error",
        { selector: "CallExpression[callee.name=/^(readFileSync|readFile)$/]", message: readsSource },
        { selector: "CallExpression[callee.property.name=/^(readFileSync|readFile)$/]", message: readsSource },
        { selector: "Literal[value=/flags\\.json/]", message: "A test checks behaviour, not config: the release step records flags, so do not assert on flags.json." },
        { selector: "MemberExpression[property.name='only'][object.name=/^(it|test|describe)$/]", message: ".only silently skips every other test: remove it." },
      ],
    },
  },
);
