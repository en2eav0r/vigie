// Vigie Web journey screens in the site style (Figma: Web laptop / Investigation, Blocked, Safe, Evidence).
// Vigie Web and Vigie Desktop both use these screens; they render only server data and cannot open a link on their own.
import { esc, markTestMode, streamInvestigation } from "./ui.js";

export { esc, markTestMode, streamInvestigation };

const SPRITE = "/static/img/icons.svg";
const reduceMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export function icon(name, size, extra = "") {
  return `<svg class="s-icon s-icon--${size} ${extra}" aria-hidden="true" focusable="false"><use href="${SPRITE}#i-${name}"></use></svg>`;
}
const logo = (cls) => `<svg class="${cls}" viewBox="0 0 32 32" aria-hidden="true"><use href="${SPRITE}#i-logo"></use></svg>`;
const button = (label, attr, variant = "") =>
  `<button class="s-btn s-btn--hero ${variant}" type="button" ${attr}>${esc(label)}${icon("arrow", 20)}</button>`;

export function setTheme(theme) {
  document.body.classList.toggle("is-red", theme === "red");
  document.body.classList.toggle("is-green", theme === "green");
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = theme === "red" ? "#b4232c" : theme === "green" ? "#146c43" : "#f3f6fb";
}

export function setFootnote(text) {
  const el = document.getElementById("footnote-text");
  if (el) el.textContent = text;
}

// State changes dissolve (220 ms), as in the rest of Vigie.
export async function swap(stage, html, theme) {
  if (stage.dataset.filled && !reduceMotion()) {
    stage.classList.add("is-leaving");
    await new Promise((r) => setTimeout(r, 220));
  }
  setTheme(theme);
  stage.innerHTML = html;
  stage.dataset.filled = "1";
  stage.classList.remove("is-leaving");
  window.scrollTo({ top: 0 });
  const focus = stage.querySelector("[data-autofocus]");
  if (focus) focus.focus({ preventScroll: true });
}

// The five stages of the home page; each server step belongs to one of them.
const STAGES = ["Verdict memory", "Case file", "Blocklists", "AI analyst", "Safety rules"];
const STAGE_OF = {
  memory: 0, redirects: 1, urlscan: 1, domain: 1, signals: 1, official_site: 1, compare: 1, web_search: 1,
  reputation: 2, agent: 3, backup: 3, guardrails: 4,
};

function stageRail(current, label = "Investigation stages") {
  const items = STAGES.map((name, i) => {
    const state = i < current ? "is-done" : i === current ? "is-current" : "";
    return `<li class="s-rstage ${state}"${i === current ? ' aria-current="step"' : ""}><span class="s-stage__num">${String(i + 1).padStart(2, "0")}</span><span class="s-stage__name">${name}</span></li>`;
  }).join("");
  return `<ol class="s-stages" aria-label="${label}" data-current="${current}">${items}</ol>`;
}

// The filled part of the rail line follows the current stage (set through the CSSOM: the CSP forbids style attributes).
function paintRail(stage) {
  const rail = stage.querySelector(".s-stages");
  if (rail) rail.style.setProperty("--done", String(Number(rail.dataset.current) / 4));
}

// Investigation -----------------------------------------------------------------------------
export function renderInvestigation(stage, { host }) {
  const html = `
    <section class="s-hero s-inv" aria-labelledby="inv-title">
      <div class="s-hero__v" aria-hidden="true">${logo("")}</div>
      <div class="s-hero__intro">
        <span class="s-pill">${icon("scan", 16)}Investigation in progress</span>
        <h1 id="inv-title" class="s-h1" tabindex="-1" data-autofocus data-title>Who is <span class="s-h1__ai">behind</span><br>this link?</h1>
        <p class="s-promise">Vigie is investigating <span class="s-mono">${esc(host)}</span></p>
        <p class="s-problem" data-count>Starting the investigation…</p>
        <div data-rail>${stageRail(0)}</div>
      </div>
      <div class="s-hero__media"><div class="s-hero__zone" aria-hidden="true"></div><figure class="s-window" aria-live="polite" aria-busy="true">
        <div class="s-window__bar">${logo("s-window__logo")}<img class="s-window__controls" src="/static/img/window-controls.svg" width="76" height="12" alt=""></div>
        <div class="s-window__address"><div class="s-address">${icon("scan", 16, "s-icon--blue")}<span class="s-mono">${esc(host)}</span></div></div>
        <div class="s-window__body">
          <div class="s-investigation__head">${icon("scan", 26, "s-icon--blue")}<span class="s-investigation__title">Investigating…</span></div>
          <p class="s-investigation__sub">Checking the link you just clicked.</p>
          <div class="s-progress" role="progressbar" aria-label="Investigation progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="2"><span class="s-progress__done"></span></div>
          <ul class="s-checks" data-steps></ul>
        </div>
      </figure></div>
    </section>`;
  setFootnote("The page stays closed until the check is done.");
  const ready = swap(stage, html, "canvas");
  const steps = new Map();
  const queue = [];
  let lastShown = 0;
  let current = 0;

  // Steps that arrive in a burst still appear one after the other.
  const pump = () => {
    if (!queue.length) return;
    const wait = reduceMotion() ? 0 : Math.max(0, 120 - (performance.now() - lastShown));
    setTimeout(() => {
      const fn = queue.shift();
      if (fn) fn();
      lastShown = performance.now();
      pump();
    }, wait);
  };

  const update = () => {
    const done = [...steps.values()].filter((s) => s.status === "done").length;
    const total = Math.max(7, steps.size + 1);
    const pct = Math.min(92, Math.round((done / total) * 100)) || 2;
    const bar = stage.querySelector(".s-progress");
    if (!bar) return;
    bar.querySelector("span").style.width = pct + "%";
    bar.setAttribute("aria-valuenow", String(pct));
    stage.querySelector("[data-count]").textContent = done === 1 ? "1 check complete" : `${done} checks complete`;
    stage.querySelector("[data-rail]").innerHTML = stageRail(current);
    paintRail(stage);
    if (current >= 3) {
      const title = stage.querySelector("[data-title]");
      if (title && !title.dataset.late) {
        title.dataset.late = "1";
        title.innerHTML = 'Is this page <span class="s-h1__ai">really</span><br>what it claims?';
      }
    }
  };

  return {
    ready,
    step(data) {
      queue.push(() => {
        const list = stage.querySelector("[data-steps]");
        if (!list) return;
        let entry = steps.get(data.id);
        if (!entry) {
          const li = document.createElement("li");
          list.appendChild(li);
          entry = { li };
          steps.set(data.id, entry);
          // The window keeps the six latest checks so the screen never needs scrolling.
          while (list.children.length > 6) list.firstElementChild.remove();
        }
        entry.status = data.status;
        current = Math.max(current, STAGE_OF[data.tool] ?? 1);
        entry.li.className = data.status === "running" ? "is-active" : "";
        entry.li.innerHTML = `${icon(data.status === "running" ? "clock" : "check", 18, data.status === "running" ? "s-pulse" : "")}<span>${esc(data.label)}</span>`;
        update();
      });
      pump();
    },
    async finish() {
      await new Promise((resolve) => { queue.push(resolve); pump(); });
      const bar = stage.querySelector(".s-progress span");
      if (bar) bar.style.width = "100%";
      const win = stage.querySelector(".s-window");
      if (win) win.setAttribute("aria-busy", "false");
      if (!reduceMotion()) await new Promise((r) => setTimeout(r, 450));
    },
  };
}

// Evidence helpers ------------------------------------------------------------------------------
const fact = (verdict, title) => ((verdict.evidence || []).find((e) => e.title === title) || {}).detail || "";
const ageOf = (detail) => detail.replace(/^Registered /, "").replace(/, registrar .*$/, "");

// Red screens ---------------------------------------------------------------------------------
function redLayout({ pill, pillIcon, title, sub, actions, side }) {
  return `
    <section class="s-hero s-vscreen" aria-live="assertive">
      <div class="s-hero__v" aria-hidden="true">${logo("")}</div>
      <div class="s-hero__intro">
        <span class="s-pill s-pill--on-colour">${icon(pillIcon, 16)}${esc(pill)}</span>
        <h1 class="s-h1" tabindex="-1" data-autofocus data-title>${title}</h1>
        ${sub ? `<p class="s-promise">${sub}</p>` : ""}
        <div class="s-actions">${actions}</div>
      </div>
      ${side ? `<div class="s-verdict__side">${side}</div>` : ""}
    </section>`;
}

function comparison(verdict) {
  const brand = verdict.impersonated_brand;
  const official = verdict.official_domain;
  const age = ageOf(fact(verdict, "Domain registration"));
  const login = fact(verdict, "Login form");
  const rows = [];
  if (age) rows.push(["Domain created", `<span class="s-mono">${esc(age)}</span>`, ""]);
  rows.push(["Official site", "No", official ? "Yes, two sources agree" : ""]);
  if (login) rows.push(["Page asks for", esc(login.replace(/^Requests /, "")), ""]);
  const body = rows.map(([l, a, b]) => `<tr><th scope="row">${l}</th><td>${a}</td><td>${b}</td></tr>`).join("");
  return `
    <table class="s-vcompare">
      <thead><tr><td></td>
        <th scope="col"><span class="s-vcompare__bar"><small>This link</small><span class="s-mono">${esc(verdict.host)}</span></span></th>
        <th scope="col"><span class="s-vcompare__bar"><small>The real ${esc(brand)}</small><span class="s-mono">${esc(official)}</span></span></th>
      </tr></thead>
      <tbody>${body}</tbody>
    </table>`;
}

function factsList(verdict) {
  const items = (verdict.evidence || []).filter((e) => ["Blocklists", "Domain registration", "Login form", "Claimed identity"].includes(e.title));
  if (!items.length) return "";
  return `<ul class="s-vfacts">${items.map((e) => `<li><span>${esc(e.title)}</span><strong>${esc(e.detail)}</strong></li>`).join("")}</ul>`;
}

export function renderBlocked(stage, verdict, { onEvidence, onReport }) {
  const brand = verdict.impersonated_brand;
  const compare = brand && verdict.official_domain;
  const html = redLayout({
    pill: "Blocked by Vigie", pillIcon: "stop",
    title: brand ? `This is not<br>${esc(brand)}.` : "This link<br>stays closed.",
    sub: `<span class="s-mono">${esc(verdict.host)}</span> ${brand ? `pretends to be ${esc(brand)}.` : "is reported as dangerous."}`,
    actions: `${button("See the evidence", "data-evidence", "s-btn--white")}<button class="s-textlink" type="button" data-report>Report a mistake</button>`,
    side: compare ? comparison(verdict) : factsList(verdict),
  });
  setFootnote("This page remains blocked.");
  return swap(stage, html, "red").then(() => {
    stage.querySelector("[data-evidence]").addEventListener("click", onEvidence);
    bindReport(stage, onReport);
  });
}

export function renderUnknown(stage, verdict, { onRetry }) {
  const html = redLayout({
    pill: "Verification impossible", pillIcon: "alert",
    title: "This link<br>stays closed.",
    sub: "Vigie could not finish checking it.",
    actions: button("Check again", "data-retry", "s-btn--white"),
    side: `<p class="s-verdict__reason"><span>Reason</span>${esc(verdict.reason || "Unknown")}</p>`,
  });
  setFootnote("This page remains blocked.");
  return swap(stage, html, "red").then(() => stage.querySelector("[data-retry]").addEventListener("click", onRetry));
}

export function renderOffline(stage, { host, detail }, { onRetry }) {
  const html = redLayout({
    pill: "Server unreachable", pillIcon: "alert",
    title: "Vigie can’t<br>be reached.",
    sub: `<span class="s-mono">${esc(host)}</span> could not be checked, so it stays closed.`,
    actions: button("Try again", "data-retry", "s-btn--white"),
    side: `<p class="s-verdict__reason"><span>What to do</span>${esc(detail || "Check your internet connection, then try again.")}</p>`,
  });
  setFootnote("This page remains blocked.");
  return swap(stage, html, "red").then(() => stage.querySelector("[data-retry]").addEventListener("click", onRetry));
}

function bindReport(stage, onReport) {
  const el = stage.querySelector("[data-report]");
  if (!el || !onReport) return;
  el.addEventListener("click", async () => {
    el.disabled = true;
    let ok = false;
    try { ok = await onReport(); } catch { ok = false; }
    const note = document.createElement("p");
    note.className = "s-report-done";
    note.setAttribute("role", "status");
    note.textContent = ok ? "Thank you, a person will review this verdict." : "The report could not be sent, please try again later.";
    el.replaceWith(note);
  });
}

// Safe ----------------------------------------------------------------------------------------
const RING = 2 * Math.PI * 147;

// `chooser` (Vigie Desktop) receives a slot and { countdown(label), openNow(label) } and decides how the link opens.
export function renderSafe(stage, verdict, { openLabel = "Opening this page", onOpen, onSeeChecks, chooser }) {
  const dest = verdict.destination || {};
  const name = dest.name || verdict.host;
  const replay = openLabel.startsWith("Replay");
  const html = `
    <section class="s-hero s-vscreen" aria-live="assertive">
      <div class="s-hero__v" aria-hidden="true">${logo("")}</div>
      <div class="s-hero__intro">
        <span class="s-pill s-pill--on-colour">${icon("check", 16)}Verified by Vigie</span>
        <h1 class="s-h1" tabindex="-1" data-autofocus data-title>${dest.verified_brand ? `This is the<br>real ${esc(name)}.` : "This link<br>is safe."}</h1>
        <div class="s-destination">
          ${icon(dest.verified_brand ? "bank" : "browser", 30)}
          <div><strong>${esc(name)}</strong><span class="s-mono">${esc(verdict.host)}</span></div>
          <em>${verdict.from_memory ? "Already checked today" : "Verified destination"}</em>
        </div>
        <div class="s-actions">
          ${replay ? "" : button("Open now", "data-open-now", "s-btn--white")}
          <button class="s-textlink" type="button" data-checks>See the checks</button>
        </div>
      </div>
      <div class="s-verdict__side">
      <div class="s-countdown" role="timer" aria-live="off">
        <svg class="s-countdown__ring" viewBox="0 0 300 300" aria-hidden="true">
          <circle cx="150" cy="150" r="147" class="s-countdown__track"></circle>
          <circle cx="150" cy="150" r="147" class="s-countdown__arc" data-arc></circle>
        </svg>
        <p class="s-countdown__num"><b data-left>5</b><span data-unit>seconds</span></p>
        <p class="s-countdown__caption" data-caption>${replay ? esc(openLabel) : `Before ${esc(verdict.host)} opens`}</p>
      </div>
      <div class="s-chooser" data-choose hidden></div>
      </div>
    </section>`;
  setFootnote("Vigie investigated and you stay in control.");
  let timer = null;
  let cancelled = false;

  const paint = (left) => {
    const num = stage.querySelector("[data-left]");
    if (!num) return;
    num.textContent = String(left);
    stage.querySelector("[data-unit]").textContent = left === 0 ? (replay ? "seconds" : "opening") : left === 1 ? "second" : "seconds";
    stage.querySelector("[data-arc]").style.strokeDashoffset = String(RING * (1 - left / 5));
  };

  const caption = (text) => { const el = stage.querySelector("[data-caption]"); if (el) el.textContent = text; };
  const openNow = async (label) => {
    cancelled = true;
    clearInterval(timer);
    paint(0);
    if (!replay) caption(typeof label === "string" ? label : `Opening ${verdict.host}`);
    await onOpen();
  };
  const startCountdown = (label) => {
    if (label) caption(label);
    const now = stage.querySelector("[data-open-now]");
    if (now) now.hidden = false;
    let left = 5;
    timer = setInterval(async () => {
      if (cancelled) return;
      left -= 1;
      if (left > 0) { paint(left); return; }
      await openNow(label);
    }, 1000);
  };

  // The green screen counts down once per second for five seconds, then the link opens (C02).
  const ready = swap(stage, html, "green").then(() => {
    const arc = stage.querySelector("[data-arc]");
    arc.style.strokeDasharray = String(RING);
    arc.style.strokeDashoffset = "0";
    stage.querySelector("[data-checks]").addEventListener("click", () => { cancelled = true; clearInterval(timer); onSeeChecks(); });
    const now = stage.querySelector("[data-open-now]");
    if (now) now.addEventListener("click", () => openNow());
    if (chooser) {
      // Nothing opens until the user picks a browser, unless one was saved with "Always use this browser".
      if (now) now.hidden = true;
      caption("Choose a browser to open it");
      chooser(stage.querySelector("[data-choose]"), { countdown: startCountdown, openNow });
    } else startCountdown();
  });
  return { ready, stop() { cancelled = true; clearInterval(timer); } };
}

// Neutral screens: quota reached, link that cannot be checked -------------------------
export function renderNotice(stage, { iconName, title, text, host, actionLabel, onAction, footnote }) {
  const html = `
    <section class="s-hero s-notice" aria-live="assertive">
      <div class="s-hero__v" aria-hidden="true">${logo("")}</div>
      <div class="s-hero__intro">
        <span class="s-pill">${icon(iconName, 16)}The link stays closed</span>
        <h1 class="s-h1 s-h1--small" tabindex="-1" data-autofocus>${esc(title)}</h1>
        ${host ? `<p class="s-promise"><span class="s-mono">${esc(host)}</span></p>` : ""}
        <p class="s-problem">${esc(text)}</p>
        ${actionLabel ? `<div class="s-actions">${button(actionLabel, "data-action")}</div>` : ""}
      </div>
    </section>`;
  setFootnote(footnote || "The page stays closed until it can be checked.");
  return swap(stage, html, "canvas").then(() => {
    const action = stage.querySelector("[data-action]");
    if (action && onAction) action.addEventListener("click", onAction);
  });
}

// Evidence ------------------------------------------------------------------------------------
export function renderEvidence(stage, verdict, { onBack, backLabel, onReport }) {
  const safe = verdict.verdict === "safe";
  const items = (verdict.evidence || []).map((e) => `
      <li>${icon(e.icon || "check", 22, "s-icon--blue")}<div><strong>${esc(e.title)}</strong><span>${esc(e.detail)}</span></div></li>`).join("");
  const html = `
    <section class="s-hero s-evidence" aria-labelledby="ev-title">
      <div class="s-hero__v" aria-hidden="true">${logo("")}</div>
      <div class="s-hero__intro">
        <span class="s-pill s-pill--verdict ${safe ? "is-safe" : "is-blocked"}">${icon(safe ? "check" : "stop", 16)}${safe ? "Safe" : "Blocked"}</span>
        <h1 id="ev-title" class="s-h1" tabindex="-1" data-autofocus>${safe ? "The checks." : "The evidence."}</h1>
        <p class="s-promise"><span class="s-mono">${esc(verdict.host)}</span></p>
        <p class="s-problem">Every fact comes from a check Vigie ran on this exact link.</p>
        <div class="s-actions">
          <button class="s-btn s-btn--hero" type="button" data-back>${esc(backLabel || "Back to the verdict")}${icon("arrow", 20)}</button>
          ${onReport ? '<button class="s-textlink s-textlink--blue" type="button" data-report>Report a mistake</button>' : ""}
        </div>
      </div>
      <div class="s-hero__media"><div class="s-hero__zone" aria-hidden="true"></div><div class="s-window s-window--list">
        <ul class="s-evlist">${items || "<li>No check recorded.</li>"}</ul>
      </div></div>
    </section>`;
  setFootnote("A decision backed by visible evidence.");
  return swap(stage, html, "canvas").then(() => {
    stage.querySelector("[data-back]").addEventListener("click", onBack);
    bindReport(stage, onReport);
  });
}
