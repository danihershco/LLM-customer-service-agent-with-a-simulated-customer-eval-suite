"""The Maison Verre customer service agent: a Claude tool-use loop."""
import json
import os
from pathlib import Path

import anthropic

from .tools import TOOL_SCHEMAS, Store

HERE = Path(__file__).parent
AGENT_MODEL = os.environ.get("AGENT_MODEL", "claude-haiku-5-5")
PROMPT_VERSION = os.environ.get("PROMPT_VERSION", "v1")


def system_prompt(version=PROMPT_VERSION):
    prompt = (HERE / "prompts" / f"{version}.md").read_text()
    versioned = HERE / f"policy_{version}.md"
    policy = (versioned if versioned.exists() else HERE / "policy.md").read_text()
    return prompt.replace("{{POLICY}}", policy)


class Agent:
    def __init__(self, db, version=PROMPT_VERSION, model=AGENT_MODEL, client=None):
        self.store = Store(db)
        self.system = system_prompt(version)
        self.model = model
        self.client = client or anthropic.Anthropic()
        self.messages = []
        self.trace = []  # tool calls, for transcripts
        self.usage = {"in": 0, "out": 0}

    def reply(self, user_text, max_steps=10):
        self.messages.append({"role": "user", "content": user_text})
        for _ in range(max_steps):
            resp = self.client.messages.create(
                model=self.model, max_tokens=1024, system=self.system,
                tools=TOOL_SCHEMAS, messages=self.messages)
            self.usage["in"] += resp.usage.input_tokens
            self.usage["out"] += resp.usage.output_tokens
            self.messages.append({"role": "assistant", "content": resp.content})
            tool_uses = [b for b in resp.content if b.type == "tool_use"]
            if not tool_uses:
                return "".join(b.text for b in resp.content if b.type == "text")
            results = []
            for tu in tool_uses:
                out = self.store.call(tu.name, tu.input)
                self.trace.append({"tool": tu.name, "input": tu.input, "output": out})
                results.append({"type": "tool_result", "tool_use_id": tu.id,
                                "content": json.dumps(out)})
            self.messages.append({"role": "user", "content": results})
        return "Sorry, I'm having trouble completing that. Let me connect you with our client care team."
