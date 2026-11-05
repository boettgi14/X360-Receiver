// Rendertest für das Frontend (dist/index.js) mit gestellten Decky-Bausteinen und jsdom.
// Prüft Aufbau, Reihenfolge der Gruppen, Ausklappen, Schalter und Backend-Aufrufe. Es ist KEIN Test
// gegen Steams echte Oberfläche: Aussehen und Fokus-Navigation bleiben ungeprüft.
// Aufruf in einem Ordner mit installiertem react, react-dom und jsdom (z. B. leeres Verzeichnis,
// `npm install react react-dom jsdom`):   node <Pfad>/tools/frontend_render_test.mjs <Pfad>/dist/index.js
import { createRequire } from "node:module";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

const require = createRequire(path.join(process.cwd(), "x.js"));
const { JSDOM } = require("jsdom");
const React = require("react");
const jsxRuntime = require("react/jsx-runtime");
const { createRoot } = require("react-dom/client");
const { act } = React;
const assert = require("node:assert/strict");
const bundlePath = path.resolve(process.argv[2] ?? "dist/index.js");
const tmpBundle = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "x360w-")), "bundle.mjs");
fs.copyFileSync(bundlePath, tmpBundle);

const dom = new JSDOM("<!doctype html><div id=root></div>", { pretendToBeVisual: true });
globalThis.window = dom.window; globalThis.document = dom.window.document;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const h = React.createElement;
const realSetInterval = globalThis.setInterval;
globalThis.setInterval = (fn, ms) => realSetInterval(fn, Math.min(ms, 15)); // Abfrage statt alle 2 s alle 15 ms

// Gestellte Decky-Bausteine: einfache HTML-Elemente, damit Text und Klicks prüfbar sind.
const text = (n) => (typeof n === "string" ? n : null);
globalThis.DFL = {
  PanelSection: ({ title, children }) => h("section", { "data-title": title }, title && h("h2", null, title), children),
  PanelSectionRow: ({ children }) => h("div", { className: "row" }, children),
  Field: ({ label, description, children, onClick, onActivate, icon }) =>
    h("div", { className: "field", onClick }, icon, h("b", null, label), description && h("i", null, description), children),
  ToggleField: ({ label, description, checked, onChange }) =>
    h("div", { className: "toggle", "data-checked": String(checked), onClick: () => onChange(!checked) }, h("b", null, label), h("i", null, description)),
  ButtonItem: ({ children, description, onClick, disabled }) =>
    h("button", { disabled, onClick }, children, description && h("i", null, description)),
  DropdownItem: ({ label, rgOptions, selectedOption }) =>
    h("div", { className: "dropdown", "data-selected": String(selectedOption) }, label, rgOptions.length + " Optionen"),
  ConfirmModal: ({ strTitle }) => h("div", null, strTitle),
  showModal: () => {},
  staticClasses: { Title: "t" },
};
globalThis.SP_REACT = React;
globalThis.SP_JSX = jsxRuntime;

const calls = [];
let status;
globalThis.window.__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit = {
  connect: () => ({
    callable: (name) => async (...args) => { calls.push([name, ...args]); return name === "get_status" ? status : { ok: true }; },
    definePlugin: (fn) => fn,
    addEventListener() {}, removeEventListener() {}, toaster: {},
  }),
};
globalThis.document = dom.window.document;

const slot = (n, over = {}) => ({
  slot: n, connected: true, detected_by: ["monitor"], led: null, headset: false, chatpad: false,
  subtype_name: "Gamepad", battery_level: null, state_age_s: null, state_source: null, connected_age_s: 5, last_led_mode: null, ...over,
});
const base = () => ({
  settings: { monitor_enabled: true, auto_poweroff: true, poweroff_on_shutdown: false },
  monitor: { enabled: true, setup_error: null, readers: {} },
  led_modes: { 0: "aus", 6: "Position 1 an" },
  diagnostics: { verdict: "Der Dienst lief beim letzten Herunterfahren: 1 von 1 Controllern ausgeschaltet.", lines: ["Zeit: 2026-11-05 12:00:00", "Dauer: 1.2 s, Receiver: 1"] },
  receivers: [
    { usb_path: "1-3", label: "Xbox 360 Wireless Receiver (0719)", bus: 1, devnum: 2, slot_count: 4, unlocated_count: 0, unassigned_leds: [],
      controllers: [slot(0, { battery_level: 2, state_age_s: 120, led: null }), slot(2, { battery_level: null, headset: true, detected_by: ["sysfs"] })] },
    { usb_path: "3-1", label: "Xbox 360 Wireless Receiver (0291)", bus: 3, devnum: 7, slot_count: 4, unlocated_count: 1, unassigned_leds: ["xpad4"], controllers: [] },
  ],
});

const bundle = (await import(pathToFileURL(tmpBundle).href)).default;
const plugin = bundle();
const root = createRoot(document.getElementById("root"));
const html = () => document.getElementById("root").innerHTML;
const plain = () => document.getElementById("root").textContent;
const flush = async () => { await act(async () => { await new Promise((r) => setTimeout(r, 60)); }); };

status = base();
await act(async () => { root.render(plugin.content); });
await flush();

// --- Aufbau und Reihenfolge
const out = plain();
const order = ["Allgemein", "Überwachung", "Energie", "Beim Standby ausschalten", "Beim Herunterfahren ausschalten", "Receiver 1", "Controller 1", "Stufe 2/3", "Controller 3", "Receiver 2"];
let pos = -1;
for (const needle of order) { const i = out.indexOf(needle, pos + 1); assert.ok(i > pos, `"${needle}" fehlt oder steht an falscher Stelle`); pos = i; }
assert.ok(!out.includes("Akku jetzt abfragen"), "Karten müssen eingeklappt starten");
assert.ok(out.includes("1 weiterer Controller verbunden"), "nicht zugeordneter Controller wird erwähnt");
assert.ok(out.includes("LEDs dieses Receivers"));
assert.ok(out.includes("2 von 4 Slots belegt"));
assert.ok(html().includes("Akkustufe 2 von 3"), "Akkubalken mit Beschriftung");
assert.ok(html().includes("Akkustand unbekannt"), "Balken ohne Wert");

// --- Ausklappen
const headers = [...document.querySelectorAll(".field")].filter((f) => f.textContent.includes("Controller 1"));
await act(async () => { headers[0].dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true })); });
const open = plain();
for (const needle of ["Akku jetzt abfragen", "Controller ausschalten", "Details", "Slot am Receiver", "Letzte Meldung", "vor 2 min"]) assert.ok(open.includes(needle), needle + " fehlt");
// Der aufgeklappte Bereich zeigt weder Akkubalken noch Stufe; beides steht nur in der Kopfzeile.
assert.ok(!open.includes("Stufe 2 von 3"), "keine Akkustufe im aufgeklappten Bereich");
assert.equal(html().split('aria-label="Akkustufe 2 von 3"').length - 1, 1, "Akkubalken nur einmal (Kopfzeile)");
assert.equal(open.split("Stufe 2/3").length - 1, 1, "Stufe nur einmal (Kopfzeile)");
assert.ok(!open.slice(0, open.indexOf("Receiver 2")).includes("LED-Muster"), "ohne zugeordnete LED keine LED-Gruppe in der Karte");
assert.ok(open.slice(open.indexOf("Receiver 2")).includes("LED-Muster (xpad4)"), "nicht zuordenbare LED beim Receiver");
// Gruppenüberschriften stehen in der Reihenfolge Akku → Energie → Details innerhalb der Karte
const card = open.slice(open.indexOf("Akku jetzt abfragen") - 40);
assert.ok(card.indexOf("Energie") < card.indexOf("Details"));

// --- Diagnose: Urteil sichtbar, Einzelschritte erst nach dem Ausklappen
assert.ok(open.includes("Diagnose") && open.includes("Dienst beim Herunterfahren"));
assert.ok(open.includes("1 von 1 Controllern ausgeschaltet"));
assert.ok(!open.includes("Dauer: 1.2 s, Receiver: 1"), "Einzelschritte zunächst eingeklappt");
const diag = [...document.querySelectorAll(".field")].find((f) => f.textContent.includes("Dienst beim Herunterfahren"));
await act(async () => { diag.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true })); });
assert.ok(plain().includes("Dauer: 1.2 s, Receiver: 1") && plain().includes("Zeit: 2026-11-05 12:00:00"));
await act(async () => { diag.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true })); });
assert.ok(!plain().includes("Dauer: 1.2 s, Receiver: 1"), "wieder eingeklappt");

// --- Schalter rufen das Backend
const toggle = (name) => [...document.querySelectorAll(".toggle")].find((t) => t.textContent.includes(name));
await act(async () => { toggle("Beim Herunterfahren").dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true })); });
await act(async () => { toggle("Beim Standby").dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true })); });
assert.deepEqual(calls.filter((c) => c[0] === "set_poweroff_on_shutdown"), [["set_poweroff_on_shutdown", true]]);
assert.deepEqual(calls.filter((c) => c[0] === "set_auto_poweroff"), [["set_auto_poweroff", false]]);

// --- Akku abfragen mit den richtigen Argumenten
const btn = [...document.querySelectorAll("button")].find((b) => b.textContent.includes("Akku jetzt abfragen"));
await act(async () => { btn.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true })); });
await flush();
assert.deepEqual(calls.filter((c) => c[0] === "query_battery"), [["query_battery", 1, 2, 0]]);

// --- zugeordnete LED erscheint in der Karte
status = base();
status.receivers[0].controllers = [slot(0, { battery_level: 3, led: "xpad0", last_led_mode: 6 })];
status.receivers[0].unassigned_leds = [];
await flush();
const again = [...document.querySelectorAll(".field")].find((f) => f.textContent.includes("Controller 1"));
assert.ok(plain().includes("LED-Muster (xpad0)"), "LED-Gruppe in geöffneter Karte");
assert.equal(document.querySelector(".dropdown").dataset.selected, "6");

// --- ohne Diagnose keine Diagnose-Gruppe
status = base(); status.diagnostics = null;
await flush();
assert.ok(!plain().includes("Dienst beim Herunterfahren"));

// --- keine Receiver / Überwachung aus / Standby-Parameter nicht lesbar
status = base(); status.receivers = []; status.settings.auto_poweroff = null; status.settings.monitor_enabled = false;
await flush();
const empty = plain();
assert.ok(empty.includes("Kein Xbox-360-Receiver gefunden"));
assert.ok(empty.includes("Standby-Ausschalten nicht verfügbar"));
assert.ok(!empty.includes("Beim Standby ausschalten"));
assert.ok(empty.includes("Beim Herunterfahren ausschalten"));

// --- Receiver ohne Controller
status = base(); status.receivers[1].unlocated_count = 0; status.receivers[1].unassigned_leds = [];
await flush();
assert.ok(plain().includes("Kein Controller verbunden"));

console.log("Rendertest OK,", calls.length, "Backend-Aufrufe");
root.unmount();
process.exit(0);
