# Engram scientific benchmark preregistration

Status: **pilot protocol, frozen before the expanded run**  
Protocol: `benchmarks/scientific/protocol.json`

## Research question

Does Engram improve agent performance generally and with statistically defensible
evidence under controlled, paired evaluation?

This is **a reproducible experimental matrix that will be expanded until it reaches
statistically solid evidence**. The five-task internal suite is an instrumentation
pilot. It cannot establish generalization by itself.

## Experimental unit and controls

One pair uses the same model, reasoning effort, task, frozen repository snapshot,
shared instructions, non-Engram tools, timeout, and repetition number. The treatment
is the Engram recall directive and its read-only tool. Condition order is randomized
inside every pair with the fixed seed in `protocol.json`; pair order is randomized too.

The common model setting is `reasoning_effort=high`, supported by all five included
models. A later ceiling study may use each model's maximum setting, but those results
must remain separate from the controlled common-effort comparison.

The pilot has five repetitions and the confirmatory target has ten. Repetitions do
not replace task diversity: confirmatory evidence must include the pinned official
external suites listed in the protocol.

## Outcomes

The primary outcome is paired task completion, determined by an objective verifier,
official benchmark grader, or executable tests. The primary test is a two-sided exact
McNemar test at alpha 0.05. The report also gives the paired effect and a deterministic
bootstrap 95% confidence interval.

Secondary outcomes are official score, token categories, API list-price equivalent,
wall time, tool calls, observable errors, and context consumption. Continuous paired
deltas use bootstrap intervals and a paired sign-flip randomization test.

Codex subscription runs do not expose the actual invoice charge for each run. The
runner therefore records `actual_billed_usd=null` and calculates
`api_equivalent_usd` from the versioned price manifest. It never presents that
estimate as a charged amount.

## Judging and debate

Objective graders are primary. When an official benchmark requires an LLM grader,
its result is reported with that label and cannot override executable evidence.

Model debate is a separate secondary diagnostic:

1. collect independent answers without model names;
2. replace identities with randomized labels;
3. request cross-critiques under the same written rubric;
4. aggregate multiple verdicts and record disagreement;
5. preserve the objective score even when the jury disagrees.

Debate results are not merged into the primary endpoint.

## Exclusions and stopping

Infrastructure failures are retained and reported. A run may be excluded only when
the failure is demonstrably outside the evaluated condition and affects pair validity;
the exclusion reason must be written before rerunning both members of that pair.

There is no optional stopping based on a favorable p-value. The pilot ends at five
repetitions. The confirmatory internal matrix ends at ten. Every official suite must
use a pinned version, a fixed task sample, and its declared completion rule before its
first scored run.

GPT-5.3 Codex Spark was excluded before data collection because preflight reported
that it was unavailable to Codex with this ChatGPT account. Its absence is not an
Engram failure.

## Claim boundary

A pilot can show that the measurement system works and estimate effect variance. A
production claim requires the target sample, confidence interval, primary test, and
external benchmark evidence. A public multi-tenant launch also requires separate
security, reliability, recovery, and load gates; benchmark success alone is not a
production authorization.
