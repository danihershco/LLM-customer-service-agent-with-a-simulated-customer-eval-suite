"""Run every scenario with a simulated customer and score the agent.

    python -m evals.run --version v1
"""
import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import anthropic

from agent.agent import Agent
from agent.data import fresh_db
from evals.scenarios import ALL, HARD, SCENARIOS

USER_MODEL = os.environ.get("USER_MODEL", "claude-sonnet-5-5")
STOP = "###STOP###"
MAX_TURNS = 12

USER_SYSTEM = """You are simulating a customer chatting with a luxury retailer's support assistant.
Follow your instructions exactly. Write short, natural messages, one at a time, like a real shopper.
Only share details (order number, email, condition, etc.) when asked or when naturally relevant.
Never invent order details beyond your instructions.
When your request is resolved, clearly refused and you have accepted it, or you've been handed to a person,
reply with your final short message followed by {stop} on its own line.

Your instructions:
{instructions}"""

client = anthropic.Anthropic()
USAGE = {"user_in": 0, "user_out": 0, "agent_in": 0, "agent_out": 0}


def simulate_user(instructions, transcript, attempts=3):
    # The simulator occasionally returns no text; retry, then treat it as the customer leaving.
    for _ in range(attempts):
        text = _simulate_user_once(instructions, transcript)
        if text and "<invoke" not in text and "</invoke>" not in text:
            return text
    return STOP


def _simulate_user_once(instructions, transcript):
    # From the simulated customer's view, the agent's messages are the "user" turns.
    msgs = [{"role": "user", "content": "(The chat has opened. Write your first message to the assistant.)"}]
    for turn in transcript:
        if turn["role"] == "customer":
            msgs.append({"role": "assistant", "content": turn["text"]})
        else:
            msgs.append({"role": "user", "content": turn["text"]})
    resp = client.messages.create(model=USER_MODEL, max_tokens=300,
                                  system=USER_SYSTEM.format(stop=STOP, instructions=instructions),
                                  messages=msgs)
    USAGE["user_in"] += resp.usage.input_tokens
    USAGE["user_out"] += resp.usage.output_tokens
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def grade(sc, db):
    got_returns = sorted(json.dumps({k: r[k] for k in ("order_id", "item_ids", "refund_method")}, sort_keys=True)
                         for r in db["returns"])
    exp_returns = sorted(json.dumps(r, sort_keys=True) for r in sc["returns"])
    got_ex = sorted(json.dumps(e, sort_keys=True) for e in db["exchanges"])
    exp_ex = sorted(json.dumps(e, sort_keys=True) for e in sc["exchanges"])
    escalated = len(db["escalations"]) > 0
    reasons = []
    if got_returns != exp_returns:
        reasons.append(f"returns: expected {sc['returns']}, got {db['returns']}")
    if got_ex != exp_ex:
        reasons.append(f"exchanges: expected {sc['exchanges']}, got {db['exchanges']}")
    if escalated != sc["escalate"]:
        reasons.append(f"escalation: expected {sc['escalate']}, got {escalated}")
    return not reasons, reasons


def run_scenario(sc, version):
    db = fresh_db()
    agent = Agent(db, version=version)
    transcript = []
    for _ in range(MAX_TURNS):
        user_text = simulate_user(sc["user"], transcript)
        done = STOP in user_text
        user_text = user_text.replace(STOP, "").strip()
        if user_text:
            transcript.append({"role": "customer", "text": user_text})
        if done and not user_text:
            break
        reply = agent.reply(user_text).strip() or "(The assistant sent an empty message.)"
        transcript.append({"role": "agent", "text": reply})
        if done:  # the customer's last message still reaches the agent, so it can act on it
            break
    USAGE["agent_in"] += agent.usage["in"]
    USAGE["agent_out"] += agent.usage["out"]
    passed, reasons = grade(sc, db)
    return {"id": sc["id"], "tests": sc["tests"], "passed": passed, "reasons": reasons,
            "transcript": transcript, "tool_calls": agent.trace}


def safe_run(sc, version):
    try:
        return run_scenario(sc, version)
    except Exception as e:  # a crash counts as a failure, not a stopped run
        return {"id": sc["id"], "tests": sc["tests"], "passed": False,
                "reasons": [f"error: {e}"], "transcript": [], "tool_calls": []}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="v1")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--trials", type=int, default=1)
    ap.add_argument("--set", choices=["core", "hard", "all"], default="all")
    args = ap.parse_args()
    pool = {"core": SCENARIOS, "hard": HARD, "all": ALL}[args.set]
    scs = [s for s in pool if not args.only or s["id"] in args.only] * args.trials
    with ThreadPoolExecutor(args.workers) as ex:
        results = list(ex.map(lambda s: safe_run(s, args.version), scs))
    n_pass = sum(r["passed"] for r in results)
    out = Path("results") / f"{args.version}_{args.set}_x{args.trials}.json"
    out.write_text(json.dumps({"version": args.version, "trials": args.trials, "passed": n_pass,
                               "total": len(results), "results": results}, indent=2, default=str))
    by_id = {}
    for r in results:
        by_id.setdefault(r["id"], []).append(r)
    all_pass = 0
    for sid, rs in by_id.items():
        k = sum(r["passed"] for r in rs)
        all_pass += k == len(rs)
        why = "; ".join(sorted({x for r in rs for x in r["reasons"]}))[:160]
        print(f"{k}/{len(rs)}  {sid:28} {why}")
    print(f"\n{args.version}: {n_pass}/{len(results)} conversations passed ({100 * n_pass / len(results):.0f}%); "
          f"{all_pass}/{len(by_id)} scenarios passed every trial  -> {out}")
    print("tokens:", USAGE)


if __name__ == "__main__":
    sys.exit(main())
