// Vigie journey screens, shared by Vigie Web and Vigie Desktop.
// Every screen is rendered from server data; nothing here can open a link on its own.

const SPRITE = "/static/img/icons.svg";

export function icon(name, size = 24, extra = "") {
  return `<svg class="icon icon-${size} ${extra}" aria-hidden="true" focusable="false"><use href="${SPRITE}#i-${name}"></use></svg>`;
}

export function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const reduceMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export function setTheme(theme) {
  document.body.classList.toggle("is-red", theme === "red");
  document.body.classList.toggle("is-green", theme === "green");
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = theme === "red" ? "#b4232c" : theme === "green" ? "#146c43" : "#f3f6fb";
}

// Shown whenever the server runs the scripted test agent: those verdicts do not come from the AI.
export function markTestMode() {
  if (document.querySelector(".test-banner")) return;
  const banner = document.createElement("p");
  banner.className = "test-banner";
  banner.setAttribute("role", "note");
  banner.textContent = "Test mode: no AI model is connected. Verdicts come from a scripted test agent, not from Vigie's AI.";
  document.body.prepend(banner);
}

export function setFootnote(text) {
  const el = document.getElementById("footnote-text");
  if (el) el.textContent = text;
}

// Swap the stage content with a short dissolve (state transitions dissolve, DESIGN.md).
export async function swap(stage, html, theme) {
  if (stage.dataset.filled && !reduceMotion()) {
    stage.classList.add("is-leaving");
    await new Promise((r) => setTimeout(r, 220));
  }
  if (theme) setTheme(theme);
  stage.innerHTML = html;
  stage.dataset.filled = "1";
  stage.classList.remove("is-leaving");
  const focus = stage.querySelector("[data-autofocus]");
  if (focus) focus.focus({ preventScroll: true });
}

const ASIDE_INVESTIGATION = `
  <aside class="aside" aria-hidden="true">
    <svg class="logo" viewBox="0 0 32 32"><use href="${SPRITE}#i-logo"></use></svg>
    <h2>One link.<br>A closer look.</h2>
    <p>The destination stays closed while Vigie investigates its identity.</p>
  </aside>`;

// Investigation ---------------------------------------------------------------
export function renderInvestigation(stage, { host, lede }) {
  const html = `
    <div class="split">
      <section class="panel" aria-live="polite" aria-busy="true">
        <span class="pill">${icon("scan", 16)}Investigation in progress</span>
        <div class="title-row">${icon("scan", 28, "blue spin")}<h1 tabindex="-1" data-autofocus>Investigating…</h1></div>
        ${lede ? `<p class="lede">${esc(lede)}</p>` : ""}
        <p class="target">${esc(host)}</p>
        <div class="progress">
          <div class="bar" role="progressbar" aria-label="Investigation progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="2"><span></span></div>
          <p data-count>Starting the investigation…</p>
        </div>
        <ul class="steps" data-steps></ul>
      </section>
      ${ASIDE_INVESTIGATION}
    </div>`;
  setFootnote("The page stays closed until the check is done.");
  const ready = swap(stage, html, "canvas");
  const steps = new Map();
  const queue = [];
  let shown = 0;
  let lastShown = 0;

  // Steps that arrive in a burst (verdict memory, fast tools) still appear one after the other.
  const pump = () => {
    if (!queue.length) return;
    const now = performance.now();
    const wait = reduceMotion() ? 0 : Math.max(0, 120 - (now - lastShown));
    setTimeout(() => {
      const fn = queue.shift();
      if (fn) fn();
      lastShown = performance.now();
      pump();
    }, wait);
  };

  const update = () => {
    const list = stage.querySelector("[data-steps]");
    if (!list) return;
    const done = [...steps.values()].filter((s) => s.status === "done").length;
    const total = Math.max(7, steps.size + 1);
    const pct = Math.min(92, Math.round((done / total) * 100)) || 2;
    const bar = stage.querySelector(".bar");
    bar.querySelector("span").style.width = pct + "%";
    bar.setAttribute("aria-valuenow", String(pct));
    stage.querySelector("[data-count]").textContent = done === 1 ? "1 check complete" : `${done} checks complete`;
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
          shown += 1;
        }
        entry.status = data.status;
        entry.li.className = data.status === "running" ? "is-running" : "";
        entry.li.innerHTML = `${icon(data.status === "running" ? "clock" : "check", 20)}<span>${esc(data.label)}</span>`;
        update();
      });
      pump();
    },
    async finish() {
      await new Promise((resolve) => { queue.push(resolve); pump(); });
      const bar = stage.querySelector(".bar span");
      if (bar) bar.style.width = "100%";
      const panel = stage.querySelector(".panel");
      if (panel) panel.setAttribute("aria-busy", "false");
      if (!reduceMotion()) await new Promise((r) => setTimeout(r, 450));
    },
  };
}

// Safe ------------------------------------------------------------------------------
export function renderSafe(stage, verdict, { openLabel, onOpen, onSeeChecks, chooser }) {
  const dest = verdict.destination || {};
  const name = dest.name || verdict.host;
  const html = `
    <section class="verdict is-safe" aria-live="assertive">
      <div class="ring">${icon("check", 32)}</div>
      <h1 tabindex="-1" data-autofocus data-title>This link is safe</h1>
      <p class="intro">The investigation is complete. Your destination is verified.</p>
      <div class="sheet destination">
        <div class="who">${icon(dest.verified_brand ? "bank" : "browser", 36)}
          <div><strong>${esc(name)}</strong><span>${esc(verdict.host)}</span></div>
        </div>
        <div class="cleared"><b>Verified destination</b>
          <span>${esc(verdict.from_memory ? "Already investigated today. This link was cleared by Vigie." : "Investigation complete. This link was cleared by Vigie.")}</span>
        </div>
        <div data-open></div>
      </div>
      <div><button class="textlink is-white" type="button" data-checks>See the checks</button></div>
    </section>`;
  setFootnote("Vigie investigates. You stay in control.");
  let timer = null;
  let cancelled = false;

  const paint = (left, label) => {
    const slot = stage.querySelector("[data-open]");
    if (!slot) return;
    slot.innerHTML = `
      <div class="countdown" role="timer" aria-live="off">
        <div class="count${left === 0 ? " is-done" : ""}">${left > 0 ? `<b>${left}</b><small>${left === 1 ? "second" : "seconds"}</small>` : icon("check", 28)}</div>
        <div><strong>${esc(left > 0 ? label : label.replace(/^Opening/, "Opening now").replace("now this page", "this page now"))}</strong><span>${label.startsWith("Replay") ? "A replay never opens the link." : left > 0 ? "Your verified link opens automatically." : "Your verified link is opening."}</span></div>
      </div>`;
  };

  const openNow = async (label) => {
    paint(0, label);
    const title = stage.querySelector("[data-title]");
    if (title) title.textContent = "Ready to continue";
    await onOpen();
  };

  // The green screen counts down once per second for five seconds, then the link opens (C02).
  const startCountdown = (label) => {
    let left = 5;
    paint(left, label);
    timer = setInterval(async () => {
      if (cancelled) return;
      left -= 1;
      if (left > 0) {
        paint(left, label);
        return;
      }
      clearInterval(timer);
      await openNow(label);
    }, 1000);
  };

  const ready = swap(stage, html, "green").then(() => {
    stage.querySelector("[data-checks]").addEventListener("click", () => { cancelled = true; clearInterval(timer); onSeeChecks(); });
    if (chooser) chooser(stage.querySelector("[data-open]"), { countdown: startCountdown, openNow });
    else startCountdown(openLabel);
  });
  return { ready, stop() { cancelled = true; clearInterval(timer); } };
}

// Red screens: blocked, unknown, server unreachable ------------------------------------
function redScreen({ host, kicker, hostLine, why, reason, actions }) {
  return `
    <section class="verdict" aria-live="assertive">
      ${icon("stop", 72, "stop")}
      <h1 tabindex="-1" data-autofocus>Unable to open<br>this page</h1>
      <div class="urlbar">${icon("link", 22)}<span>${esc(host)}</span></div>
      <div class="sheet">
        <p class="kicker">${esc(kicker)}</p>
        ${hostLine ? `<p class="host">${esc(host)}</p>` : ""}
        <p class="why">${esc(why)}</p>
        ${reason ? `<p class="reason">${esc(reason)}</p>` : ""}
        <div class="actions">${actions}</div>
      </div>
    </section>`;
}

export function renderBlocked(stage, verdict, { onEvidence, onReport }) {
  const html = redScreen({
    host: verdict.host,
    kicker: "Blocked destination",
    hostLine: true,
    why: verdict.explanation,
    actions: `<button class="textlink" type="button" data-evidence>${icon("file", 20)}See the evidence</button>
              <button class="textlink is-quiet" type="button" data-report>Report a mistake</button>`,
  });
  setFootnote("This page remains blocked.");
  return swap(stage, html, "red").then(() => {
    stage.querySelector("[data-evidence]").addEventListener("click", onEvidence);
    bindReport(stage, onReport);
  });
}

export function renderUnknown(stage, verdict, { onRetry }) {
  const html = redScreen({
    host: verdict.host,
    kicker: "Verification impossible",
    hostLine: false,
    why: "Vigie could not finish checking this link, so it stays closed.",
    reason: `Reason: ${verdict.reason || "Unknown"}`,
    actions: `<button class="textlink" type="button" data-retry>${icon("scan", 20)}Check again</button>`,
  });
  setFootnote("This page remains blocked.");
  return swap(stage, html, "red").then(() => stage.querySelector("[data-retry]").addEventListener("click", onRetry));
}

export function renderOffline(stage, { host, detail }, { onRetry }) {
  const html = redScreen({
    host,
    kicker: "Server unreachable",
    hostLine: false,
    why: "Vigie's server cannot be reached, so this link could not be checked. It stays closed.",
    reason: detail || "Check your internet connection, then try again.",
    actions: `<button class="textlink" type="button" data-retry>${icon("scan", 20)}Try again</button>`,
  });
  setFootnote("This page remains blocked.");
  return swap(stage, html, "red").then(() => stage.querySelector("[data-retry]").addEventListener("click", onRetry));
}

function bindReport(stage, onReport) {
  const button = stage.querySelector("[data-report]");
  if (!button || !onReport) return;
  button.addEventListener("click", async () => {
    button.disabled = true;
    let ok = false;
    try { ok = await onReport(); } catch { ok = false; }
    const note = document.createElement("p");
    note.className = "report-done";
    note.setAttribute("role", "status");
    note.textContent = ok ? "Thank you. A person will review this verdict." : "The report could not be sent. Try again later.";
    button.replaceWith(note);
  });
}

// Neutral screens: quota reached, link that cannot be checked -------------------------
export function renderNotice(stage, { iconName, title, text, host, actionLabel, onAction, footnote }) {
  const html = `
    <div class="split">
      <section class="panel" aria-live="assertive">
        ${icon(iconName, 48, "notice-icon")}
        <h1 tabindex="-1" data-autofocus>${esc(title)}</h1>
        ${host ? `<p class="target">${esc(host)}</p>` : ""}
        <p class="lede">${esc(text)}</p>
        ${actionLabel ? `<button class="btn is-inline" type="button" data-action><span class="label">${esc(actionLabel)}</span>${icon("arrow", 20)}</button>` : ""}
      </section>
      ${ASIDE_INVESTIGATION}
    </div>`;
  setFootnote(footnote || "The page stays closed until it can be checked.");
  return swap(stage, html, "canvas").then(() => {
    const action = stage.querySelector("[data-action]");
    if (action && onAction) action.addEventListener("click", onAction);
  });
}

// Evidence ------------------------------------------------------------------------------
export function renderEvidence(stage, verdict, { onBack, backLabel, onReport }) {
  const safe = verdict.verdict === "safe";
  const items = (verdict.evidence || []).map((e) => `
      <li>${icon(e.icon || "check", 22)}<div><strong>${esc(e.title)}</strong><span>${esc(e.detail)}</span></div></li>`).join("");
  const html = `
    <div class="split">
      <section class="panel">
        <h1 tabindex="-1" data-autofocus>${safe ? "The checks" : "The evidence"}</h1>
        <p class="target">${esc(verdict.host)}</p>
        <ul class="evidence">${items || "<li>No check recorded.</li>"}</ul>
        <div class="actions sheet-actions">
          <button class="textlink is-blue" type="button" data-back>${icon("back", 20)}${esc(backLabel || "Back to the verdict")}</button>
          ${onReport ? `<button class="textlink is-quiet" type="button" data-report>Report a mistake</button>` : ""}
        </div>
      </section>
      <aside class="aside" aria-hidden="true">
        <svg class="logo" viewBox="0 0 32 32"><use href="${SPRITE}#i-logo"></use></svg>
        <h2>A verdict you can understand.</h2>
        <p>See the checks behind the decision, in plain language.</p>
      </aside>
    </div>`;
  setFootnote("A decision backed by visible evidence.");
  return swap(stage, html, "canvas").then(() => {
    stage.querySelector("[data-back]").addEventListener("click", onBack);
    bindReport(stage, onReport);
  });
}

// Streaming client for POST /investigate (server-sent events over fetch) ----------------
export async function streamInvestigation({ endpoint, url, headers, onEvent, signal }) {
  const response = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream", ...headers },
    body: JSON.stringify({ url }),
    signal,
  });
  if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let ended = false;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let index;
    while ((index = buffer.indexOf("\n\n")) >= 0) {
      const chunk = buffer.slice(0, index);
      buffer = buffer.slice(index + 2);
      let event = "message";
      let data = "";
      for (const line of chunk.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      if (!data) continue;
      const payload = JSON.parse(data);
      if (["verdict", "limit", "invalid", "token"].includes(event)) ended = true;
      await onEvent(event, payload);
    }
  }
  if (!ended) throw new Error("The connection closed before the verdict.");
}
