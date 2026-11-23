"""Offline sample data, used only when NEWS_MOCK=1 / LLM_MOCK=1 (tests and demos)."""
import json
import time

H = 3600

_SAMPLE = {
    "tech": [
        ("Sample: Chipmaker unveils new AI accelerator for data centres", ["Outlet A", "Outlet B", "Outlet C"]),
        ("Sample: Government drafts rules for AI-generated content labels", ["Outlet A", "Outlet D"]),
        ("Sample: Startup raises funding to build Indian-language AI models", ["Outlet B"]),
        ("Sample: Smartphone maker opens new factory near Chennai", ["Outlet C", "Outlet E"]),
        ("Sample: Major cloud outage disrupts apps for several hours", ["Outlet A", "Outlet B", "Outlet E", "Outlet F"]),
        ("Sample: Open-source model tops coding benchmark", ["Outlet F"]),
    ],
    "india": [
        ("Sample: Parliament winter session opens with debate on new bill", ["Outlet A", "Outlet B", "Outlet C"]),
        ("Sample: State election results announced, ruling party retains power", ["Outlet A", "Outlet D", "Outlet E"]),
        ("Sample: Central bank keeps repo rate unchanged", ["Outlet B", "Outlet C"]),
        ("Sample: New highway project approved by cabinet", ["Outlet D"]),
        ("Sample: Opposition alliance announces seat-sharing deal", ["Outlet E", "Outlet F"]),
    ],
    "world": [
        ("Sample: Leaders meet at summit to discuss trade tariffs", ["Outlet A", "Outlet B", "Outlet C", "Outlet D"]),
        ("Sample: Ceasefire talks resume after weeks of fighting", ["Outlet A", "Outlet E"]),
        ("Sample: New sanctions announced on oil exports", ["Outlet B", "Outlet F"]),
        ("Sample: Snap election called after coalition collapses", ["Outlet C"]),
        ("Sample: UN climate talks end with funding pledge", ["Outlet D", "Outlet E"]),
    ],
    "security": [
        ("Sample: Security forces foil attack plot, several arrested", ["Outlet A", "Outlet B", "Outlet C"]),
        ("Sample: Blast near market injures dozens, investigation launched", ["Outlet A", "Outlet D", "Outlet E"]),
        ("Sample: Militant group claims responsibility for border ambush", ["Outlet B"]),
        ("Sample: Counter-terror agency files chargesheet in 2025 case", ["Outlet C", "Outlet F"]),
        ("Sample: Airports on high alert after intelligence warning", ["Outlet E"]),
    ],
}


def mock_items(category: str) -> list[dict]:
    now = time.time()
    items = []
    for i, (title, outlets) in enumerate(_SAMPLE[category]):
        for j, o in enumerate(outlets):
            items.append({
                "title": title,
                "source": o, "url": f"https://example.com/{category}/{i}/{j}",
                "published": now - (i * 2 + j) * H,
                "summary": f"Sample summary for testing: {title}. Further details reported by {o}.",
            })
    return items


def mock_leads(story: dict) -> list[dict]:
    base = story["published"]
    words = story["title"].replace("Sample: ", "")
    return [
        {"title": f"Earlier: first signs of the issue behind '{words[:40]}'", "source": "Outlet A",
         "url": "https://example.com/lead/1", "published": base - 20 * 24 * H, "summary": ""},
        {"title": f"Earlier: officials respond as pressure builds on '{words[:40]}'", "source": "Outlet B",
         "url": "https://example.com/lead/2", "published": base - 9 * 24 * H, "summary": ""},
        {"title": f"Earlier: key decision taken days before '{words[:40]}'", "source": "Outlet C",
         "url": "https://example.com/lead/3", "published": base - 2 * 24 * H, "summary": ""},
    ]


def mock_llm_answer(model: str) -> str:
    return json.dumps({
        "headline": "Sample decoded story",
        "hook": "Imagine waking up to find the rules changed overnight. This is a sample, generated offline.",
        "core_idea": "Sample core idea: one decision upstream ripples down to ordinary people.",
        "what_changed": "Sample: before, X was true; now, Y is true.",
        "why": "Sample: pressure had been building for weeks (see backstory).",
        "how": "Sample: the decision was announced and takes effect in stages.",
        "when": "Sample: announced today; effects over the coming months.",
        "who_affected": [{"group": "Sample group A", "impact": "pays less"},
                         {"group": "Sample group B", "impact": "earns less"}],
        "backstory": [{"date": "3 weeks ago", "event": "Sample: first warning signs"},
                      {"date": "9 days ago", "event": "Sample: pressure builds"}],
        "narrative": ["Sample paragraph one.", "Sample paragraph two.", "Sample paragraph three."],
        "watch_next": "Sample: what to watch next.",
        "confidence_note": "",
        "_model": model,
    })
