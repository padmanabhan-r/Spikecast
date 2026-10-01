"""Claude, the writer: one event in, one sentence out.

The writer sees a single event, the glossary entries for the cells in it, and the last few
lines. It never sees the fly's controls, because there are none here to see: this module
imports nothing from the simulation.
"""

import json

import anthropic

from spikecast import env
from spikecast.narrate.config import settings
from spikecast.narrate.events import Event

PERSONAS = {
    "nature_doc": "a calm, precise nature-documentary narrator who is quietly amazed",
    "sportscaster": "a quick, vivid sports commentator calling the action as it happens",
    "neuroscientist": "a working neuroscientist explaining to a curious friend",
}

SYSTEM = """You are the commentator for Spikecast: a simulation of a whole fruit-fly brain, \
wired as it was mapped in a real fly, with a simple body in a small world. Viewers see the \
brain lighting up and the fly moving. Most are not scientists.

You are {persona}.

In this experiment a fixed rule steers the fly: in a smell, if the brain's outputs labelled \
approach do not out-fire the outputs labelled avoid, the fly turns back. Nothing tells the \
fly which smell is which.

You will be given one event that was just measured in the simulation. Write ONE sentence \
about it for the viewer.

Rules, all of them strict:
- At most {max_words} words. Present tense. Plain English. One sentence.
- Say only what the event's facts and the glossary support. If it is not there, it did not happen.
- You may name a cell type only if it is in the glossary you are given, and only by the name \
or nickname given there.
- You may state a number only if it is in the event's facts. Round it if you like. Most \
lines are better with one number or none.
- Describe what cells and synapses do, not what the fly thinks, feels or wants.
- Lead with what a viewer can see (the fly walks on, turns back, takes off), then the reason.
- Call the smells the pink smell and the amber smell.
- A fact called "note" is background for you, not something to say. Never mention the \
stimulus model, the simulation's internals, or that something is modelled. Where a note says \
our model drives or adds something, simply do not present that thing as a discovery.
- Say "times a second" rather than Hz.
- Do not repeat the wording of the previous lines; carry the story forward from them.
- No quotation marks, no emoji, no stage directions, no preamble, no word counts, no working. \
Output the sentence only."""


class Writer:
    """Writes lines with the Anthropic SDK: first-party when ANTHROPIC_API_KEY is set,
    otherwise the same SDK pointed at OpenRouter's Anthropic-compatible endpoint."""

    def __init__(self, mode: str = "broadcast", enabled: bool = True):
        cfg = settings()
        self.cfg = cfg["writer"]
        self.max_words = cfg["max_words"]
        self.persona = PERSONAS[cfg["persona"]]
        self.model = self.cfg["live_model" if mode == "live" else "broadcast_model"]
        self.client: anthropic.Anthropic | None = None
        self.model_id = self.model
        self.via = None
        if not enabled:
            return
        if env.get("ANTHROPIC_API_KEY") or env.get("ANTHROPIC_AUTH_TOKEN"):
            self.client, self.via = anthropic.Anthropic(), "anthropic"
        elif env.get("OPENROUTER_API_KEY"):
            self.client = anthropic.Anthropic(
                base_url="https://openrouter.ai/api",
                auth_token=env.get("OPENROUTER_API_KEY"),
                api_key=None,
            )
            self.model_id = self.cfg["openrouter_models"][self.model]
            self.via = "openrouter"
        self.calls = 0

    @property
    def available(self) -> bool:
        return self.client is not None

    def write(
        self,
        event: Event,
        glossary: list[dict],
        previous: list[str],
        rejected: tuple[str, str] | None = None,
    ) -> tuple[str | None, str | None]:
        """Returns (line, None) or (None, why there is no line)."""
        if self.client is None:
            return None, "no writer key (ANTHROPIC_API_KEY or OPENROUTER_API_KEY)"
        request = {
            "event": event.payload(),
            "glossary": glossary,
            "previous_lines": previous[-3:],
        }
        content = json.dumps(request, indent=1)
        if rejected:
            content += (
                f'\n\nYour last attempt was rejected: "{rejected[0]}"\nReason: {rejected[1]}\n'
                "Write a different sentence that avoids that problem."
            )
        options: dict = {}
        if "haiku" not in self.model:
            # Opus 5.5 always thinks; effort is the only control, and this is a small task.
            options["output_config"] = {"effort": self.cfg.get("effort", "low")}
        try:
            response = self.client.messages.create(
                model=self.model_id,
                max_tokens=2000,
                system=SYSTEM.format(persona=self.persona, max_words=self.max_words),
                messages=[{"role": "user", "content": content}],
                **options,
            )
        except anthropic.RateLimitError:
            return None, "writer rate limited"
        except anthropic.APIStatusError as error:
            return None, f"writer error {error.status_code}"
        except anthropic.APIConnectionError:
            return None, "writer unreachable"
        self.calls += 1
        if response.stop_reason == "refusal":
            return None, "writer declined"
        text = "\n".join(b.text for b in response.content if b.type == "text").strip()
        # Asked to fix a rejected line, the model sometimes shows its working first. The
        # sentence is the last line it wrote.
        text = text.splitlines()[-1].strip().strip('"“”').strip() if text else ""
        return (text, None) if text else (None, "writer returned nothing")
