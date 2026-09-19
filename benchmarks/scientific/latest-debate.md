# Blind five-model jury smoke test

Run date: 2026-09-19  
Source: Engram ON answers from the five-model `state-storage` smoke test  
Reasoning effort: `high`  
Judges: GPT-5.5, GPT-5.6 Luna, Terra, Sol, and GPT-6 Astra

The five independent answers were assigned randomized labels. Every judge saw
the answers in a different rotated order, received the same rubric, and did not
see model identities. All five judges returned schema-valid verdicts and made
zero tool calls.

| Model revealed after judging | Mean jury score | First-place votes | Objective score |
| --- | ---: | ---: | ---: |
| gpt-6-astra | 99.20 | 5 | 1.000 |
| gpt-5.5 | 96.80 | 0 | 1.000 |
| gpt-5.6-sol | 96.20 | 0 | 1.000 |
| gpt-5.6-terra | 95.40 | 0 | 1.000 |
| gpt-5.6-luna | 94.40 | 0 | 1.000 |

Jury disagreement was 0.0: all five judges selected the same blinded response,
which was revealed afterward as GPT-6 Astra. The recurring reason was its
complete answer and clean repository-relative citations. Lower scores mostly
reflected absolute artifact paths, less portable citation formatting, or fewer
index implementation details.

All five objective scores were already perfect. The jury therefore ranks
presentation and supporting detail within correct answers; it does not show an
accuracy advantage. This is a one-task diagnostic and is not part of the
primary Engram ON/OFF endpoint.
