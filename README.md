# Maison Verre Client Care Agent

An LLM customer service agent for a fictional luxury fashion retailer, plus an evaluation suite that tests it against 30 simulated customers. Built by Dani Hershco, November 2026.

The brand and its customers are fictional. The returns policy is modeled on a real luxury retailer's public policy, simplified.

## What the agent does

The agent handles returns and exchanges over chat. It is Claude (`claude-haiku-5-5`) with:

- **Instructions** (`agent/prompts/v1.md` to `v4.md`): who it is and how to behave.
- **Knowledge** (`agent/policy.md`): return windows, final sale rules, condition rules, refunds, exchanges, gifts, when to escalate.
- **Five tools** (`agent/tools.py`): `find_order` (order number and email must match), `check_stock`, `create_return`, `create_exchange`, `escalate_to_human`.

Like a real order system, the tools don't enforce the policy. Deciding what's allowed is the agent's job, and that's what the tests measure.

## How it's tested

Each test case (`evals/scenarios.py`) has two parts:

1. **A customer script**, played by a second model (`claude-sonnet-5-5`). Example: "You're Hana. You want to return sneakers. You threw out the box, but only say so if asked."
2. **The correct outcome**: exactly which returns and exchanges should exist at the end, and whether the agent should hand off to a person.

The grader ignores how the chat reads and checks the store's records at the end. This follows the approach of Sierra's τ-bench: simulated users, success judged by final state.

There are 30 scenarios: 20 core cases (happy paths, final sale, worn items, gift recipients, damaged items, wrong email, requests for a person) and 10 hard cases (exact day 14, 15 and 31 edges, mixed return windows in one order, a customer who switches from a return to an exchange, a fake "store manager" override, two orders in one chat, an ambiguous item). Every scenario runs 3 times, because the same agent can handle the same customer differently.

## Results

| Version | What changed | Conversations passed | Scenarios passed every run |
|---|---|---|---|
| v1 | Baseline: role, tone, policy | 86/90 (96%) | 26/30 |
| v2 | Escalate only when asked; state only facts from tools; cancelled-card refunds added to policy; tools return the email they used | 87/90 (97%) | 27/30 |
| v3 | Confirm condition and the plan before creating anything; exchange tool returns shipping instructions | 83/90 (92%) | 24/30 |
| v4 | Ask about condition once, then trust and remind; decline only on disqualifying answers | 89/90 (99%) | 29/30 |

### What each round taught

- **v1:** The agent offered human reviews nobody asked for (extra tickets, lower containment), made up which email a return label went to, and left a customer with a cancelled card unresolved.
- **v2:** Fixing hallucinations exposed a knowledge gap: asked how to ship an exchange back, the agent correctly said it didn't know, then had to escalate. It also created a shoe return before asking about the box, and couldn't undo it.
- **v3:** Confirming before acting fixed the change-of-mind case, but the agent became an interrogator about packaging. Customers left to "go check" and never finished. This is the safety vs. friction tradeoff.
- **v4:** One condition question, then trust and remind (returns are inspected at the warehouse anyway). Friction gone, safety kept.

The fixes fell into three kinds: instructions (escalation rules, confirm-then-act), knowledge (cancelled cards), and tools (returning the email used, shipping instructions for exchanges).

## Honest limits

- The store and customers are simulated; a simulated customer is more cooperative than a real one.
- 3 runs per scenario is a small sample. Treat one-point differences between versions as noise.
- The grader checks end state only. It can't see tone, or the agent offering a review unprompted when no handoff happened (seen once in v4). An LLM-graded rubric would catch those.
- Two bugs in the test harness were found and fixed during the project (empty simulator replies, and the customer's last message not reaching the agent). v1 and v2 results combine runs before and after one tool change; see `results/`.
- The single v4 failure looks like a simulator dropout (the simulated customer stopped after the first reply); it's counted as a failure anyway.

## Run it

```bash
pip install anthropic
export ANTHROPIC_API_KEY=...
python chat.py                                          # chat with the agent
python -m evals.run --version v4 --set all --trials 3   # run the evals
```

Results land in `results/`, including every transcript and tool call.
