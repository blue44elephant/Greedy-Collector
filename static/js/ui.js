import {ApiError} from "./api.js";
export const byId = id => document.getElementById(id);
export const present = value => value == null || value === "" ? "Not available" : String(value);
export function text(id, value) { byId(id).textContent = present(value); }
export function element(tag, value, className) {
  const node = document.createElement(tag);
  if (value !== undefined) node.textContent = present(value);
  if (className) node.className = className;
  return node;
}
export function dateText(value) {
  if (!value) return "Not available";
  const normalized = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value}Z`;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? "Not available" : date.toISOString().replace("T", " ").replace(/\.\d+Z$/, " UTC");
}
export function shortValue(value) {
  const full = present(value);
  const short = full.length > 23 ? `${full.slice(0, 10)}…${full.slice(-8)}` : full;
  const node = element("span", short, "short-value");
  node.title = full; node.tabIndex = 0; node.setAttribute("aria-label", full);
  node.addEventListener("focus", () => { node.textContent = full; });
  node.addEventListener("blur", () => { node.textContent = short; });
  return node;
}
export class UserError extends Error {}
export async function run(scope, operation, pending = "Working…") {
  if (scope.dataset.busy === "true") return;
  scope.dataset.busy = "true";
  const controls = [...scope.querySelectorAll("button,input,select,textarea")].map(node => [node, node.disabled]);
  controls.forEach(([node]) => { node.disabled = true; });
  let message = scope.querySelector(":scope > .operation-status");
  if (!message) { message = element("p", undefined, "operation-status"); scope.append(message); }
  message.setAttribute("role", "status"); message.textContent = pending; message.className = "operation-status";
  scope.setAttribute("aria-busy", "true");
  try { await operation(); message.textContent = "Complete."; }
  catch (error) {
    message.className = "operation-status error";
    message.setAttribute("role", "alert");
    message.textContent = error instanceof ApiError || error instanceof UserError ? error.message : "The operation could not be completed. Please try again.";
  } finally {
    controls.forEach(([node, disabled]) => { node.disabled = disabled; });
    scope.dataset.busy = "false"; scope.setAttribute("aria-busy", "false");
  }
}
export function action(label, handler, className = "secondary") {
  const button = element("button", label, className); button.type = "button";
  button.addEventListener("click", () => run(button.closest(".panel") || button.parentElement, handler));
  return button;
}
export function panel(title, note) {
  const node = element("section", undefined, "panel");
  node.append(element("h2", title));
  if (note) node.append(element("p", note, "muted small"));
  return node;
}
export function table(headers, rows, empty = "No records are available.") {
  if (!rows.length) return element("p", empty, "empty");
  const wrap = element("div", undefined, "table-scroll"); wrap.tabIndex = 0;
  const grid = element("table"); const head = element("thead"); const tr = element("tr");
  headers.forEach(label => { const th = element("th", label); th.scope = "col"; tr.append(th); });
  head.append(tr); grid.append(head); const body = element("tbody");
  for (const values of rows) {
    const row = element("tr");
    for (const value of values) { const td = element("td"); if (value instanceof Node) td.append(value); else td.textContent = present(value); row.append(td); }
    body.append(row);
  }
  grid.append(body); wrap.append(grid); return wrap;
}
export function details(title, value) {
  const node = element("details"); node.append(element("summary", title), element("pre", JSON.stringify(value, null, 2))); return node;
}
export function fields(definitions) {
  const fragment = document.createDocumentFragment();
  for (const def of definitions) {
    const wrap = element("label", undefined, "form-field"); wrap.append(element("span", def.label));
    const input = element(def.options ? "select" : def.type === "textarea" ? "textarea" : "input");
    input.name = def.name;
    if (def.options) for (const option of def.options) {
      const [value, label] = Array.isArray(option) ? option : [option, option];
      const node = element("option", label); node.value = value; input.append(node);
    }
    else if (def.type !== "textarea") input.type = def.type || "text";
    input.required = Boolean(def.required);
    if (def.type === "checkbox") input.checked = Boolean(def.value);
    else if (def.value != null) input.value = def.value;
    for (const key of ["min", "max", "step", "accept", "maxLength"]) if (def[key] != null) input[key] = def[key];
    wrap.append(input); fragment.append(wrap);
  }
  return fragment;
}
export function makeForm(definitions, label, handler) {
  const form = element("form", undefined, "editor"); form.append(fields(definitions));
  const button = element("button", label); button.type = "submit"; form.append(button);
  form.addEventListener("submit", event => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(form));
    // Capture values before run() disables controls.
    run(form, () => handler(data, form));
  });
  return form;
}
import {chains,hasCapability} from './chains.js';
export {chains};
export const chainAddress = capability => [
  {name:"chain", label:"Chain", options:capability ? chains.filter(([id]) => hasCapability(id, capability)) : chains},
  {name:"address", label:"Public wallet address", required:true},
];
export function heading(host, name, reload) {
  host.replaceChildren(); const top = element("div", undefined, "workspace-heading");
  top.append(element("h1", name)); if (reload) top.append(action("Reload", reload)); host.append(top);
}
