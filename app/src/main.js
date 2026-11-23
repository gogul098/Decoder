import "@fontsource/orbitron/700.css";
import "@fontsource/orbitron/900.css";
import "@fontsource/space-grotesk/400.css";
import "@fontsource/space-grotesk/600.css";
import "@fontsource/space-grotesk/700.css";
import "./style.css";
import { Capacitor } from "@capacitor/core";

const view = document.getElementById("view");
const isNative = Capacitor.isNativePlatform();

// ---------- settings ----------
const store = {
  get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch {} },
};
const DEFAULT_API = import.meta.env.VITE_API_BASE || "";
const apiBase = () => (store.get("api", DEFAULT_API) || "").replace(/\/+$/, "");

const CATS = [
  { id: "tech", label: "Tech & AI" },
  { id: "india", label: "Indian Politics" },
  { id: "world", label: "World Politics" },
  { id: "security", label: "Terror & Security" },
];
const catLabel = (id) => CATS.find((c) => c.id === id)?.label || id;

// ---------- helpers ----------
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
function ago(ts) {
  const m = Math.max(1, Math.round((Date.now() / 1000 - ts) / 60));
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  return h < 24 ? `${h} h ago` : `${Math.round(h / 24)} d ago`;
}
async function api(path) {
  if (!apiBase()) throw new Error("NO_API");
  const r = await fetch(apiBase() + path, { headers: { Accept: "application/json" } });
  if (!r.ok) {
    let msg = `Server error ${r.status}`;
    try { msg = (await r.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return r.json();
}
async function openExternal(url) {
  if (isNative) {
    const { Browser } = await import("@capacitor/browser");
    await Browser.open({ url });
  } else window.open(url, "_blank", "noopener");
}
const feedCache = {};
let runId = 0;  // cancels polling when the user navigates away

// ---------- speech ----------
let speaking = false;
async function speak(text, btn) {
  const set = (on) => { speaking = on; if (btn) btn.innerHTML = on ? "■ Stop" : "▶ Listen"; };
  if (speaking) { await stopSpeech(); set(false); return; }
  set(true);
  try {
    if (isNative) {
      const { TextToSpeech } = await import("@capacitor-community/text-to-speech");
      await TextToSpeech.speak({ text, lang: "en-IN", rate: 1.0, category: "playback" });
      set(false);
    } else if ("speechSynthesis" in window) {
      const u = new SpeechSynthesisUtterance(text);
      u.lang = "en-IN";
      u.onend = u.onerror = () => set(false);
      speechSynthesis.speak(u);
    } else set(false);
  } catch { set(false); }
}
async function stopSpeech() {
  try {
    if (isNative) { const { TextToSpeech } = await import("@capacitor-community/text-to-speech"); await TextToSpeech.stop(); }
    else if ("speechSynthesis" in window) speechSynthesis.cancel();
  } catch {}
  speaking = false;
}

// ---------- screens ----------
function needSetup() {
  view.innerHTML = `<section class="fade error">
    <h2 style="margin-top:0">Connect your server</h2>
    <p>The app needs the address of your News Decoded backend (the server that talks to Groq).</p>
    <a class="btn alt" href="#/settings">Open settings</a></section>`;
}

async function home(cat) {
  cat = CATS.some((c) => c.id === cat) ? cat : store.get("cat", "tech");
  store.set("cat", cat);
  view.innerHTML = `<section class="intro fade">
      <h1>Top 5. Decoded.</h1>
      <p>Tap a story to see what changed, why it happened, who it hits and the backstory.</p>
    </section>
    <nav class="tabs" role="tablist">${CATS.map((c) =>
      `<button class="tab" role="tab" aria-selected="${c.id === cat}" data-cat="${c.id}">${esc(c.label)}</button>`).join("")}</nav>
    <div class="meta"><span id="updated">Tuning in…</span><button class="btn-ghost" id="refresh">↻ Refresh</button></div>
    <div id="list">${'<div class="skel"></div>'.repeat(5)}</div>`;
  view.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => { location.hash = `#/c/${b.dataset.cat}`; }));
  view.querySelector("#refresh").addEventListener("click", () => { delete feedCache[cat]; home(cat); });
  if (!apiBase()) return needSetup();

  const list = view.querySelector("#list");
  try {
    const data = feedCache[cat] && Date.now() - feedCache[cat].at < 120000 ? feedCache[cat].data : await api(`/api/feed/${cat}`);
    feedCache[cat] = { at: Date.now(), data };
    if (store.get("cat") !== cat) return;
    view.querySelector("#updated").textContent = `${catLabel(cat)} · updated ${ago(data.updated)}`;
    if (!data.stories.length) { list.innerHTML = `<p class="note">No stories right now. Try refresh.</p>`; return; }
    list.innerHTML = data.stories.map((s, i) => `
      <a class="card fade" style="animation-delay:${i * 60}ms" href="#/s/${s.id}">
        <div class="rank">${String(i + 1).padStart(2, "0")}</div>
        <div><h2>${esc(s.title)}</h2>
          <div class="sub"><span class="pill">${s.outlets} outlet${s.outlets > 1 ? "s" : ""}</span><span>${ago(s.published)}</span><span>${esc(s.sources[0]?.name || "")}</span></div>
        </div></a>`).join("");
  } catch (e) {
    if (e.message === "NO_API") return needSetup();
    list.innerHTML = `<div class="error"><b>Can't reach the server.</b><p>${esc(e.message)}</p><a class="btn alt" href="#/settings">Check settings</a></div>`;
  }
}

async function story(id) {
  const my = ++runId;
  await stopSpeech();
  const known = Object.values(feedCache).flatMap((f) => f.data.stories).find((s) => s.id === id);
  view.innerHTML = `<a class="back" href="#/c/${store.get("cat", "tech")}">← Top 5</a>
    ${known ? `<div class="kicker">${esc(catLabel(known.category))}</div><h2 style="margin:0 0 6px;font-size:20px">${esc(known.title)}</h2>` : ""}
    <div class="decoding"><div class="ring"></div><h2 id="stage">DECODING SIGNAL</h2><p id="sub">Reading earlier coverage to work out why…</p></div>`;
  if (!apiBase()) return needSetup();
  const lines = { queued: "In the queue, a model is about to pick it up…", decoding: "Reading earlier coverage to work out why…" };
  let delay = 900;
  for (let tries = 0; tries < 120; tries++) {
    if (my !== runId) return;
    try {
      const d = await api(`/api/decode/${id}`);
      if (my !== runId) return;
      if (d.status === "ready") return renderStory(d.result);
      if (d.status === "error") throw new Error(d.message);
      const sub = view.querySelector("#sub");
      if (sub) sub.textContent = lines[d.status] || lines.decoding;
    } catch (e) {
      if (my !== runId) return;
      view.querySelector(".decoding")?.remove();
      view.insertAdjacentHTML("beforeend", `<div class="error fade"><b>Couldn't decode this one.</b><p>${esc(e.message)}</p>
        <button class="btn alt" id="retry">Try again</button></div>`);
      view.querySelector("#retry").addEventListener("click", () => story(id));
      return;
    }
    await new Promise((r) => setTimeout(r, delay));
    delay = Math.min(2500, delay * 1.15);
  }
}

function renderStory(d) {
  const s = d.story || {};
  const qa = [["WHAT CHANGED", d.what_changed], ["WHY", d.why], ["HOW", d.how], ["WHEN", d.when]].filter(([, v]) => v);
  const sources = [
    ...(s.sources || []).map((x) => ({ name: x.name, title: x.title, url: x.url })),
    ...(d.leads || []).map((x) => ({ name: x.source, title: x.title, url: x.url, earlier: true })),
  ];
  view.innerHTML = `<article class="story fade">
    <a class="back" href="#/c/${store.get("cat", "tech")}">← Top 5</a>
    <div class="kicker">${esc(catLabel(s.category))} · ${s.outlets || 1} outlets · ${ago(s.published || Date.now() / 1000)}</div>
    <h1>${esc(d.headline || s.title)}</h1>
    ${d.hook ? `<p class="hook">${esc(d.hook)}</p>` : ""}
    <div class="actions"><button class="btn" id="listen">▶ Listen</button>
      ${s.sources?.[0]?.url ? `<button class="btn alt" id="orig">Original report</button>` : ""}</div>
    <div class="core"><b>THE CORE IDEA</b><p>${esc(d.core_idea)}</p></div>
    <div class="qa">${qa.map(([k, v]) => `<div class="q"><h3>${k}</h3><p>${esc(v)}</p></div>`).join("")}</div>
    ${d.who_affected?.length ? `<h2 class="sec">Who it affects</h2><div class="who">${d.who_affected.map((w) =>
      `<div><strong>${esc(w.group)}</strong><span>${esc(w.impact)}</span></div>`).join("")}</div>` : ""}
    ${d.backstory?.length ? `<h2 class="sec">The backstory</h2><ol class="timeline">${d.backstory.map((b) =>
      `<li>${b.date ? `<time>${esc(b.date)}</time>` : ""}${esc(b.event)}</li>`).join("")}</ol>` : ""}
    ${d.narrative?.length ? `<h2 class="sec">The full story</h2><div class="narrative">${d.narrative.map((p) => `<p>${esc(p)}</p>`).join("")}</div>` : ""}
    ${d.watch_next ? `<h2 class="sec">Watch next</h2><div class="watch">${esc(d.watch_next)}</div>` : ""}
    ${d.confidence_note ? `<p class="note">${esc(d.confidence_note)}</p>` : ""}
    <h2 class="sec">Sources</h2><div class="sources">${sources.map((x, i) =>
      `<a href="${esc(x.url)}" data-i="${i}"><b>${esc(x.name)}</b>${x.earlier ? " · earlier" : ""}: ${esc(x.title)}</a>`).join("")}</div>
    <p class="small">Written by AI (${esc(d.model)}) from the headlines above. Check the sources for anything important.</p>
  </article>`;
  const script = [d.headline, d.hook, "The core idea. " + d.core_idea, d.what_changed && "What changed. " + d.what_changed,
    d.why && "Why. " + d.why, ...(d.narrative || [])].filter(Boolean).join("\n\n");
  const lb = view.querySelector("#listen");
  lb.addEventListener("click", () => speak(script, lb));
  view.querySelector("#orig")?.addEventListener("click", () => openExternal(s.sources[0].url));
  view.querySelectorAll(".sources a").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); openExternal(sources[+a.dataset.i].url); }));
  window.scrollTo(0, 0);
}

function settingsView() {
  view.innerHTML = `<section class="fade">
    <a class="back" href="#/">← Back</a>
    <h1 style="font:800 28px var(--display);margin:6px 0">Settings</h1>
    <div class="field"><label for="api">Server address</label>
      <input id="api" type="url" inputmode="url" placeholder="https://your-server.example.com" value="${esc(apiBase())}">
      <span class="note" style="margin:0">Where your News Decoded backend runs.</span></div>
    <div class="actions"><button class="btn" id="save">Save & test</button></div>
    <p id="msg"></p></section>`;
  view.querySelector("#save").addEventListener("click", async () => {
    const v = view.querySelector("#api").value.trim();
    store.set("api", v);
    const msg = view.querySelector("#msg");
    msg.textContent = "Testing…";
    try { await api("/api/categories"); msg.textContent = "✔ Connected."; Object.keys(feedCache).forEach((k) => delete feedCache[k]); }
    catch (e) { msg.textContent = "✖ " + (e.message === "NO_API" ? "Enter an address first." : e.message); }
  });
}

// ---------- router ----------
function route() {
  runId++;
  const h = location.hash.replace(/^#\/?/, "").split("/");
  document.body.classList.toggle("is-home", !h[0] || h[0] === "c");
  if (h[0] === "s" && h[1]) story(h[1]);
  else if (h[0] === "settings") settingsView();
  else home(h[0] === "c" ? h[1] : undefined);
}
window.addEventListener("hashchange", route);
route();

if (isNative) {
  import("@capacitor/app").then(({ App }) => App.addListener("backButton", () => {
    if (location.hash && location.hash !== "#/" && !location.hash.startsWith("#/c/")) history.back();
    else App.exitApp();
  }));
}
