// Vigie Desktop: receives clicked links from Windows, shows the investigation and hands safe links to a browser.
// The journey screens are the site's own (site-ui.js), so the app and the site look the same.
import {
  esc, icon, markTestMode, renderBlocked, renderEvidence, renderInvestigation, renderNotice, renderOffline, renderSafe,
  renderUnknown, setFootnote, swap,
} from "/static/js/site-ui.js";

const stage = document.getElementById("stage");
const address = document.getElementById("address");
const addressInput = document.getElementById("address-input");
const menu = document.getElementById("menu");
const menuButton = document.getElementById("menu-button");

let api = null;
let state = {};
let current = null;      // { url, view, verdict, safeView }
let journey = 0;         // ignores events from an investigation the user has left

const hostOf = (url) => {
  try { return new URL(/^[a-z][a-z0-9+.-]*:\/\//i.test(url) ? url : "https://" + url).host; } catch { return url.slice(0, 80); }
};
const logo = `<svg viewBox="0 0 32 32" aria-hidden="true"><use href="/static/img/icons.svg#i-logo"></use></svg>`;

function setAddress(text, busy = false) {
  addressInput.value = text;
  address.classList.toggle("is-busy", busy);
}

const checkCard = (hint) => `
  <div class="s-hero__media"><div class="s-hero__zone" aria-hidden="true"></div>
    <form class="s-window s-form" data-paste novalidate>
      <div class="s-form__head">${icon("scan", 26, "s-icon--blue")}<h2 class="s-investigation__title">Check a link</h2></div>
      <label class="s-form__label" for="paste">Link to investigate</label>
      <div class="s-field">${icon("link", 22)}<input id="paste" type="text" inputmode="url" spellcheck="false" autocomplete="off" placeholder="Paste a link"></div>
      <button class="s-btn s-btn--hero s-btn--block" type="submit">Check this link${icon("arrow", 20)}</button>
      <p class="d-hint">${hint}</p>
    </form>
  </div>`;

// Home: default-browser setup (D02, D06) and "Paste a link to check" (D05) ----------------
async function home({ firstRun = false } = {}) {
  journey += 1;
  current = null;
  setAddress("");
  const status = await api.default_status();
  state = { ...state, ...status };
  const statusLine = state.isDefault
    ? `<p class="d-status">${icon("check", 20)}Vigie is your default browser, so clicked links come here first.</p>`
    : state.resetWarning
      ? `<p class="d-status is-warning">${icon("alert", 20)}Windows changed your default browser, so links no longer reach Vigie.</p>`
      : "";
  const html = `
    <section class="s-hero" aria-labelledby="home-title">
      <div class="s-hero__v" aria-hidden="true">${logo}</div>
      <div class="s-hero__intro">
        <span class="s-pill">${icon("desktop", 16)}Vigie for Windows</span>
        <h1 id="home-title" class="s-h1" tabindex="-1" data-autofocus>${state.isDefault
          ? 'Every link you<br>click is <span class="s-h1__ai">checked</span>.'
          : 'One setting and<br>every link is <span class="s-h1__ai">checked</span>.'}</h1>
        <p class="s-promise">Links clicked in Outlook, WhatsApp or a document reach Vigie first, and safe links open in your usual browser.</p>
        ${statusLine}
        ${state.isDefault ? "" : `
        <div class="s-actions"><button class="s-btn s-btn--hero" type="button" data-settings>Set Vigie as default browser${icon("arrow", 20)}</button></div>
        <ol class="d-steps" data-steps hidden>
          <li><span>01</span><span>Windows Settings opens on <b>Vigie</b>.</span></li>
          <li><span>02</span><span>Select <b>Set default</b> at the top, or set <b>HTTP</b> and <b>HTTPS</b> to Vigie.</span></li>
          <li><span>03</span><span>Come back here and this page confirms when it worked.</span></li>
        </ol>`}
      </div>
      ${checkCard("Works even if Vigie is not your default browser.")}
    </section>`;
  setFootnote("Choose your usual browser once and Vigie takes care of the checks.");
  await swap(stage, html, "canvas");
  const settingsButton = stage.querySelector("[data-settings]");
  if (settingsButton) {
    const openSettings = async () => {
      stage.querySelector("[data-steps]").hidden = false;
      await api.open_default_settings();
    };
    settingsButton.addEventListener("click", openSettings);
    // D02: right after installation, open the Windows page and show which option to pick.
    if (firstRun) setTimeout(openSettings, 1200);
  }
  stage.querySelector("[data-paste]").addEventListener("submit", (event) => {
    event.preventDefault();
    const value = stage.querySelector("#paste").value.trim();
    if (value) check(value);
  });
}

// Re-check the default browser when the user comes back from Windows Settings.
window.addEventListener("focus", async () => {
  if (!current && api && stage.querySelector("[data-paste]") && !stage.querySelector("[data-server]")) {
    const status = await api.default_status();
    if (status.isDefault !== state.isDefault) home();
  }
});

// Investigation ----------------------------------------------------------------------------
async function check(url) {
  journey += 1;
  const mine = journey;
  menu.hidden = true;
  setAddress(hostOf(url), true);
  const view = renderInvestigation(stage, { host: hostOf(url) });
  current = { url, view, verdict: null };
  await view.ready;
  if (mine !== journey) return;
  api.check(url);
}

window.vigie = {
  check,
  home,
  async onEvent(event, data) {
    if (!current || current.verdict) return;
    const { view } = current;
    if (event === "start") { if (data.test_agent) markTestMode(); return; }
    if (event === "step") { view.step(data); return; }
    address.classList.remove("is-busy");
    if (event === "verdict") {
      current.verdict = data;
      setAddress(data.host || hostOf(current.url));
      await view.finish();
      showVerdict();
    } else if (event === "offline") {
      current.verdict = { verdict: "offline" };
      renderOffline(stage, { host: data.host, detail: data.detail }, { onRetry: () => check(current.url) });
    } else if (event === "limit") {
      current.verdict = { verdict: "limit" };
      renderNotice(stage, { iconName: "clock", title: "Daily limit reached", host: hostOf(current.url),
        text: data.message, actionLabel: "Back to Vigie", onAction: home });
    } else if (event === "invalid") {
      current.verdict = { verdict: "invalid" };
      renderNotice(stage, { iconName: "alert", title: "This link can't be checked", host: current.url.slice(0, 200),
        text: data.message, actionLabel: "Back to Vigie", onAction: home });
    }
  },
};

function showVerdict() {
  const verdict = current.verdict;
  if (verdict.verdict === "safe") {
    current.safeView = renderSafe(stage, verdict, {
      onSeeChecks: showEvidence,
      onOpen: () => openSafe(verdict),
      chooser: (slot, controls) => chooseBrowser(slot, controls),
    });
  } else if (verdict.verdict === "blocked") {
    renderBlocked(stage, verdict, { onEvidence: showEvidence, onReport: () => api.report(verdict.url, verdict.verdict) });
  } else {
    renderUnknown(stage, verdict, { onRetry: () => check(current.url) });
  }
}

function showEvidence() {
  const verdict = current.verdict;
  renderEvidence(stage, verdict, {
    onBack: showVerdict,
    onReport: () => api.report(verdict.url, verdict.verdict),
    backLabel: verdict.verdict === "safe" ? "Back to the verdict" : "Back to the blocked page",
  });
}

// D04: a safe link opens in the browser chosen by the user, with an "always use this browser" option.
let choice = { id: null, always: false };

async function chooseBrowser(slot, { countdown, openNow }) {
  const saved = (await api.ready()).browser;
  if (saved) {
    choice = { id: saved.id, always: false };
    countdown(`Opening in ${saved.name}`);
    return;
  }
  const list = await api.list_browsers();
  slot.hidden = false;
  if (!list.length) {
    slot.innerHTML = `<p class="d-hint is-error">No browser was found on this computer.</p>`;
    return;
  }
  slot.innerHTML = `
    <p>Open this link with</p>
    <ul>${list.map((b) => `<li><button type="button" data-id="${esc(b.id)}">${icon("browser", 20)}${esc(b.name)}</button></li>`).join("")}</ul>
    <label><input type="checkbox" data-always checked>Always use this browser</label>`;
  slot.querySelectorAll("[data-id]").forEach((button) => button.addEventListener("click", () => {
    choice = { id: button.dataset.id, always: slot.querySelector("[data-always]").checked };
    const name = list.find((b) => b.id === choice.id)?.name || "your browser";
    slot.hidden = true;
    openNow(`Opening in ${name}`);
  }));
}

async function openSafe(verdict) {
  const result = await api.open_link(verdict.url, choice.id, choice.always);
  if (!result.ok) {
    const slot = stage.querySelector("[data-choose]");
    if (slot) { slot.hidden = false; slot.insertAdjacentHTML("beforeend", `<p class="d-hint is-error">${esc(result.error)}</p>`); }
    return;
  }
  setTimeout(() => { if (current && current.verdict === verdict) home(); }, 2500);
}

// Settings (C07, D04) -----------------------------------------------------------------------
async function settings() {
  journey += 1;
  current = null;
  setAddress("Vigie settings");
  const info = await api.ready();
  const html = `
    <section class="s-hero" aria-labelledby="settings-title">
      <div class="s-hero__v" aria-hidden="true">${logo}</div>
      <div class="s-hero__intro">
        <span class="s-pill">${icon("desktop", 16)}Vigie ${esc(info.version)}</span>
        <h1 id="settings-title" class="s-h1" tabindex="-1" data-autofocus>Your <span class="s-h1__ai">rules</span>,<br>Vigie’s checks.</h1>
        <p class="s-problem">An organisation can point Vigie at its own server, and you choose the browser for safe links.</p>
      </div>
      <div class="s-hero__media"><div class="s-hero__zone" aria-hidden="true"></div>
        <div class="s-window d-settings">
          <div class="d-setting">
            <p>Vigie server</p>
            <form data-server novalidate>
              <div class="s-field">${icon("link", 20)}<input id="server" type="text" spellcheck="false" value="${esc(info.server)}" aria-label="Vigie server"></div>
              <button class="s-btn s-btn--hero d-save" type="submit">Save</button>
            </form>
            <p class="d-hint" data-server-hint>Use an https:// address.</p>
          </div>
          <div class="d-setting">
            <p>Browser for safe links</p>
            <div class="d-setting__row"><span>${info.browser ? esc(info.browser.name) + ", always" : "Ask each time"}</span>
              ${info.browser ? `<button class="d-ghost" type="button" data-forget>Ask each time</button>` : ""}</div>
          </div>
          <div class="d-setting">
            <p>Default browser</p>
            <div class="d-setting__row"><span>${info.isDefault ? "Vigie receives your clicked links." : "Vigie is not your default browser."}</span>
              <button class="d-ghost" type="button" data-defaults>Open default app settings</button></div>
          </div>
        </div>
      </div>
    </section>`;
  setFootnote("Vigie investigates and you stay in control.");
  await swap(stage, html, "canvas");
  stage.querySelector("[data-server]").addEventListener("submit", async (event) => {
    event.preventDefault();
    const hint = stage.querySelector("[data-server-hint]");
    const result = await api.save_server(stage.querySelector("#server").value);
    hint.className = "d-hint " + (result.ok && result.reachable ? "is-ok" : "is-error");
    hint.textContent = !result.ok ? result.error
      : result.reachable ? "Saved, and the server answers." : "Saved, but the server does not answer yet.";
  });
  stage.querySelector("[data-forget]")?.addEventListener("click", async () => { await api.forget_browser(); settings(); });
  stage.querySelector("[data-defaults]").addEventListener("click", () => api.open_default_settings());
}

async function about() {
  journey += 1;
  current = null;
  const info = await api.ready();
  setAddress("About Vigie");
  renderNotice(stage, {
    iconName: "eye", title: "About Vigie",
    text: `Vigie ${info.version}, an AI agent that investigates every link before it opens, so a safe link opens in your browser and a blocked or unverifiable link stays closed.`,
    actionLabel: "Check a link", onAction: home, footnote: "Vigie investigates and you stay in control.",
  });
}

// Chrome: address bar, back, menu, window controls --------------------------------------
address.addEventListener("submit", (event) => {
  event.preventDefault();
  const value = addressInput.value.trim();
  if (value) check(value);
});
addressInput.addEventListener("focus", () => addressInput.select());
document.getElementById("back").addEventListener("click", () => {
  current?.safeView?.stop();
  home();
});
menuButton.addEventListener("click", () => {
  menu.hidden = !menu.hidden;
  menuButton.setAttribute("aria-expanded", String(!menu.hidden));
});
menu.addEventListener("click", (event) => {
  const target = event.target.closest("[data-go]");
  if (!target) return;
  menu.hidden = true;
  current?.safeView?.stop();
  ({ home, settings, about })[target.dataset.go]();
});
document.addEventListener("click", (event) => {
  if (!menu.hidden && !event.target.closest("#menu, #menu-button")) menu.hidden = true;
});
document.querySelectorAll("[data-win]").forEach((button) => {
  button.addEventListener("click", () => api[button.dataset.win]());
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") menu.hidden = true;
  if ((event.ctrlKey && event.key.toLowerCase() === "l") || event.key === "F6") {
    event.preventDefault();
    addressInput.focus();
  }
});

// Start ------------------------------------------------------------------------------------
async function start() {
  api = window.pywebview.api;
  state = await api.ready();
  if (state.pending) check(state.pending);
  else home({ firstRun: state.firstRun });
}

if (window.pywebview && window.pywebview.api && window.pywebview.api.ready) start();
else window.addEventListener("pywebviewready", start, { once: true });
