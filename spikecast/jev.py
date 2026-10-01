"""Jev (TypeSafe AI): a decision model that answers typed questions.

Jev does not write text. It is given a piece of state and a question with a fixed list of
options, and returns one option with a probability for every option. Reached through
OpenRouter; the key stays server-side.
"""

from dataclasses import dataclass, field

import httpx

from spikecast import env

MODEL = "~typesafe/jev-latest"
URL = "https://openrouter.ai/api/v1/systemone"


@dataclass
class Answer:
    """One answer from Jev, or the reason there is none."""

    choice: str | None
    probabilities: dict[str, float] = field(default_factory=dict)
    model: str | None = None
    cost_usd: float = 0.0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.choice is not None


class Jev:
    def __init__(self, timeout_s: float = 20.0):
        self.key = env.get("OPENROUTER_API_KEY")
        self.timeout = timeout_s
        self.calls = 0
        self.cost_usd = 0.0
        self._client = httpx.Client(timeout=timeout_s) if self.key else None

    @property
    def available(self) -> bool:
        return bool(self.key)

    def choose(self, state: str, instructions: str, options: dict[str, str]) -> Answer:
        """One typed choice question: which of `options` holds, given `state`?"""
        if self._client is None:
            return Answer(None, error="no OPENROUTER_API_KEY")
        body = {
            "model": MODEL,
            "state": state,
            "questions": {
                "q": {"type": "choice", "instructions": instructions, "criteria": options}
            },
        }
        try:
            response = self._client.post(
                URL, headers={"Authorization": f"Bearer {self.key}"}, json=body
            )
            response.raise_for_status()
            data = response.json()
            answer = data["answers"]["q"]
            choice = answer["choice"]
        except (httpx.HTTPError, KeyError, ValueError) as error:
            return Answer(None, error=f"Jev unavailable: {type(error).__name__}")
        if choice not in options:
            return Answer(None, error=f"Jev returned an option that was not offered: {choice}")
        cost = float(data.get("usage", {}).get("cost", 0.0) or 0.0)
        self.calls += 1
        self.cost_usd += cost
        return Answer(
            choice=choice,
            probabilities={k: float(v) for k, v in answer.get("probabilities", {}).items()},
            model=data.get("model"),
            cost_usd=cost,
        )
