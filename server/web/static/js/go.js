// Vigie Web journey: /go?url=<link>. The link opens in this tab only after a safe verdict (W02).
import {
  markTestMode, renderBlocked, renderEvidence, renderInvestigation, renderNotice, renderOffline, renderSafe, renderUnknown,
  streamInvestigation,
} from "./site-ui.js?v=20261014e";

const stage = document.getElementById("stage");
const params = new URLSearchParams(location.search);
const target = params.get("url") || "";
let verdict = null;
let replaying = false;   // a replay never opens the link

function storage(op, key, value) {
  try {
    if (op === "get") return localStorage.getItem(key);
    if (op === "set") localStorage.setItem(key, value);
    if (op === "del") localStorage.removeItem(key);
  } catch {
    return null;
  }
  return null;
}

async function clientToken(fresh = false) {
  if (!fresh) {
    const saved = storage("get", "vigie_token");
    if (saved) return saved;
  }
  const response = await fetch("/api/token", { method: "POST" });
  if (!response.ok) throw new Error(`token ${response.status}`);
  const { token } = await response.json();
  storage("set", "vigie_token", token);
  return token;
}

function hostOf(url) {
  try {
    return new URL(/^[a-z][a-z0-9+.-]*:\/\//i.test(url) ? url : "https://" + url).host;
  } catch {
    return url.slice(0, 80);
  }
}

function showVerdict() {
  if (verdict.verdict === "safe") {
    return renderSafe(stage, verdict, {
      openLabel: replaying ? "Replay: the link will not open" : "Opening this page",
      // The only place the destination is ever opened, and only after a safe verdict.
      onOpen: async () => { if (!replaying) location.replace(verdict.url); },
      onSeeChecks: showEvidence,
    });
  }
  if (verdict.verdict === "blocked") {
    return renderBlocked(stage, verdict, { onEvidence: showEvidence, onReport: report });
  }
  return renderUnknown(stage, verdict, { onRetry: run });
}

function showEvidence() {
  renderEvidence(stage, verdict, { onBack: showVerdict, onReport: report });
}

async function report() {
  const response = await fetch("/api/report", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url: verdict.url, verdict: verdict.verdict }),
  });
  return response.ok;
}

async function run(retried = false) {
  verdict = null;
  if (!target) {
    renderNotice(stage, {
      iconName: "link", title: "No link to check",
      text: "This page checks a link before it opens, so paste one on the check page to start.",
      actionLabel: "Check a link", onAction: () => { location.href = "/check"; },
    });
    return;
  }
  const view = renderInvestigation(stage, { host: hostOf(target) });
  await view.ready;
  let token;
  try {
    token = await clientToken();
  } catch {
    await renderOffline(stage, { host: hostOf(target) }, { onRetry: () => run() });
    return;
  }
  try {
    await streamInvestigation({
      endpoint: "/investigate",
      url: target,
      headers: { "X-Vigie-Token": token },
      onEvent: async (event, data) => {
        if (event === "start" && data.test_agent) markTestMode();
        else if (event === "step") view.step(data);
        else if (event === "verdict") {
          verdict = data;
          await view.finish();
          await showVerdict();
        } else if (event === "invalid") {
          await renderNotice(stage, {
            iconName: "alert", title: "This link can't be checked", host: target.slice(0, 200), text: data.message,
            actionLabel: "Check another link", onAction: () => { location.href = "/check"; },
          });
        } else if (event === "limit") {
          await renderNotice(stage, {
            iconName: "clock", title: "Daily limit reached", host: hostOf(target), text: data.message,
            actionLabel: "Back to the home page", onAction: () => { location.href = "/"; },
          });
        } else if (event === "token") {
          storage("del", "vigie_token");
          if (!retried) { await clientToken(true); run(true); }
        }
      },
    });
  } catch (error) {
    if (!verdict) await renderOffline(stage, { host: hostOf(target) }, { onRetry: () => run() });
  }
}

// Replay mode (spec 12.3): plays back an investigation recorded beforehand, labelled as such, and never
// opens the link. Used only if the live demo fails on the day.
async function replay(name) {
  replaying = true;
  const response = await fetch(`/api/replays/${encodeURIComponent(name)}`);
  if (!response.ok) {
    renderNotice(stage, { iconName: "alert", title: "No replay with this name",
      text: "This replay does not exist on the server.", actionLabel: "Check a link", onAction: () => { location.href = "/check"; } });
    return;
  }
  const data = await response.json();
  const banner = document.createElement("p");
  banner.className = "test-banner";
  banner.setAttribute("role", "note");
  banner.textContent = `Replay of an investigation recorded on ${data.recorded_at.slice(0, 10)}. This is not a live check, and the link will not open.`;
  document.body.prepend(banner);
  const view = renderInvestigation(stage, { host: data.host });
  await view.ready;
  let last = 0;
  for (const item of data.events) {
    await new Promise((r) => setTimeout(r, Math.min(4000, Math.max(0, (item.t - last) * 1000))));
    last = item.t;
    if (item.event === "step") view.step(item.data);
    if (item.event === "verdict") {
      verdict = item.data;
      await view.finish();
      await showVerdict();
    }
  }
}

const replayName = location.pathname.startsWith("/replay/") ? location.pathname.slice(8) : "";
if (replayName) replay(replayName);
else run();
