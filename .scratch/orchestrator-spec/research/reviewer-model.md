# Reviewer Agent model (issue #25)

Researched 2026-10-07. Every source below was accessed 2026-10-07.

## Recommendation

**Use `deepseek-ai/DeepSeek-V4-Pro-0813` on DeepInfra for the read-only reviewer Agent.**

- **Lineage.** It is DeepSeek's MIT-licensed 1M-context MoE, trained by a different lab than the Qwen coder. It is $1.30 input / $2.60 output per 1M tokens, and DeepInfra lists tool calling, JSON mode and `json_schema` structured output for it.
- **Cost.** It costs roughly 4x the coder per input token and 2.6x per output token. A review is a bounded read of a diff, so it should still be cents per Build Run. With 100K input and 10K output tokens, list price is about $0.156 (computed from the DeepInfra prices below). The reviewer is the only gate before full exposure, so paying for the largest DeepSeek model is justified.
- **Runner-up: `deepseek-ai/DeepSeek-V4.1-Flash`** ($0.20 / $0.60, MIT, 1M context). It lost because it has no independent evidence and no track record. It appeared in DeepInfra's catalog on 2026-09-10, less than a month ago, and has fewer active parameters. It is the obvious cheap downgrade path if the Pro review volume turns out to be costly. Its owner-reported agentic numbers are higher than Pro's, but they come from different benchmark versions, so they are not comparable.

**Caveats that matter for the decision**

1. No benchmark of open-weight models doing PR bug-finding turned up. The two code-review benchmarks found (Tenki and Factory's Review Benchmark) either exclude open-weight models or could not be read. All code-understanding evidence for the candidates is agentic-coding evidence (SWE-bench, Terminal-Bench, DeepSWE). It is owner-reported, apart from the Artificial Analysis figures for GLM-5.2 and DeepSeek V4 Pro (preview).
2. Run a smoke test before pinning. Replay a few known-buggy diffs through OpenHands + LiteLLM with this model. Check three things: tool-call round-trips, `reasoning_effort` handling, and that `usage.estimated_cost` is present on this specific model.
3. The Factory Review Benchmark (docs.factory.com/benchmarks/review-benchmark) may contain open-weight results. Its page is rendered client-side and I could not read it. Someone with a browser should check it.

## Comparison table

DeepInfra prices are $/1M tokens, taken from `https://api.deepinfra.com/models/list`. That API returns cents per token, and I converted them. Context is DeepInfra's `max_tokens`. "Tags" are DeepInfra's own capability tags for the model.

| Model (DeepInfra id) | In / Out $/M | Context | License | DeepInfra tags | Owner-reported coding/agentic numbers | Independent evidence | Qwen lineage |
|---|---|---|---|---|---|---|---|
| **deepseek-ai/DeepSeek-V4-Pro-0813** (recommended) | 1.30 / 2.60 (cached in 0.10) | 1,048,576 | MIT | tools, json, structured-output, can-disable-reasoning | Terminal-Bench 2.1 87.9; Toolathlon-Verified 74.1; DeepSWE 62.7; NL2Repo 61.5 | None found for the 0813 release. Preview "V4 Pro (max)" scored 44 on the Artificial Analysis Intelligence Index, at about $0.05 per index task | Independent (DeepSeek) |
| deepseek-ai/DeepSeek-V4.1-Flash (runner-up) | 0.20 / 0.60 (cached in 0.03) | 1,048,576 | MIT | tools, json, structured-output, can-disable-reasoning, multimodal | DeepSWE v1.1 74.2; Terminal-Bench 2.1 90.6 | None found | Independent (DeepSeek) |
| deepseek-ai/DeepSeek-V4-Flash-0731 | 0.06 / 0.18 | 1,048,576 | MIT (inferred from the V4 family; this card not read) | tools, json, structured-output | DeepInfra's description says it outperforms V4-Pro (Preview) on the benchmarks the owner lists | None found | Independent |
| zai-org/GLM-5.2 | 0.75 / 2.40 | 1,048,576 | MIT | tools, json, structured-output, reasoning | SWE-bench Pro 62.1; Terminal-Bench 2.1 81.0; DeepSWE 46.2 | Artificial Analysis Intelligence Index 51, the top open-weights score at the time (2026-06-16); about $0.46 per index task, with 43k output tokens per task | Independent (Zhipu / Z.ai) |
| moonshotai/Kimi-K3 | 2.85 / 14.25 | 1,048,576 | Kimi K3 License (modified MIT; attribution-clause terms not read) | tools, json, structured-output | Terminal-Bench 2.1 88.3; DeepSWE 67.5 | None found | Independent (Moonshot) |
| moonshotai/Kimi-K2.7-Code | 0.68 / 3.40 | 262,144 | Modified MIT (terms not read) | tools, json, structured-output | Kimi Code Bench v2 62.0; MCP Atlas 76.0 (no SWE-bench figure on the card) | None found | Independent |
| MiniMaxAI/MiniMax-M3 | 0.28 / 1.10 | 524,288 on DeepInfra (card says 1M) | "minimax-community" (terms not read) | tools, json, structured-output | SWE-bench Verified 80.5; SWE-bench Pro 59 | Artificial Analysis Intelligence Index 44, at about $0.18 per index task | Independent |
| openai/gpt-oss-120b | 0.037 / 0.17 | 131,072 | Apache 2.0 | tools, json, structured-output | SWE-bench Verified 52.6 (medium reasoning) | None found | Independent (OpenAI) |
| Qwen/Qwen3-Coder-480B-A35B-Instruct-Turbo (current coder, for reference) | 0.30 / 1.00 | 262,144 | Apache 2.0 | tools, json, structured-output | n/a | n/a | It is the coder |

Not evaluated: the other new catalog entries (Nemotron-3-Ultra, MiMo-V2.6-Pro, Step-3.7-Flash, Hy3, Ling-3.0). Every Qwen-family model was excluded, because the point is lineage independence.

## Findings with citations

### 1. Review and code-understanding quality

- **DeepSeek-V4-Pro (preview).** The model card lists SWE-bench Verified 80.6, SWE-bench Pro 55.4, Terminal Bench 2.0 67.9 and LiveCodeBench 93.5. These are owner-reported. The card also lists MIT and a 1M context. https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro
- **DeepSeek-V4-Pro-0813.** The card lists Terminal Bench 2.1 87.9, Toolathlon-Verified 74.1, DeepSWE 62.7 and NL2Repo 61.5. These are owner-reported, on newer benchmark versions than the preview card, so the two cards' numbers cannot be compared directly. https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro-0813 . DeepInfra's description says it is "the official release of DeepSeek-V4-Pro, superseding the preview version, with greatly enhanced agentic capabilities" (https://api.deepinfra.com/models/list).
- **DeepSeek-V4.1-Flash.** The card lists DeepSWE v1.1 74.2 and Terminal-Bench 2.1 90.6, owner-reported. It also lists 552B backbone parameters with 8B activated in prefill and 16B in decode. https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash . The DeepInfra catalog entry was created 2026-09-10 (https://api.deepinfra.com/models/list). That is the basis for "less than a month old" above.
- **GLM-5.2.** The card lists SWE-bench Pro 62.1, Terminal Bench 2.1 81.0 and DeepSWE 46.2. https://huggingface.co/zai-org/GLM-5.2 . Artificial Analysis (independent) says it is "the new leading open weights model on the Artificial Analysis Intelligence Index scoring 51". It put MiniMax-M3 and DeepSeek V4 Pro both at 44, and reported TerminalBench v2.1 at 78%. GLM-5.2 used 43k output tokens per task, 37k of them reasoning, at about $0.46 per task. https://artificialanalysis.ai/articles/glm-5-2-is-the-new-leading-open-weights-model-on-the-artificial-analysis-intelligence-index . A search-result summary of the same article gives DeepSeek V4 Pro (max) at about $0.05 per task. I did not confirm that figure on the page itself, so treat it as unverified. GLM-5.2 is the strongest independently measured open model, but it is much more expensive per task and token-hungry.
- **Kimi K3 and K2.7-Code.** K3: Terminal-Bench 2.1 88.3, DeepSWE 67.5 (https://huggingface.co/moonshotai/Kimi-K3). K2.7-Code reports only Kimi's own benchmarks (https://huggingface.co/moonshotai/Kimi-K2.7-Code). Owner-reported only.
- **MiniMax-M3.** SWE-bench Verified 80.5 and SWE-bench Pro 59, owner-reported. https://huggingface.co/MiniMaxAI/MiniMax-M3
- **gpt-oss-120b.** SWE-bench Verified 52.6% at medium reasoning. This is far below the others, and it is the weakest candidate. https://huggingface.co/openai/gpt-oss-120b
- **Code-review benchmarks.**
  - Tenki's benchmark (7 tools on 50 PRs with 122 real bugs, published April 2026) evaluates review products and coding agents only. No open-weight models are in it. https://tenki.cloud/benchmarks/code-reviewer.md
  - Factory's Review Benchmark says it covers 13 frontier and open-source models on 50 PRs (per a search-result snippet), but its page content could not be read. https://docs.factory.com/benchmarks/review-benchmark (unverified).
  - Net result: no primary source ranks these models specifically at PR bug-finding.
  - The benchmark numbers on all the model cards above are the model owners' own claims.
- **Tooling note.** The summaries of HF cards and web pages were produced by an automated page-reader. Release dates it returned were inconsistent with the other sources, so I cite no release dates from model cards. The only dates used are the DeepInfra catalog `create_ts` values and the Artificial Analysis article date.

### 2. Tool-calling and agentic reliability under OpenHands / LiteLLM

- **LiteLLM.** A DeepInfra model is addressed as `deepinfra/<model>` with `DEEPINFRA_API_KEY`. The LiteLLM page says nothing about function calling or cost tracking for DeepInfra. https://docs.litellm.ai/docs/providers/deepinfra
- **OpenHands.** Custom OpenAI-compatible endpoints use an `openai/<model-id>` prefix and a base URL. The docs warn that failing tool calls with a custom model may be "an issue with the model itself". They say nothing about `native_tool_calling` or DeepInfra. https://docs.openhands.dev/openhands/usage/llms/local-llms . The OpenHands LLM docs page does not discuss model recommendations either. https://docs.openhands.dev/openhands/usage/llms/openhands-llms
- **OpenHands Index.** A search result says it is a holistic coding-agent benchmark (https://benchlm.ai/md/benchmarks/openhandsindex.md, a third-party mirror). I could not read the index itself at https://index.openhands.dev, so there is no verified OpenHands-specific per-model result for any candidate (unverified).
- **DeepInfra tool calling.** Supported: single calls, parallel calls ("quality may vary"), `tool_choice` auto and none, streaming. Not supported: nested calls. Its tips include avoiding system messages and keeping temperature below 1.0. https://docs.deepinfra.com/chat/tool-calling.md . DeepInfra states "Tool call accuracy is a top priority" and cites Moonshot's K2 Vendor Verifier for Kimi K2, so there is a provider-side vendor-verification precedent, but only for Kimi (same page).
- **Reasoning round-trips (risk).**
  - DeepSeek's own API docs say that when tools are used in thinking mode, `reasoning_content` of all previous turns must be passed back. Thinking mode ignores `temperature`, `presence_penalty` and `frequency_penalty`. https://api-docs.deepseek.com/guides/thinking_mode
  - Kimi K3's card has a similar requirement, to return `reasoning_content` and `tool_calls` in multi-turn use (https://huggingface.co/moonshotai/Kimi-K3).
  - Whether OpenHands/LiteLLM preserves `reasoning_content` against DeepInfra's endpoint is unverified. DeepInfra lets reasoning be controlled with `reasoning_effort`, and lists V4-Flash-0731, V4-Pro-0813, GLM-5.2 and Kimi-K3 as reasoning-capable. https://docs.deepinfra.com/chat/reasoning.md
  - For the reviewer, pick a `reasoning_effort` setting and test it in the smoke test. The DeepInfra tags show V4-Pro-0813 as both `non-reasoning` and `can-disable-reasoning`. The reviewer is read-only, which limits the damage from tool-call quirks to a failed or retried review. The verdict stays gated on the JSON schema (see section 5).

### 3. Price and cost reporting

- **Prices.** DeepInfra's model API gives V4-Pro-0813 at 0.00013 / 0.00026 cents per token, which is $1.30 / $2.60 per 1M. V4.1-Flash is $0.20 / $0.60, GLM-5.2 is $0.75 / $2.40, Kimi-K3 is $2.85 / $14.25, and the Qwen coder Turbo is $0.30 / $1.00. https://api.deepinfra.com/models/list (queried 2026-10-07). The V4-Pro-0813 page shows $1.30 / $2.60 with cached input at $0.10, 1,048,576 context, tool calling and JSON mode. https://deepinfra.com/deepseek-ai/DeepSeek-V4-Pro-0813
- **`usage.estimated_cost`.** DeepInfra's quickstart shows a chat-completion response containing `"usage": {..., "estimated_cost": 0.0000268}`. The example uses `deepseek-ai/DeepSeek-V4-Flash-0731`, and the field appears in a general OpenAI-compatible example. https://docs.deepinfra.com/quickstart (full text via https://docs.deepinfra.com/llms-full.txt). I found no per-model statement, so the field's presence on V4-Pro-0813 is likely but unverified for that exact model. The smoke test should assert it.
- **Cost framing.** Using list price for 100K input plus 10K output tokens (my arithmetic): V4-Pro-0813 is about $0.156, V4.1-Flash about $0.026, GLM-5.2 about $0.099. Reasoning tokens are billed as output, and the Artificial Analysis token counts above suggest reasoning-heavy models spend many more output tokens, so GLM-5.2's real cost is likely higher than this arithmetic. Treat all of these as estimates.

### 4. License

- DeepSeek-V4-Pro and V4-Pro-0813: MIT, stated on the Hugging Face cards and on DeepInfra's V4-Pro-0813 page. V4.1-Flash: MIT. See the URLs in section 1 and https://deepinfra.com/deepseek-ai/DeepSeek-V4-Pro-0813 . MIT has no use restrictions relevant to an automated reviewer.
- GLM-5.2: MIT (https://huggingface.co/zai-org/GLM-5.2). gpt-oss-120b: Apache 2.0.
- Kimi K3 uses a "Kimi K3 License" described as a modified-MIT attribution clause, and K2.7-Code uses "Modified MIT". I did not read the actual license text, so threshold terms are unverified. MiniMax-M3 is "minimax-community", also unread.
- Weights are open, but DeepInfra serves them hosted, so this use is API consumption of the weights, not redistribution.

### 5. Context window and structured output

- V4-Pro-0813, V4.1-Flash, V4-Flash-0731 and GLM-5.2: 1,048,576 tokens on DeepInfra. Kimi-K2.7-Code: 262,144. Source: https://api.deepinfra.com/models/list
- DeepInfra supports `response_format` with `json_object` and `json_schema` (strict) "across many of our models". Its guidance is to prefer `json_schema` with `"strict": true` in production, and to still ask for JSON in the prompt. https://docs.deepinfra.com/chat/structured-outputs.md . V4-Pro-0813 carries the `json` and `structured-output` tags (https://api.deepinfra.com/models/list).
- Whether structured output and tool use work together in one request on this model was not verified. The reviewer should validate the verdict JSON against its schema client-side and treat a malformed verdict as "not clean" (no auto-release).

### 6. Lineage independence from Qwen

- Qwen3-Coder is Alibaba's model (the existing architecture decision records its Apache 2.0 license and Qwen team origin; `ARCHITECTURE.md`, Model serving). DeepSeek-V4, GLM, Kimi, MiniMax and gpt-oss come from different organizations (DeepSeek, Zhipu / Z.ai, Moonshot, MiniMax, OpenAI), each with its own model card above.
- Independent organizations do not guarantee independent training data or no cross-distillation. I found no primary source on shared training data or distillation between these labs and Qwen, so treat "no shared blind spots" as an assumption, not a verified fact.

## Why the others lost

- **Kimi K3:** about 2.2x the input and 5.5x the output price of V4-Pro-0813, with a custom license to read first.
- **GLM-5.2:** best independent number, but a pricier, more verbose reasoner (about $0.46 per index task). It is a reasonable alternative if V4-Pro underperforms in the smoke test.
- **MiniMax-M3:** strong owner numbers, but a community license and a context mismatch between DeepInfra (524K) and the card (1M).
- **Kimi K2.7-Code:** coding-focused, but reports no SWE-bench figures on its card and has a smaller context.
- **gpt-oss-120b:** cheapest, but SWE-bench Verified 52.6 is too weak for the only gate before full exposure.
- **V4-Flash-0731 and V4.1-Flash:** cheapest credible options. Held back by lack of independent evidence and track record, and Flash-class models are smaller; see the runner-up note above.

## Unverified items

- No benchmark of open-weight models on PR code review; Factory's Review Benchmark page unreadable.
- OpenHands Index per-model results unreadable.
- `usage.estimated_cost` on V4-Pro-0813 specifically (documented only in a general example using V4-Flash-0731).
- OpenHands/LiteLLM handling of `reasoning_content` and tool calls against DeepSeek V4 via DeepInfra.
- Structured output combined with tool calls on V4-Pro-0813.
- Kimi, MiniMax license text; V4-Flash-0731 license (inferred).
- Artificial Analysis cost-per-task for DeepSeek V4 Pro (search-summary only), and the 744B versus 753B GLM-5.2 parameter count (AA versus HF summary).
- Shared training data or distillation between the candidate labs and Qwen.
