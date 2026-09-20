# Scientific benchmark

Engram's scientific evaluation asks whether memory improves agent completion,
quality, cost, and efficiency under controlled paired conditions. The protocol
is designed to produce evidence that can be rerun and challenged; it does not
turn one favorable demo into a general claim.

## Controlled matrix

The committed pilot contains five accessible models:

- `gpt-5.5`
- `gpt-5.6-luna`
- `gpt-5.6-terra`
- `gpt-5.6-sol`
- `gpt-6-astra`

Every model uses `reasoning_effort=high`. Each task and repetition produces an
Engram OFF/ON pair. Model, task, shared instructions, frozen repository snapshot,
non-Engram tools, and timeout are held constant. The Engram recall directive and
read-only tool form the treatment. Order inside each pair is randomized.
The five-repetition pilot produces 125 pairs and 250 executions. The locked
confirmatory target is ten repetitions after the external task sets are pinned.

Codex Spark is absent by design. Preflight reported that it was unavailable to
Codex with this ChatGPT account, and it was excluded before scored collection.

## Completed internal pilot

The preregistered five-repetition pilot completed all 250 executions as 125
intact OFF/ON pairs with no infrastructure failure included in analysis.
Completion rose from 110/125 without Engram to 125/125 with Engram, a paired
difference of +12.0 percentage points (bootstrap 95% CI +6.4 to +17.6; exact
McNemar p=0.000061). Engram also reduced aggregate uncached input by 17.8%,
output by 20.6%, wall time by 14.6%, and tool calls by 24.5%.

The completion difference was concentrated in one of the five internal tasks,
so this remains an instrumentation pilot rather than evidence of broad
generalization. The full sanitized result, per-model completion, statistical
tests, and limitations are in
[`benchmarks/scientific/latest-pilot.md`](../benchmarks/scientific/latest-pilot.md).

## Reproducible commands

Create the full pilot plan without calling a model:

```powershell
uv run engram-science plan
```

Run a checkpointed pilot. Each complete OFF/ON pair is flushed atomically;
running the same command again skips completed pairs and refuses incomplete or
failed persisted results:

```powershell
uv run engram-science run --timeout 600
uv run engram-science analyze
```

The first scored execution freezes a source snapshot and study digest in the
output directory. Resume refuses changed code, tasks, or protocol instead of
silently mixing experimental conditions.

Use `--max-pairs 1` for an end-to-end smoke test without splitting an ON/OFF
pair. `--model` and `--task-id` select a diagnostic subset without altering the
committed protocol. Use `--repetitions 10` only for the preregistered
confirmatory matrix.

After independent answers exist, run the separate blind jury:

```powershell
uv run engram-debate `
  --input artifacts\scientific\five-model-smoke\results.jsonl `
  --task-id state-storage `
  --condition engram `
  --output-dir artifacts\scientific\five-model-debate
```

The jury rotates answer order, hides model identity, applies one rubric, rejects
judges that use tools, reports disagreement, and reveals identities only after
aggregation. Its result remains secondary to objective grading.

The machine-readable inputs live in
[`benchmarks/scientific/protocol.json`](../benchmarks/scientific/protocol.json)
and [`benchmarks/scientific/pricing.json`](../benchmarks/scientific/pricing.json).
The written decision rules are in
[`benchmarks/scientific/preregistration.md`](../benchmarks/scientific/preregistration.md).

## Statistics and claim policy

The primary endpoint is paired completion. The analyzer reports the Engram ON
minus OFF effect, a deterministic bootstrap 95% confidence interval, and the
two-sided exact McNemar p-value. Secondary paired metrics use bootstrap
intervals and a sign-flip randomization test.

The primary grader must be objective: executable tests, a deterministic state
verifier, or the official benchmark's objective scoring function. LLM graders
remain labeled secondary diagnostics and cannot override objective evidence.

The internal repository questions validate the instrument and estimate
variance. Generalization requires external suites. The protocol names
[LongMemEval-V2](https://github.com/xiaowu0162/LongMemEval-V2) as the first
memory-specific benchmark and also reserves Terminal-Bench, SWE-bench Verified,
and BFCL V4 for execution, software-engineering, and tool-use coverage.

## LongMemEval-V2 adapter

The bridge implements the official `Memory.insert()` and `Memory.query()`
contract. It serializes public trajectory evidence into bounded local chunks,
indexes them through Engram, and retrieves solely from the question text. It
does not receive question IDs, gold answers, grader configuration, or other
private benchmark metadata.

The wrapper refuses a LongMemEval-V2 checkout that does not match the pinned
commit in the protocol. The official dataset revision totals about 7.12 GB.
The text-first pilot fetches about 1.20 GB and deliberately excludes 5.92 GB of
trajectory screenshot archives; that run must be labeled text-first and cannot
be presented as the full multimodal configuration.

```powershell
uv run python scripts/fetch_longmemeval_text.py `
  --output-dir artifacts\official\LongMemEval-V2\data\longmemeval-v2
uv run python artifacts\official\LongMemEval-V2\data\validate_data.py `
  --data-root artifacts\official\LongMemEval-V2\data\longmemeval-v2 `
  --tier small `
  --no-check-screenshots
```

After the deliberate data step, run a small-domain smoke test from this repository:

```powershell
uv sync --extra longmemeval
$env:LONGMEMEVAL_V2_ROOT = "$PWD\artifacts\official\LongMemEval-V2"
uv run python benchmarks/adapters/run_longmemeval_v2.py `
  --method engram_runtime `
  --data-root "$env:LONGMEMEVAL_V2_ROOT\data\longmemeval-v2" `
  --domain web `
  --tier small `
  --limit 1 `
  --output-dir artifacts\longmemeval\engram-web-smoke `
  --reader-model gpt-5.6-luna `
  --reader-base-url https://api.openai.com/v1 `
  --reader-enable-thinking `
  --reader-max-concurrent-requests 1 `
  --prompt-build-max-workers 1
```

The official data download includes screenshot archives and can be large, so it
is a deliberate setup step rather than an implicit side effect of the runner.

The pinned full dataset has now passed the official small-tier validator with
screenshots enabled. The frozen OFF/ON execution manifest, question counts,
local hardware requirements, and paid-evaluator cost gate are recorded in
[`benchmarks/scientific/longmemeval-v2-preflight.md`](../benchmarks/scientific/longmemeval-v2-preflight.md)
and
[`benchmarks/scientific/longmemeval-v2-plan.json`](../benchmarks/scientific/longmemeval-v2-plan.json).

## Cost semantics

The runner records reported input, cached input, uncached input, output, and
reasoning tokens. `api_equivalent_usd` applies the versioned standard API list
prices from official OpenAI documentation. `actual_billed_usd` stays `null`
for Codex subscription runs because Codex does not expose a per-run invoice.

Likewise, `model_invocation_proxy=1` means one visible `codex exec` session. It
does not pretend to count provider-internal requests. Unobservable retry counts
remain `null`; observable errors are retained.
