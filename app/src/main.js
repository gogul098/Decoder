import "@fontsource-variable/inter";
import "@fontsource-variable/newsreader";
import "@fontsource-variable/newsreader/wght-italic.css";
import "./style.css";
import { Capacitor } from "@capacitor/core";

const view = document.getElementById("view");
const page = document.getElementById("page");
const liveEl = document.getElementById("live");
const isNative = Capacitor.isNativePlatform();
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

// ---------------- settings ----------------
const store = {
  get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch {} },
};
const apiBase = () => (store.get("api", import.meta.env.VITE_API_BASE || "") || "").replace(/\/+$/, "");

const CATS = [
  { id: "tech", label: "Tech & AI" },
  { id: "india", label: "India" },
  { id: "world", label: "World" },
  { id: "security", label: "Security" },
];
const CAT_COLOR = { tech: "--blue", india: "--orange", world: "--mint", security: "--red" };
const RANK_COLOR = ["--yellow", "--pink", "--mint", "--blue", "--lilac"];
const setCat = (cat) => { document.documentElement.dataset.cat = cat || "tech"; };
let nextTurn = { color: null, label: "" };   // what the coloured back of the next page flip shows
const catLabel = (id) => ({ tech: "Tech & AI", india: "Indian politics", world: "World politics", security: "Terror & security" }[id] || id);

// ---------------- helpers ----------------
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
function ago(ts) {
  const m = Math.max(1, Math.round((Date.now() / 1000 - ts) / 60));
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  return h < 24 ? `${h} h ago` : `${Math.round(h / 24)} d ago`;
}
const today = () => new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" });
async function getJSON(path) {
  const r = await fetch(apiBase() + path, { headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `Server error ${r.status}`);
  return r.json();
}
async function openExternal(url) {
  if (isNative) { const { Browser } = await import("@capacitor/browser"); await Browser.open({ url }); }
  else window.open(url, "_blank", "noopener");
}
const icon = {
  play: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 4.5v15l13-7.5z"/></svg>',
  stop: '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="1.5"/></svg>',
};

// ---------------- live news (SSE) ----------------
// One stream, opened when the app starts. The server sends today's top 5 for every
// category straight from Redis, then pushes new stories whenever the ingester publishes.
const state = { feeds: {}, pending: {}, status: "" };
let es = null;
function setLive(s, text) { liveEl.dataset.state = s; liveEl.querySelector("span").textContent = text; }

function connectLive() {
  if (es) es.close();
  if (!apiBase()) { setLive("off", "Offline"); return; }
  setLive("connecting", "Connecting");
  // free hosting sleeps when idle and takes ~1 min to wake; say so instead of looking stuck
  const wake = setTimeout(() => { if (liveEl.dataset.state !== "live") setLive("connecting", "Waking server…"); }, 4000);
  es = new EventSource(apiBase() + "/api/stream");
  es.onopen = () => { clearTimeout(wake); setLive("live", "Live"); };
  es.onerror = () => setLive("connecting", "Reconnecting");   // EventSource retries on its own
  es.addEventListener("snapshot", (e) => {
    const d = JSON.parse(e.data);
    state.feeds[d.category] = d;
    delete state.pending[d.category];
    if (current.name === "home" && current.cat === d.category) renderList(d.category);
  });
  es.addEventListener("update", (e) => {
    const d = JSON.parse(e.data);
    const prev = state.feeds[d.category];
    const had = prev?.stories?.length;
    const stale = !prev || Date.now() / 1000 - prev.updated > 1800;   // old list from before the server slept
    if (!had || stale || !(current.name === "home" && current.cat === d.category)) {
      state.feeds[d.category] = d;                  // nobody is looking at it: swap silently
      if (current.name === "home" && current.cat === d.category) renderList(d.category);
    } else {
      state.pending[d.category] = d;                // don't move a list under someone's thumb
      showFresh(d.category);
    }
  });
  es.addEventListener("status", (e) => {
    state.status = JSON.parse(e.data).message;
    if (current.name === "home") renderList(current.cat);
  });
}

// ---------------- speech ----------------
let speaking = false;
async function speak(text, btn) {
  const set = (on) => { speaking = on; if (btn) btn.innerHTML = `${on ? icon.stop : icon.play}${on ? "Stop" : "Listen"}`; };
  if (speaking) { await stopSpeech(); set(false); return; }
  set(true);
  try {
    if (isNative) {
      const { TextToSpeech } = await import("@capacitor-community/text-to-speech");
      await TextToSpeech.speak({ text, lang: "en-IN", rate: 1.0, category: "playback" });
      set(false);
    } else if ("speechSynthesis" in window) {
      const u = new SpeechSynthesisUtterance(text);
      u.lang = "en-IN"; u.onend = u.onerror = () => set(false);
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

// ---------------- page turn ----------------
// The old page is copied onto a sheet that curls away (forward) or peels off to the
// right (back), uncovering the new page underneath.
function turnPage(dir, render) {
  if (reduced || !current.name) { render(); return; }
  const y = window.scrollY;
  const wrap = document.createElement("div");
  wrap.className = "turn-wrap";
  const sheet = document.createElement("div");
  sheet.className = "turn";
  const color = nextTurn.color || CAT_COLOR[current.cat] || "--cat";
  wrap.style.setProperty("--flip", `var(${color})`);
  const front = document.createElement("div");
  front.className = "face front";
  const back = document.createElement("div");
  back.className = "face back";
  back.innerHTML = `<b>${esc(nextTurn.label || (dir === "back" ? "5" : "→"))}</b><i>${dir === "back" ? "Back to the top five" : "Decoding…"}</i>`;
  nextTurn = { color: null, label: "" };
  const copy = page.cloneNode(true);
  copy.removeAttribute("id");
  copy.classList.add("frozen");
  copy.querySelectorAll("[id]").forEach((el) => el.removeAttribute("id"));
  copy.style.transform = `translateY(${-y}px)`;
  front.appendChild(copy);
  sheet.append(front, back);
  wrap.appendChild(sheet);
  const shade = document.createElement("div");
  shade.className = "under-shadow";
  shade.style.setProperty("--flip", `var(${color})`);
  render();
  document.body.append(shade, wrap);
  requestAnimationFrame(() => sheet.classList.add(dir === "back" ? "bwd" : "fwd"));
  const done = () => { wrap.remove(); shade.remove(); };
  sheet.addEventListener("animationend", (e) => { if (e.target === sheet) done(); });
  setTimeout(done, 1400);
}

// ---------------- screens ----------------
const current = { name: "", cat: "", id: "" };
const scrollMemo = {};

function needSetup() {
  view.innerHTML = `<div class="notice box" style="margin-top:24px"><h2>Connect your server</h2>
    <p>Decoded needs the address of your backend, the server that collects the news and talks to Groq.</p>
    <a class="btn solid" href="#/settings">Open settings</a></div>`;
}

function home(cat) {
  cat = CATS.some((c) => c.id === cat) ? cat : store.get("cat", "tech");
  store.set("cat", cat);
  Object.assign(current, { name: "home", cat });
  setCat(cat);
  view.innerHTML = `
    <p class="dateline">${esc(today())}</p>
    <h1 class="title">Today's <em>top five</em></h1>
    <nav class="tabs" role="tablist">${CATS.map((c) =>
      `<button class="tab" role="tab" style="--c:var(${CAT_COLOR[c.id]})" aria-selected="${c.id === cat}" data-cat="${c.id}">${esc(c.label)}</button>`).join("")}</nav>
    <div id="fresh"></div>
    <div id="list"></div>`;
  view.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.cat !== cat) history.replaceState(null, "", `#/c/${b.dataset.cat}`), home(b.dataset.cat);
  }));
  if (!apiBase()) return needSetup();
  renderList(cat);
  if (state.pending[cat]) showFresh(cat);
}

function renderList(cat, highlight = []) {
  const list = document.getElementById("list");
  if (!list) return;
  const feed = state.feeds[cat];
  if (!feed) { list.innerHTML = '<div class="skel"></div>'.repeat(5); return; }
  if (!feed.stories.length) {
    list.innerHTML = `<div class="empty box"><p style="margin:0;color:var(--ink2)">${esc(state.status || "No stories yet. They'll appear here the moment they arrive.")}</p></div>`;
    return;
  }
  list.innerHTML = feed.stories.map((s, i) => `
    <a class="sheet${highlight.includes(s.id) ? " new" : ""}" href="#/s/${s.id}" data-rank="${i + 1}"
       style="--c:var(${RANK_COLOR[i % 5]});animation-delay:${i * 60}ms">
      <div class="frame"><div class="leaf">
        <div class="num">${i + 1}</div>
        <div><h2>${esc(s.title)}</h2>
          <div class="meta"><span>${s.outlets} ${s.outlets > 1 ? "outlets" : "outlet"}</span><span>${ago(s.published)}</span><span>${esc(s.sources[0]?.name || "")}</span></div>
        </div>
      </div></div>
      <svg class="corner" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><polygon points="0,0 0,100 100,100"/></svg>
    </a>`).join("");
  list.querySelectorAll(".sheet").forEach((a) => a.addEventListener("click", (e) => {
    e.preventDefault();
    a.classList.add("curl");                       // the corner lifts first, then the page turns
    nextTurn = { color: RANK_COLOR[(+a.dataset.rank - 1) % 5], label: a.dataset.rank };
    setTimeout(() => { location.hash = a.getAttribute("href"); }, reduced ? 0 : 170);
  }));
}

function showFresh(cat) {
  const box = document.getElementById("fresh");
  if (!box || current.cat !== cat) return;
  box.innerHTML = `<div class="fresh"><button>New stories · show</button></div>`;
  box.querySelector("button").addEventListener("click", () => {
    const old = new Set((state.feeds[cat]?.stories || []).map((s) => s.id));
    state.feeds[cat] = state.pending[cat];
    delete state.pending[cat];
    box.innerHTML = "";
    renderList(cat, state.feeds[cat].stories.filter((s) => !old.has(s.id)).map((s) => s.id));
    window.scrollTo({ top: 0, behavior: reduced ? "auto" : "smooth" });
  });
}

let decodeSrc = null;
function story(id) {
  Object.assign(current, { name: "story", id });
  stopSpeech();
  const known = Object.values(state.feeds).flatMap((f) => f.stories).find((s) => s.id === id);
  setCat(known?.category || store.get("cat", "tech"));
  view.innerHTML = `
    <div class="story-top"><a class="back" href="#/c/${store.get("cat", "tech")}">← Top five</a></div>
    <article class="paper box">
      <header class="masthead">${known ? `${kicker(known)}<h1>${esc(known.title)}</h1>` : `<h1>Decoding…</h1>`}</header>
      <div class="inner">
      <ol class="steps">
        <li data-s="queued"><i></i>Waiting for a free model</li>
        <li data-s="finding"><i></i>Reading earlier coverage</li>
        <li data-s="writing"><i></i>Writing the story</li>
      </ol>
      <div class="lines">${'<span style="width:%"></span>'.repeat(5).replace(/%/g, () => 60 + Math.round(Math.random() * 40) + "%")}</div>
      </div>
    </article>`;
  if (!apiBase()) return needSetup();
  decode(id);
}

function setStage(stage, extra = {}) {
  const order = ["queued", "finding", "writing"];
  const at = order.indexOf(stage);
  view.querySelectorAll(".steps li").forEach((li, i) => {
    li.className = i < at ? "done" : i === at ? "on" : "";
  });
  if (stage === "writing" && extra.leads !== undefined) {
    const li = view.querySelector('.steps li[data-s="finding"]');
    if (li) li.lastChild.textContent = `Read ${extra.leads} earlier report${extra.leads === 1 ? "" : "s"}`;
  }
}

function decode(id) {
  if (decodeSrc) decodeSrc.close();
  const mine = id;
  let finished = false;
  const fail = (msg) => {
    finished = true;
    if (current.id !== mine || current.name !== "story") return;
    view.querySelector(".steps")?.remove(); view.querySelector(".lines")?.remove();
    view.querySelector(".inner").insertAdjacentHTML("beforeend",
      `<div class="notice" style="padding:0;margin-top:18px"><p>${esc(msg)}</p><button class="btn" id="retry">Try again</button></div>`);
    view.querySelector("#retry").addEventListener("click", () => story(mine));
  };
  const src = (decodeSrc = new EventSource(`${apiBase()}/api/decode/${id}/stream`));
  src.addEventListener("progress", (e) => { const d = JSON.parse(e.data); if (current.id === mine) setStage(d.stage, d); });
  src.addEventListener("ready", (e) => { finished = true; src.close(); if (current.id === mine && current.name === "story") renderStory(JSON.parse(e.data).result); });
  src.addEventListener("error", (e) => {
    if (e.data) { src.close(); fail(JSON.parse(e.data).message); return; }
    if (finished) return;
    src.close();                                      // stream broke: fall back to polling once a second
    poll(mine, fail);
  });
}

async function poll(id, fail, tries = 0) {
  if (current.id !== id || current.name !== "story") return;
  try {
    const d = await getJSON(`/api/decode/${id}`);
    if (d.stage === "ready") return renderStory(d.result);
    if (d.stage === "error") return fail(d.message);
    setStage(d.stage, d);
  } catch (e) { if (tries > 5) return fail("Can't reach the server. Check your connection."); }
  setTimeout(() => poll(id, fail, tries + 1), 1200);
}

const kicker = (s) => `<p class="kicker"><span>${esc(catLabel(s.category))}</span><span>${s.outlets || 1} outlets</span><span>${ago(s.published || Date.now() / 1000)}</span></p>`;
const col = (i) => `--c:var(${RANK_COLOR[i % 5]})`;

function renderStory(d) {
  const s = d.story || {};
  setCat(s.category);
  const qa = [["What changed", d.what_changed], ["Why", d.why], ["How", d.how], ["When", d.when]].filter(([, v]) => v);
  const sources = [
    ...(s.sources || []).map((x) => ({ name: x.name, title: x.title, url: x.url })),
    ...(d.leads || []).map((x) => ({ name: x.source, title: x.title, url: x.url, earlier: true })),
  ];
  let k = 0;
  const sec = (t) => `<h2 class="sec" style="${col(++k)}">${t}</h2>`;
  view.innerHTML = `
    <div class="story-top"><a class="back" href="#/c/${store.get("cat", "tech")}">← Top five</a>
      <button class="btn" id="listen">${icon.play}Listen</button></div>
    <article class="paper box">
      <header class="masthead">${kicker(s)}<h1>${esc(d.headline || s.title)}</h1></header>
      <div class="inner">
      ${d.hook ? `<p class="hook">${esc(d.hook)}</p>` : ""}
      <div class="core"><span class="tag">The core idea</span><p>${esc(d.core_idea)}</p></div>
      ${qa.length ? `<dl class="qa">${qa.map(([q, v], i) => `<div><dt><span class="tag" style="${col(i + 1)}">${q}</span></dt><dd>${esc(v)}</dd></div>`).join("")}</dl>` : ""}
      ${d.who_affected?.length ? `${sec("Who it affects")}<div class="who">${d.who_affected.map((w, i) =>
        `<div style="${col(i + 2)}"><b>${esc(w.group)}</b>${w.impact ? `<span>${esc(w.impact)}</span>` : ""}</div>`).join("")}</div>` : ""}
      ${d.backstory?.length ? `${sec("How we got here")}<ol class="timeline">${d.backstory.map((b, i) =>
        `<li style="${col(i)}">${b.date ? `<time>${esc(b.date)}</time><br>` : ""}${esc(b.event)}</li>`).join("")}</ol>` : ""}
      ${d.narrative?.length ? `${sec("The full story")}<div class="narrative">${d.narrative.map((p) => `<p>${esc(p)}</p>`).join("")}</div>` : ""}
      ${d.watch_next ? `${sec("What to watch next")}<p class="watch">${esc(d.watch_next)}</p>` : ""}
      ${d.confidence_note ? `<p class="note">${esc(d.confidence_note)}</p>` : ""}
      ${sec("Sources")}
      <div class="sources">${sources.map((x, i) => `<a href="${esc(x.url)}" data-i="${i}"><b>${esc(x.name)}</b>${x.earlier ? " · earlier" : ""} — ${esc(x.title)}</a>`).join("")}</div>
      <p class="fine">Written by AI (${esc(d.model)}) from the reports listed above. Check them for anything important.</p>
      </div>
    </article>`;
  const script = [d.headline, d.hook, "The core idea. " + d.core_idea, d.what_changed && "What changed. " + d.what_changed,
    d.why && "Why. " + d.why, ...(d.narrative || [])].filter(Boolean).join("\n\n");
  const lb = view.querySelector("#listen");
  lb.addEventListener("click", () => speak(script, lb));
  view.querySelectorAll(".sources a").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); openExternal(sources[+a.dataset.i].url); }));
}

function settingsView() {
  Object.assign(current, { name: "settings" });
  view.innerHTML = `
    <div class="story-top"><a class="back" href="#/">← Back</a></div>
    <div class="paper box" style="padding:24px 22px">
      <h1 style="font-size:32px;margin-bottom:4px">Settings</h1>
      <div class="field"><label for="api">Server address</label>
        <input id="api" type="url" inputmode="url" autocomplete="off" placeholder="https://news.example.com" value="${esc(apiBase())}"></div>
      <button class="btn solid" id="save">Save and connect</button>
      <p id="msg" class="note"></p>
    </div>`;
  view.querySelector("#save").addEventListener("click", async () => {
    const msg = view.querySelector("#msg");
    const v = view.querySelector("#api").value.trim();
    if (!v) { msg.className = "note bad"; msg.textContent = "Enter an address first."; return; }
    store.set("api", v);
    msg.className = "note"; msg.textContent = "Connecting…";
    try { await getJSON("/api/categories"); msg.className = "note ok"; msg.textContent = "Connected. News will stream in live."; state.feeds = {}; connectLive(); }
    catch (e) { msg.className = "note bad"; msg.textContent = "Couldn't connect: " + e.message; }
  });
}

// ---------------- router ----------------
function route() {
  const prev = current.name;
  if (prev === "home") scrollMemo.home = window.scrollY;
  const h = location.hash.replace(/^#\/?/, "").split("/");
  const go = h[0] === "s" && h[1] ? () => { story(h[1]); window.scrollTo(0, 0); }
    : h[0] === "settings" ? () => { settingsView(); window.scrollTo(0, 0); }
    : () => { home(h[0] === "c" ? h[1] : undefined); window.scrollTo(0, scrollMemo.home || 0); };
  const forward = (h[0] === "s" || h[0] === "settings") && prev === "home";
  const backward = prev && prev !== "home" && !(h[0] === "s" || h[0] === "settings");
  if (forward) turnPage("fwd", go);
  else if (backward) {
    if (decodeSrc) decodeSrc.close();
    stopSpeech();
    nextTurn = { color: CAT_COLOR[store.get("cat", "tech")], label: "5" };
    turnPage("back", go);
  }
  else go();
}
window.addEventListener("hashchange", route);
route();
connectLive();

if (isNative) {
  import("@capacitor/app").then(({ App }) => {
    App.addListener("backButton", () => {
      if (current.name === "home") App.exitApp(); else location.hash = `#/c/${store.get("cat", "tech")}`;
    });
    App.addListener("resume", () => { if (!es || es.readyState === 2) connectLive(); });
  });
}
