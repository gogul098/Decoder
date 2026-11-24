"""Turn a story + its previous news leads into the decoded narrative."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator

SYSTEM = """You are the lead writer of a news-explainer app for curious young readers in India.
Readers say normal news is boring and lacks context: it tells them THAT something happened, never WHY.
Your job: turn the headlines below into a gripping, accurate, plain-English story.

Rules:
- Use ONLY facts present in the provided headlines/snippets. If a cause is not supported by them,
  say it is unclear or reported, never invent numbers, names, quotes or dates.
- Use the PREVIOUS NEWS LEADS to build the backstory and explain why this happened now.
- Be neutral on politics: attribute claims ("the government says", "critics argue").
- For violence or terrorism, be factual and calm, no graphic detail, no speculation about suspects.
- Write like a great magazine writer: open with a concrete hook, short sentences, no jargon
  (explain any term you must use in a few words).
- Analysis: separate what HAS happened (outcome so far, only from the headlines) from what MIGHT
  happen (scenarios). Scenarios are possibilities, never predictions stated as fact; give each a
  rough likelihood (likely / possible / unlikely) and a signal that would show it is happening.
- Lessons: general, reusable insights a reader can apply when they see similar news again
  (how to read such events, what tends to follow, what to check). For markets, oil or any money
  topic: explain cause and effect, but NEVER tell anyone to buy, sell or hold anything, and no
  price targets.

Return ONE JSON object with exactly these keys:
{
 "headline": "punchy rewrite, max 12 words",
 "hook": "1-2 sentence opening that makes the reader care",
 "core_idea": "the single idea to remember, 1-2 sentences",
 "what_changed": "before vs after, 1-3 sentences",
 "why": "the causes, grounded in the backstory, 2-4 sentences",
 "how": "how it happened / the mechanism, 1-3 sentences",
 "when": "timing and what happens next in time, 1-2 sentences",
 "who_affected": [{"group": "who", "impact": "how they are affected"}],
 "backstory": [{"date": "e.g. 12 Nov", "event": "what happened then"}],
 "narrative": ["3-5 short paragraphs telling the whole story in flowing prose"],
 "outcome": "what has actually resulted so far, 1-3 sentences; say clearly if it is too early to tell",
 "future": [{"scenario": "what could happen next", "likelihood": "likely | possible | unlikely", "signal": "what would show it is happening"}],
 "lessons": [{"lesson": "a reusable insight from this story", "apply": "how to use it next time you see similar news"}],
 "watch_next": "one thing to watch for next",
 "confidence_note": "mention anything unclear or disputed, or empty string"
}"""


class Affected(BaseModel):
    group: str
    impact: str = ""


class Beat(BaseModel):
    date: str = ""
    event: str


class Scenario(BaseModel):
    scenario: str
    likelihood: str = "possible"
    signal: str = ""

    @field_validator("likelihood", mode="before")
    @classmethod
    def _lk(cls, v):
        v = str(v or "possible").lower()
        return next((k for k in ("unlikely", "likely", "possible") if k in v), "possible")


class Lesson(BaseModel):
    lesson: str
    apply: str = ""


class Decoded(BaseModel):
    headline: str
    hook: str = ""
    core_idea: str
    what_changed: str = ""
    why: str = ""
    how: str = ""
    when: str = ""
    who_affected: list[Affected] = Field(default_factory=list)
    backstory: list[Beat] = Field(default_factory=list)
    narrative: list[str] = Field(default_factory=list)
    outcome: str = ""
    future: list[Scenario] = Field(default_factory=list)
    lessons: list[Lesson] = Field(default_factory=list)
    watch_next: str = ""
    confidence_note: str = ""

    @field_validator("narrative", mode="before")
    @classmethod
    def _paras(cls, v):
        if isinstance(v, str):
            return [p.strip() for p in v.split("\n") if p.strip()]
        return v

    @field_validator("who_affected", mode="before")
    @classmethod
    def _aff(cls, v):
        return [{"group": x} if isinstance(x, str) else x for x in (v or [])]

    @field_validator("future", mode="before")
    @classmethod
    def _fut(cls, v):
        return [{"scenario": x} if isinstance(x, str) else x for x in (v or [])]

    @field_validator("lessons", mode="before")
    @classmethod
    def _les(cls, v):
        return [{"lesson": x} if isinstance(x, str) else x for x in (v or [])]

    @field_validator("backstory", mode="before")
    @classmethod
    def _beats(cls, v):
        return [{"event": x} if isinstance(x, str) else x for x in (v or [])]


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d %b %Y")


def build_messages(story: dict, leads: list[dict]) -> list[dict]:
    lines = [f"TODAY: {_day(time.time())}", f"CATEGORY: {story.get('category', '')}",
             f"MAIN HEADLINE: {story['title']}", f"SNIPPET: {story.get('summary', '')}",
             "SAME STORY AS REPORTED BY OTHER OUTLETS:"]
    lines += [f"- {s['name']}: {s.get('title', '')}" for s in story.get("sources", [])]
    lines.append("PREVIOUS NEWS LEADS (oldest first):")
    lines += [f"- [{_day(l['published'])}] {l['title']} ({l['source']})" for l in leads] or ["- none found"]
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "\n".join(lines)}]


def validate(raw: dict) -> dict:
    return Decoded.model_validate(raw).model_dump()
