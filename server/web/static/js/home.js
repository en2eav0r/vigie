// Vigie Web home: one field, "Check this link", and three examples (W01).
const form = document.getElementById("check-form");
const input = document.getElementById("link");
const field = input.closest(".field");
const error = document.getElementById("link-error");

function problem(value) {
  const text = value.trim();
  if (!text) return "Paste a link to check.";
  if (/\s/.test(text)) return "A link cannot contain spaces.";
  if (/^(javascript|data|file|vbscript):/i.test(text)) return "Vigie only checks web links (http or https).";
  const withScheme = /^[a-z][a-z0-9+.-]*:\/\//i.test(text) ? text : "https://" + text;
  let url;
  try {
    url = new URL(withScheme);
  } catch {
    return "This does not look like a web address.";
  }
  if (!["http:", "https:"].includes(url.protocol)) return "Vigie only checks web links (http or https).";
  if (!url.hostname.includes(".") && !/^\[?[0-9a-f:.]+\]?$/i.test(url.hostname)) return "This does not look like a web address.";
  return "";
}

function showError(message) {
  error.textContent = message;
  error.hidden = !message;
  field.classList.toggle("has-error", Boolean(message));
  input.setAttribute("aria-invalid", message ? "true" : "false");
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const message = problem(input.value);
  showError(message);
  if (message) {
    input.focus();
    return;
  }
  location.href = "/go?url=" + encodeURIComponent(input.value.trim());
});

input.addEventListener("input", () => {
  if (!error.hidden) showError("");
});

if (new URLSearchParams(location.search).get("example") === "unavailable") {
  showError("The live phishing example is unavailable right now, so try another one.");
}
