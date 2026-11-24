import "@fontsource-variable/inter";
import "@fontsource-variable/newsreader";
import "@fontsource-variable/newsreader/wght-italic.css";
import "./style.css";
import { Capacitor, CapacitorHttp } from "@capacitor/core";

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
// Server address: published in the repo's config/app.json (so moving the Render server needs
// no new APK), else the one built into the APK. It is never shown in the app.
store.set("api", "");   // drop addresses typed in older versions
const apiBase = () => (store.get("api_remote", "") || import.meta.env.VITE_API_BASE || "").replace(/\/+$/, "");
const BUILD = Number(import.meta.env.VITE_BUILD || 0);
const VERSION = import.meta.env.VITE_VERSION || "dev";
const REPO = import.meta.env.VITE_REPO || "gogul098/Decoder";

const CATS = [
  { id: "tech", label: "Tech & AI" },
  { id: "india", label: "India" },
  { id: "world", label: "World" },
  { id: "markets", label: "Markets" },
  { id: "oil", label: "Oil & Energy" },
  { id: "security", label: "Security" },
];
const CAT_COLOR = { tech: "--blue", india: "--orange", world: "--mint", markets: "--lilac", oil: "--yellow", security: "--red" };
const RANK_COLOR = ["--yellow", "--pink", "--mint", "--blue", "--lilac"];
const setCat = (cat) => { document.documentElement.dataset.cat = cat || "tech"; };
let nextTurn = { color: null, label: "" };   // what the coloured back of the next page flip shows
// ---------------- appearance ----------------
const THEMES = [
  { id: "classic", name: "Classic", desk: "#f6f4ef", paper: "#fffefb", dots: ["#ffd23f", "#ff7ab6", "#5ce1b6", "#6b95ff"] },
  { id: "newsprint", name: "Newsprint", desk: "#ece8de", paper: "#faf7ef", dots: ["#ecd896", "#e7b4aa", "#b5d2bd", "#b0c3dd"] },
  { id: "ocean", name: "Ocean", desk: "#e9f1f4", paper: "#fafdfe", dots: ["#ffd166", "#2ec4b6", "#4d8dff", "#8ecae6"] },
  { id: "sunset", name: "Sunset", desk: "#fbefe7", paper: "#fffaf6", dots: ["#ffc857", "#ff6b9a", "#f9844a", "#e63946"] },
  { id: "forest", name: "Forest", desk: "#edf1e8", paper: "#fbfdf8", dots: ["#e9c46a", "#8ac926", "#2a9d8f", "#e76f51"] },
  { id: "grape", name: "Grape", desk: "#f2eff8", paper: "#fdfbff", dots: ["#ffd6a5", "#ff8fc6", "#a0c4ff", "#bdb2ff"] },
];
const darkMQ = matchMedia("(prefers-color-scheme: dark)");
function applyAppearance() {
  const root = document.documentElement;
  const mode = store.get("mode", "system");
  root.dataset.mode = mode === "system" ? (darkMQ.matches ? "dark" : "light") : mode;
  root.dataset.theme = store.get("theme", "classic");
  const desk = getComputedStyle(root).getPropertyValue("--desk").trim();
  document.querySelectorAll('meta[name="theme-color"]').forEach((m) => m.setAttribute("content", desk));
}
darkMQ.addEventListener?.("change", applyAppearance);
applyAppearance();

const tilt = (id) => ((parseInt(id.slice(0, 4), 16) % 9) - 4) || 3;       // each clipping sits a bit crooked
const clip = (s, big = false) => s.image ? `
  <figure class="clip${big ? " big" : ""}" style="--tilt:${tilt(s.id)}deg"><i class="pin"></i>
    <img src="${esc(s.image)}" alt="" loading="lazy" referrerpolicy="no-referrer" decoding="async">
    ${big && s.image_credit ? `<figcaption>Photo: ${esc(s.image_credit)}</figcaption>` : ""}</figure>` : "";
function hideBrokenClips(root) {
  root.querySelectorAll(".clip img").forEach((img) => img.addEventListener("error", () => {
    img.closest(".leaf")?.classList.remove("has-clip");
    img.closest(".clip")?.remove();
  }));
}

const catLabel = (id) => ({ tech: "Tech & AI", india: "Indian politics", world: "World politics", markets: "Stock markets", oil: "Oil & energy", security: "Terror & security" }[id] || id);

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
  let downSince = 0;
  es.onerror = () => {                                        // EventSource retries on its own
    setLive("connecting", "Reconnecting");
    downSince = downSince || Date.now();
    if (Date.now() - downSince > 20000) { downSince = Date.now(); checkConfig(); }   // maybe the server moved
  };
  es.addEventListener("open", () => { downSince = 0; });
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
  back.innerHTML = `<b>${esc(nextTurn.label || (dir === "back" ? "5" : "→"))}</b>`;
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

// ---------------- updates & remote config ----------------
// Each GitHub build publishes update.json next to the APK; the repo holds config/app.json with
// the server address. Native HTTP is used so GitHub's download links work without CORS issues.
async function httpJSON(url) {
  if (isNative) {
    const r = await CapacitorHttp.get({ url, headers: { "Cache-Control": "no-cache" }, connectTimeout: 8000, readTimeout: 8000 });
    if (r.status >= 400) throw new Error(`HTTP ${r.status}`);
    return typeof r.data === "string" ? JSON.parse(r.data) : r.data;
  }
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

function toast(text) {
  const t = document.createElement("div");
  t.className = "toast";
  t.textContent = text;
  document.body.appendChild(t);
  setTimeout(() => t.classList.add("out"), 3200);
  setTimeout(() => t.remove(), 3700);
}

async function checkConfig() {
  try {
    const cfg = await httpJSON(`https://raw.githubusercontent.com/${REPO}/main/config/app.json?t=${Date.now()}`);
    const remote = (cfg.api_base || "").trim().replace(/\/+$/, "");
    if (!remote || remote === store.get("api_remote", "")) return;
    const before = apiBase();
    store.set("api_remote", remote);
    if (apiBase() !== before) {                // only when the user hasn't typed their own address
      state.feeds = {};
      connectLive();
      if (current.name === "home") home(current.cat);
      if (before) toast("Switched to the new server");
    }
  } catch { /* offline or GitHub unreachable: try again next launch */ }
}

async function checkUpdate({ manual = false } = {}) {
  if (!isNative && !manual) return null;       // the web preview has nothing to install
  const info = await httpJSON(`https://github.com/${REPO}/releases/download/latest/update.json?t=${Date.now()}`);
  if (!(info.build > BUILD)) return { info, newer: false };
  const snoozed = JSON.parse(store.get("update_snooze", "{}"));
  if (!manual && snoozed.build === info.build && Date.now() - snoozed.at < 12 * 3600e3) return { info, newer: true };
  showUpdate(info);
  return { info, newer: true };
}

function showUpdate(info) {
  if (document.querySelector(".sheet-wrap")) return;
  const wrap = document.createElement("div");
  wrap.className = "sheet-wrap";
  wrap.innerHTML = `
    <div class="scrim"></div>
    <div class="update box" role="dialog" aria-labelledby="upd-title">
      <span class="tag">Update available</span>
      <h2 id="upd-title">Version ${esc(info.version)} is ready</h2>
      <p class="upd-notes">${esc(info.notes || "Improvements and fixes.")}</p>
      <p class="note">You have ${esc(VERSION)}. Tap download, then open the file when it finishes to install. Android may ask once to allow installs from your browser.</p>
      <div class="upd-actions"><button class="btn solid" id="upd-go">Download update</button><button class="btn" id="upd-later">Later</button></div>
    </div>`;
  document.body.appendChild(wrap);
  const close = () => { wrap.classList.add("out"); setTimeout(() => wrap.remove(), 250); };
  wrap.querySelector("#upd-go").addEventListener("click", () => { openExternal(info.apk_url); close(); });
  const later = () => { store.set("update_snooze", JSON.stringify({ build: info.build, at: Date.now() })); close(); };
  wrap.querySelector("#upd-later").addEventListener("click", later);
  wrap.querySelector(".scrim").addEventListener("click", later);
}

let lastChecks = 0;
function backgroundChecks() {
  if (Date.now() - lastChecks < 10 * 60e3) return;   // at most every 10 minutes
  lastChecks = Date.now();
  checkConfig();
  checkUpdate().catch(() => {});
}

// ---------------- screens ----------------
const current = { name: "", cat: "", id: "" };
const scrollMemo = {};

function needSetup() {
  view.innerHTML = `<div class="notice box" style="margin-top:24px"><h2>Getting things ready</h2>
    <p>Decoded is looking for its news server. Check your internet connection; this usually takes a few seconds.</p>
    <button class="btn solid" id="retry-setup">Try again</button></div>`;
  view.querySelector("#retry-setup").addEventListener("click", async () => {
    await checkConfig();
    if (apiBase()) { connectLive(); route(); }
  });
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
  const order = CATS.map((c) => c.id);
  view.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.cat !== cat) switchTopic(b.dataset.cat, order.indexOf(b.dataset.cat) > order.indexOf(cat) ? 1 : -1);
  }));
  // keep the selected topic visible in the tab bar
  const tabs = view.querySelector(".tabs"), sel = view.querySelector('.tab[aria-selected="true"]');
  if (tabs && sel) tabs.scrollLeft = sel.offsetLeft - (tabs.clientWidth - sel.offsetWidth) / 2;
  if (!store.get("swipe_tip", "")) {
    store.set("swipe_tip", "1");
    setTimeout(() => toast("Tip: swipe left or right to change topic"), 2800);
  }
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
      <div class="frame"><div class="leaf${s.image ? " has-clip" : ""}">
        <div class="num">${i + 1}</div>
        <div><h2>${esc(s.title)}</h2>
          <div class="meta"><span>${s.outlets} ${s.outlets > 1 ? "outlets" : "outlet"}</span><span>${ago(s.published)}</span><span>${esc(s.sources[0]?.name || "")}</span></div>
        </div>${clip(s)}
      </div></div>
      <svg class="corner" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><polygon points="0,0 0,100 100,100"/></svg>
    </a>`).join("");
  hideBrokenClips(list);
  list.querySelectorAll(".sheet").forEach((a) => a.addEventListener("click", (e) => {
    e.preventDefault();
    a.classList.add("curl");                       // the corner lifts first, then the page turns
    nextTurn = { color: RANK_COLOR[(+a.dataset.rank - 1) % 5], label: a.dataset.rank };
    setTimeout(() => { location.hash = a.getAttribute("href"); }, reduced ? 0 : 170);
  }));
  renderArchive(cat);
}

// "Earlier today": stories that were in the top 5 before a refresh (kept for the day)
const archiveOpen = {};
function renderArchive(cat) {
  const list = document.getElementById("list");
  const items = [...(state.feeds[cat]?.archive || [])].sort((a, b) => b.published - a.published);
  list.querySelector(".archive")?.remove();
  if (!items.length) return;
  const time = (ts) => new Date(ts * 1000).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
  list.insertAdjacentHTML("beforeend", `
    <section class="archive${archiveOpen[cat] ? " open" : ""}">
      <button class="archive-head" aria-expanded="${!!archiveOpen[cat]}">
        <span>Earlier today</span><span class="count">${items.length}</span><i></i></button>
      <div class="archive-list">${items.map((a) => `
        <a href="#/s/${a.id}" class="archived"><span class="when">${time(a.published)}</span>
          <span class="t">${esc(a.title)}</span><span class="m">${esc(a.source || "")}${a.outlets > 1 ? ` · ${a.outlets} outlets` : ""}</span></a>`).join("")}
      </div>
    </section>`);
  list.querySelector(".archive-head").addEventListener("click", (e) => {
    archiveOpen[cat] = !archiveOpen[cat];
    const sec = e.currentTarget.parentElement;
    sec.classList.toggle("open", archiveOpen[cat]);
    e.currentTarget.setAttribute("aria-expanded", archiveOpen[cat]);
  });
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
      <header class="masthead">${known ? `${kicker(known)}${clip(known, true)}<h1>${esc(known.title)}</h1>` : `<h1>Decoding…</h1>`}</header>
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
      <header class="masthead" style="--c:var(${CAT_COLOR[s.category] || "--yellow"})">${kicker(s)}${clip(s, true)}<h1>${esc(d.headline || s.title)}</h1></header>
      <div class="inner">
      ${d.hook ? `<p class="hook">${esc(d.hook)}</p>` : ""}
      <div class="core"><span class="tag">The core idea</span><p>${esc(d.core_idea)}</p></div>
      ${qa.length ? `<dl class="qa">${qa.map(([q, v], i) => `<div><dt><span class="tag" style="${col(i + 1)}">${q}</span></dt><dd>${esc(v)}</dd></div>`).join("")}</dl>` : ""}
      ${d.who_affected?.length ? `${sec("Who it affects")}<div class="who">${d.who_affected.map((w, i) =>
        `<div style="${col(i + 2)}"><b>${esc(w.group)}</b>${w.impact ? `<span>${esc(w.impact)}</span>` : ""}</div>`).join("")}</div>` : ""}
      ${d.backstory?.length ? `${sec("How we got here")}<ol class="timeline">${d.backstory.map((b, i) =>
        `<li style="${col(i)}">${b.date ? `<time>${esc(b.date)}</time><br>` : ""}${esc(b.event)}</li>`).join("")}</ol>` : ""}
      ${d.outcome ? `${sec("Outcome so far")}<p class="outcome">${esc(d.outcome)}</p>` : ""}
      ${d.future?.length ? `${sec("What could happen next")}<div class="future">${d.future.map((f) => `
        <div class="scenario lk-${esc(f.likelihood)}"><span class="lk">${esc(f.likelihood[0].toUpperCase() + f.likelihood.slice(1))}</span>
          <p>${esc(f.scenario)}</p>${f.signal ? `<p class="signal"><b>Sign to watch:</b> ${esc(f.signal)}</p>` : ""}</div>`).join("")}
        <p class="note">Possibilities, not predictions.</p></div>` : ""}
      ${d.lessons?.length ? `${sec("What we can learn")}<ol class="lessons">${d.lessons.map((l, i) => `
        <li style="${col(i + 1)}"><p class="lesson">${esc(l.lesson)}</p>${l.apply ? `<p class="apply"><span class="tag">Apply it</span> ${esc(l.apply)}</p>` : ""}</li>`).join("")}</ol>` : ""}
      ${["markets", "oil"].includes(s.category) ? `<p class="note">This explains what happened and why. It isn't financial advice.</p>` : ""}
      ${d.narrative?.length ? `${sec("The full story")}<div class="narrative">${d.narrative.map((p) => `<p>${esc(p)}</p>`).join("")}</div>` : ""}
      ${d.watch_next ? `${sec("What to watch next")}<p class="watch">${esc(d.watch_next)}</p>` : ""}
      ${d.confidence_note ? `<p class="note">${esc(d.confidence_note)}</p>` : ""}
      ${sec("Sources")}
      <div class="sources">${sources.map((x, i) => `<a href="${esc(x.url)}" data-i="${i}"><b>${esc(x.name)}</b>${x.earlier ? " · earlier" : ""} — ${esc(x.title)}</a>`).join("")}</div>
      <p class="fine">Written by AI (${esc(d.model)}) from the reports listed above. Check them for anything important.</p>
      </div>
    </article>`;
  const script = [d.headline, d.hook, "The core idea. " + d.core_idea, d.what_changed && "What changed. " + d.what_changed,
    d.why && "Why. " + d.why, d.outcome && "Outcome so far. " + d.outcome,
    d.future?.length && "What could happen next. " + d.future.map((f) => `${f.likelihood}: ${f.scenario}`).join(". "),
    d.lessons?.length && "What we can learn. " + d.lessons.map((l) => l.lesson).join(" "),
    ...(d.narrative || [])].filter(Boolean).join("\n\n");
  hideBrokenClips(view);
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
      <h2 class="sec" style="--c:var(--yellow)">Appearance</h2>
      <div class="seg" role="group" aria-label="Light or dark">${[["system", "System"], ["light", "Light"], ["dark", "Dark"]].map(([v, l]) =>
        `<button data-mode="${v}" aria-pressed="${store.get("mode", "system") === v}">${l}</button>`).join("")}</div>
      <div class="themes">${THEMES.map((t) => `
        <button class="swatch" data-theme="${t.id}" aria-pressed="${store.get("theme", "classic") === t.id}" style="--sw-desk:${t.desk};--sw-paper:${t.paper}">
          <span class="mini"><span class="dots">${t.dots.map((c) => `<i style="background:${c}"></i>`).join("")}</span><span class="lines"></span></span>
          <b>${t.name}</b></button>`).join("")}</div>
      <h2 class="sec" style="--c:var(--mint)">App version</h2>
      <p style="margin:0 0 12px">Decoded ${esc(VERSION)}${BUILD ? ` · build ${BUILD}` : ""}</p>
      <button class="btn" id="check">Check for updates</button>
      <p id="umsg" class="note"></p>
    </div>`;
  view.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => {
    store.set("mode", b.dataset.mode); applyAppearance();
    view.querySelectorAll(".seg button").forEach((x) => x.setAttribute("aria-pressed", x === b));
  }));
  view.querySelectorAll(".swatch").forEach((b) => b.addEventListener("click", () => {
    store.set("theme", b.dataset.theme); applyAppearance();
    view.querySelectorAll(".swatch").forEach((x) => x.setAttribute("aria-pressed", x === b));
  }));
  view.querySelector("#check").addEventListener("click", async () => {
    const m = view.querySelector("#umsg");
    m.className = "note"; m.textContent = "Checking…";
    try {
      const r = await checkUpdate({ manual: true });
      m.className = "note ok";
      m.textContent = r.newer ? `Version ${r.info.version} is available.` : "You're on the latest version.";
    } catch { m.className = "note bad"; m.textContent = "Couldn't check right now. Try again later."; }
  });
}

// ---------------- pull to refresh ----------------
// Drag the list down from the top: a paper sheet's corner folds over as you pull; let go past
// the line and the server fetches fresh RSS while a loading screen rotates through taglines.
const TAGLINES = [
  "Rounding up today's stories…",
  "Reading between the headlines…",
  "Finding out what actually changed…",
  "Asking why, not just what…",
  "Folding the news into shape…",
];
let refreshing = false;

function setupPull() {
  const ptr = document.createElement("div");
  ptr.className = "ptr";
  ptr.innerHTML = `<div class="ptr-sheet"><i></i></div><span>Pull to refresh</span>`;
  document.body.appendChild(ptr);
  const label = ptr.querySelector("span");
  const LIMIT = 76;
  let startY = null, pull = 0;
  const reset = () => { pull = 0; startY = null; ptr.style.setProperty("--p", 0); ptr.classList.remove("ready"); view.style.transform = ""; };

  window.addEventListener("touchstart", (e) => {
    if (current.name !== "home" || refreshing || window.scrollY > 0 || document.querySelector(".sheet-wrap,.turn-wrap")) return;
    startY = e.touches[0].clientY;
  }, { passive: true });
  window.addEventListener("touchmove", (e) => {
    if (startY === null) return;
    const dy = e.touches[0].clientY - startY;
    if (dy <= 0 || window.scrollY > 0) { reset(); return; }
    e.preventDefault();
    pull = Math.min(130, dy * 0.55);
    ptr.style.setProperty("--p", Math.min(1, pull / LIMIT));
    view.style.transform = `translateY(${pull}px)`;
    const ready = pull >= LIMIT;
    ptr.classList.toggle("ready", ready);
    label.textContent = ready ? "Release to refresh" : "Pull to refresh";
  }, { passive: false });
  window.addEventListener("touchend", () => {
    if (startY === null) return;
    const go = pull >= LIMIT;
    view.style.transition = "transform .3s cubic-bezier(.2,.8,.2,1)";
    reset();
    setTimeout(() => { view.style.transition = ""; }, 320);
    if (go) refreshNow();
  });
}

async function refreshNow() {
  if (refreshing || current.name !== "home") return;
  refreshing = true;
  const cat = current.cat;
  const list = document.getElementById("list");
  const before = state.feeds[cat]?.updated || 0;
  const oldIds = new Set((state.feeds[cat]?.stories || []).map((s) => s.id));
  if (list) {
    list.innerHTML = `<div class="loading box">
      <div class="stack"><b></b><b></b><b></b></div>
      <p class="tagline" id="tagline">${TAGLINES[0]}</p>
      <p class="note">Fetching the latest in ${esc(catLabel(cat))}</p></div>`;
  }
  let t = 0;
  const rot = setInterval(() => {
    const el = document.getElementById("tagline");
    if (!el) return;
    el.classList.add("swap");
    setTimeout(() => { el.textContent = TAGLINES[++t % TAGLINES.length]; el.classList.remove("swap"); }, 220);
  }, 1800);
  const started = Date.now();
  try {
    if (!es || es.readyState === 2) connectLive();
    await getJSON(`/api/refresh?category=${cat}`);
    // wait for the ingester: the feed's timestamp moves when it has run (max ~25 s)
    while (Date.now() - started < 25000) {
      await new Promise((r) => setTimeout(r, 1500));
      const d = await getJSON(`/api/feed/${cat}`).catch(() => null);
      if (d && d.updated > before) { state.feeds[cat] = d; delete state.pending[cat]; break; }
    }
  } catch { /* fall through and show what we have */ }
  await new Promise((r) => setTimeout(r, Math.max(0, 1400 - (Date.now() - started))));   // let the tagline be read
  clearInterval(rot);
  refreshing = false;
  if (current.name === "home" && current.cat === cat) {
    document.getElementById("fresh") && (document.getElementById("fresh").innerHTML = "");
    const fresh = (state.feeds[cat]?.stories || []).filter((s) => !oldIds.has(s.id)).map((s) => s.id);
    renderList(cat, fresh);
    toast(fresh.length ? `${fresh.length} fresh ${fresh.length === 1 ? "story" : "stories"} · older ones moved to Earlier today`
                       : "Nothing new yet. Try again in a bit");
  }
}

// ---------------- swipe between topics ----------------
// Swipe left for the next topic, right for the previous one (in tab order, no wrap-around).
// The gesture locks to an axis after a few pixels, so vertical scrolling and pull-to-refresh
// are unaffected, and swipes that start on the tab bar scroll the tabs instead.
function setupSwipe() {
  let x0 = null, y0 = 0, axis = null, dx = 0;
  const order = CATS.map((c) => c.id);
  const neighbour = (dir) => order[order.indexOf(current.cat) + dir];

  window.addEventListener("touchstart", (e) => {
    if (current.name !== "home" || refreshing || e.target.closest(".tabs") || document.querySelector(".sheet-wrap,.turn-wrap")) return;
    x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; axis = null; dx = 0;
  }, { passive: true });

  window.addEventListener("touchmove", (e) => {
    if (x0 === null) return;
    const mx = e.touches[0].clientX - x0, my = e.touches[0].clientY - y0;
    if (!axis && Math.hypot(mx, my) > 10) axis = Math.abs(mx) > Math.abs(my) * 1.2 ? "x" : "y";
    if (axis !== "x") return;
    e.preventDefault();
    dx = mx;
    const edge = !neighbour(dx < 0 ? 1 : -1);               // nothing further this way: resist
    view.style.transform = `translateX(${edge ? dx * 0.15 : dx * 0.45}px)`;
    view.style.opacity = String(1 - Math.min(0.35, Math.abs(dx) / 900));
  }, { passive: false });

  window.addEventListener("touchend", () => {
    if (x0 === null) return;
    const next = axis === "x" && Math.abs(dx) > 70 ? neighbour(dx < 0 ? 1 : -1) : null;
    x0 = null;
    if (axis !== "x") return;
    if (!next) {
      view.style.transition = "transform .25s cubic-bezier(.2,.8,.2,1), opacity .25s";
      view.style.transform = ""; view.style.opacity = "";
      setTimeout(() => { view.style.transition = ""; }, 260);
      return;
    }
    switchTopic(next, dx < 0 ? 1 : -1);
  });
}

function switchTopic(cat, dir) {
  if (reduced) { history.replaceState(null, "", `#/c/${cat}`); home(cat); return; }
  view.style.transition = "transform .16s ease-in, opacity .16s ease-in";
  view.style.transform = `translateX(${dir * -40}%)`;
  view.style.opacity = "0";
  setTimeout(() => {
    history.replaceState(null, "", `#/c/${cat}`);
    home(cat);
    window.scrollTo(0, 0);
    view.style.transition = "none";
    view.style.transform = `translateX(${dir * 40}%)`;
    requestAnimationFrame(() => requestAnimationFrame(() => {
      view.style.transition = "transform .3s cubic-bezier(.2,.8,.2,1), opacity .3s";
      view.style.transform = ""; view.style.opacity = "";
      setTimeout(() => { view.style.transition = ""; }, 320);
    }));
  }, 160);
}

// ---------------- intro ----------------
function splash() {
  if (reduced) return Promise.resolve();
  const el = document.createElement("div");
  el.className = "splash";
  el.innerHTML = `
    <div class="splash-card">
      <div class="splash-sheet"><svg class="splash-corner" viewBox="0 0 100 100" preserveAspectRatio="none"><polygon points="0,0 0,100 100,100"/></svg>
        <span class="splash-d">D</span></div>
      <h1 class="splash-word">Decoded</h1>
      <p class="splash-tag">Not just what happened.<br><em>Why it happened.</em></p>
    </div>
    <div class="splash-dots"><i></i><i></i><i></i></div>`;
  document.body.appendChild(el);
  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return; done = true;
      el.classList.add("out");
      setTimeout(() => { el.remove(); resolve(); }, 520);
    };
    el.addEventListener("click", finish);           // tap to skip
    setTimeout(finish, 2400);
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
splash();
route();
setupPull();
setupSwipe();
(async () => {
  if (!apiBase()) await checkConfig();          // first launch: learn the server address
  connectLive();
  if (current.name === "home" && apiBase()) home(current.cat);
  backgroundChecks();
})();

if (isNative) {
  import("@capacitor/app").then(({ App }) => {
    App.addListener("backButton", () => {
      if (current.name === "home") App.exitApp(); else location.hash = `#/c/${store.get("cat", "tech")}`;
    });
    App.addListener("resume", () => { if (!es || es.readyState === 2) connectLive(); backgroundChecks(); });
  });
}
