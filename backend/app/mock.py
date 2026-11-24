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
    "markets": [
        ("Sample: Sensex and Nifty close higher as banks rally", ["Outlet A", "Outlet B", "Outlet C"]),
        ("Sample: Central bank holds interest rate steady", ["Outlet A", "Outlet D"]),
        ("Sample: IT stocks slip after weak US guidance", ["Outlet B", "Outlet E"]),
        ("Sample: Rupee weakens against the dollar", ["Outlet C"]),
        ("Sample: Big IPO oversubscribed on final day", ["Outlet D", "Outlet F"]),
    ],
    "oil": [
        ("Sample: Brent crude rises after OPEC+ extends output cuts", ["Outlet A", "Outlet B", "Outlet C"]),
        ("Sample: Petrol and diesel prices unchanged for another month", ["Outlet A", "Outlet D"]),
        ("Sample: India signs long-term LNG deal", ["Outlet B", "Outlet E"]),
        ("Sample: Shipping disruption pushes up freight costs for oil", ["Outlet C"]),
        ("Sample: Natural gas prices fall on mild winter forecast", ["Outlet D", "Outlet F"]),
    ],
    "security": [
        ("Sample: Security forces foil attack plot, several arrested", ["Outlet A", "Outlet B", "Outlet C"]),
        ("Sample: Blast near market injures dozens, investigation launched", ["Outlet A", "Outlet D", "Outlet E"]),
        ("Sample: Militant group claims responsibility for border ambush", ["Outlet B"]),
        ("Sample: Counter-terror agency files chargesheet in 2025 case", ["Outlet C", "Outlet F"]),
        ("Sample: Airports on high alert after intelligence warning", ["Outlet E"]),
    ],
}


def _svg(i: int) -> str:
    import base64
    pal = ["#5b8cff", "#ff8a3d", "#5ce1b6", "#ff7ab6", "#b9a3ff", "#ffd23f"]
    a, b = pal[i % 6], pal[(i + 2) % 6]
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' width='160' height='120'><defs><linearGradient id='g' x2='1' y2='1'>"
           f"<stop offset='0' stop-color='{a}'/><stop offset='1' stop-color='{b}'/></linearGradient></defs>"
           f"<rect width='160' height='120' fill='url(#g)'/><circle cx='118' cy='38' r='18' fill='#fff' opacity='.7'/>"
           f"<path d='M0 120 L50 64 L84 96 L112 70 L160 120Z' fill='#161614' opacity='.35'/></svg>")
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


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
                "image": "" if i == 2 else _svg(i),
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
        "outcome": "Sample: so far, prices moved slightly; it is too early to judge the full effect.",
        "future": [{"scenario": "Sample: the change sticks and costs slowly fall", "likelihood": "likely", "signal": "Sample: banks announce new rates"},
                   {"scenario": "Sample: the decision is reversed within months", "likelihood": "unlikely", "signal": "Sample: inflation jumps again"}],
        "lessons": [{"lesson": "Sample: one upstream decision takes months to reach people.", "apply": "Sample: next time, check when the effect actually lands, not just the headline day."}],
        "watch_next": "Sample: what to watch next.",
        "confidence_note": "",
        "_model": model,
    })
