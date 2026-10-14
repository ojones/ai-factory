// The Starter Template's lint rules. Keep this file additive: a rule is added or tightened, never loosened,
// so the learning loop can merge such changes without review (INV-15). The Orchestrator owns this file in every
// app (a coder commit that touches it is rejected; template sync copies it in), so a rule cannot be loosened to
// make a check pass. Every rule here has cases in agents/lint-fixtures/cases.json.
import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";

const readsSource = "A test checks behaviour, not source text: do not read application files in a test. Call the code or the route and assert on what it returns.";

export default tseslint.config(
  { ignores: ["**/dist/**", "**/node_modules/**"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  { languageOptions: { globals: { ...globals.node, ...globals.browser } } },
  {
    files: ["**/*.test.ts", "**/*.test.tsx", "**/__tests__/**/*.ts"],
    rules: {
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
