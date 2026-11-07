// Render test for the frontend (dist/index.js) with stand-in Decky components and jsdom.
// Checks layout, order of the groups, expanding, switches, backend calls and the texts in BOTH
// languages (English and German, chosen through `navigator.languages` like in the Steam UI).
// It is NOT a test against Steam's real UI: looks and focus navigation are not covered.
// Run in a folder with react, react-dom and jsdom installed (e.g. an empty directory,
// `npm install react react-dom jsdom`):   node <path>/tools/frontend_render_test.mjs <path>/dist/index.js
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
globalThis.setInterval = (fn, ms) => realSetInterval(fn, Math.min(ms, 15)); // poll every 15 ms instead of every 2 s

// Stand-in Decky components: plain HTML elements, so text and clicks can be checked.
globalThis.DFL = {
  PanelSection: ({ title, children }) => h("section", { "data-title": title }, title && h("h2", null, title), children),
  PanelSectionRow: ({ children }) => h("div", { className: "row" }, children),
  Field: ({ label, description, children, onClick, icon }) =>
    h("div", { className: "field", onClick }, icon, h("b", null, label), description && h("i", null, description), children),
  ToggleField: ({ label, description, checked, onChange }) =>
    h("div", { className: "toggle", "data-checked": String(checked), onClick: () => onChange(!checked) }, h("b", null, label), h("i", null, description)),
  ButtonItem: ({ children, description, onClick, disabled }) =>
    h("button", { disabled, onClick }, children, description && h("i", null, description)),
  DropdownItem: ({ label, rgOptions, selectedOption, onChange }) => {
    dropdowns[label] = { rgOptions, onChange };
    return h("div", { className: "dropdown", "data-label": label, "data-selected": String(selectedOption), "data-labels": rgOptions.map((o) => o.label).join("|") }, label);
  },
  ConfirmModal: ({ strTitle }) => h("div", null, strTitle),
  showModal: () => {},
  staticClasses: { Title: "t" },
};
globalThis.SP_REACT = React;
globalThis.SP_JSX = jsxRuntime;

let calls = [];
let status;
const dropdowns = {}; // label -> { rgOptions, onChange } of the last render
const toasts = [];
let answers = {}; // call name → result; default is { ok: true }
globalThis.window.__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit = {
  connect: () => ({
    callable: (name) => async (...args) => {
      calls.push([name, ...args]);
      if (name === "get_status") return status;
      if (name === "take_low_battery_notices") { const pending = answers[name] ?? []; delete answers[name]; return pending; } // handed out once
      return answers[name] ?? { ok: true };
    },
    definePlugin: (fn) => fn,
    addEventListener() {}, removeEventListener() {}, toaster: { toast: (data) => toasts.push(data) },
  }),
};
globalThis.document = dom.window.document;

/** Makes the page believe the Steam UI language is `languages` (what `navigator.languages` would hold). */
const setNavigator = (languages) => Object.defineProperty(globalThis, "navigator", {
  value: languages === undefined ? {} : { language: languages[0], languages },
  configurable: true,
});

const slot = (n, over = {}) => ({
  slot: n, connected: true, detected_by: ["monitor"], led: null, headset: false, chatpad: false,
  subtype: 1, subtype_name: "Gamepad", battery_level: null, state_age_s: null, state_source: null, connected_age_s: 5, last_led_mode: null, ...over,
});
const base = () => ({
  settings: { monitor_enabled: true, auto_poweroff: true, poweroff_on_shutdown: false, startup_query: true, low_battery_toast: true, language: "auto" },
  monitor: { enabled: true, setup_error: null, readers: {} },
  led_modes: { 0: "off", 6: "position 1 on" },
  diagnostics: {
    verdict: { code: "run_ok", sent: 1, total: 1 },
    lines: [{ key: "time", value: "2000-01-01 12:00:00" }, { key: "duration", value: "1.2 s" }, { key: "receivers", value: "1" }],
  },
  receivers: [
    { usb_path: "1-3", label: "Xbox 360 Wireless Receiver (0719)", unofficial: false, bus: 1, devnum: 2, slot_count: 4, unlocated_count: 0, unassigned_leds: [],
      controllers: [slot(0, { battery_level: 2, state_age_s: 120, led: null }), slot(2, { battery_level: null, headset: true, detected_by: ["sysfs"] })] },
    { usb_path: "3-1", label: "Xbox 360 Wireless Receiver (02A9)", unofficial: true, bus: 3, devnum: 7, slot_count: 4, unlocated_count: 1, unassigned_leds: ["xpad4"], controllers: [] },
  ],
});

// Every text the test looks for, per language.
const TEXT = {
  en: {
    order: ["General", "Monitoring", "Power", "Turn off on standby", "Turn off on shutdown", "Receiver 1", "Controller 1", "Level 2/3", "Controller 3", "Receiver 2"],
    query: "Query battery now", turnOffController: "Turn off controller", details: "Details", slotOnReceiver: "Slot on receiver",
    lastReport: "Last report", twoMinutes: "2 min ago", twoHours: "2.0 h ago", level2of3: "Level 2 of 3", level2: "Level 2/3",
    ariaLevel2: 'aria-label="Battery level 2 of 3"', ariaUnknown: "Battery level unknown",
    moreControllers: "1 more controller connected", ledsOfReceiver: "LEDs of this receiver", slotsInUse: "2 of 4 slots in use",
    unofficial: "(02A9) · unofficial", ledPattern: "LED pattern", mode6: "6: position 1 on",
    diagnostics: "Diagnostics", service: "Shutdown service", runOk: "1 of 1 controllers turned off",
    time: "Time2000-01-01 12:00:00", duration: "Duration1.2 s", // label and value are separate elements
    toggleShutdown: "Turn off on shutdown", toggleStandby: "Turn off on standby",
    noReceiver: "No Xbox 360 receiver found", standbyUnavailable: "Turn-off on standby unavailable",
    noController: "No controller connected", wheel: "Wheel", unknownType: "Unknown (0x1F)",
    busy: "Another access to the receiver is already running.", libusb: "libusb could not be loaded: libusb-1.0.so.0 missing",
    setupFailed: "The service could not be set up: boom", fallbackError: "something technical",
    partial: "1 of 2 controllers turned off, error: slot 2 timed out", optionOff: "(The option is now off.)",
    installFailed: "The service is not set up: no systemd", runFailed: "ran at the last shutdown but failed: OSError: x",
    find: "Find controller", found: "vibration sent", queriedNow: "queried just now", querying: "querying battery", identify: "Identify",
    rumbleUnavailable: "The controller cannot vibrate right now (no usable input device): denied",
    toggleStartup: "Query battery at start", toggleLow: "Warn when battery is low", languageLabel: "Language",
    toastTitle: "Controller battery low", toastBody: "Controller 2: battery level 0/3",
    toastBodyDe: "Controller 2: Akkustufe 0/3", toastTitleDe: "Controller-Akku niedrig",
    optionAuto: "Automatic (Steam language)", generalDe: "Allgemein", generalEn: "General",
    testButton: "Send test notification", testBody: "Controller 1: battery level 1/3 (test)", testBodyDe: "Controller 1: Akkustufe 1/3 (Test)",
    findHint: "Vibrates the controller for a few seconds.", mode2: "2: position 1 blinking, then on",
  },
  de: {
    order: ["Allgemein", "Überwachung", "Energie", "Beim Standby ausschalten", "Beim Herunterfahren ausschalten", "Receiver 1", "Controller 1", "Stufe 2/3", "Controller 3", "Receiver 2"],
    query: "Akku jetzt abfragen", turnOffController: "Controller ausschalten", details: "Details", slotOnReceiver: "Slot am Receiver",
    lastReport: "Letzte Meldung", twoMinutes: "vor 2 min", twoHours: "vor 2,0 h", level2of3: "Stufe 2 von 3", level2: "Stufe 2/3",
    ariaLevel2: 'aria-label="Akkustufe 2 von 3"', ariaUnknown: "Akkustand unbekannt",
    moreControllers: "1 weiterer Controller verbunden", ledsOfReceiver: "LEDs dieses Receivers", slotsInUse: "2 von 4 Slots belegt",
    unofficial: "(02A9) · inoffiziell", ledPattern: "LED-Muster", mode6: "6: Position 1 an",
    diagnostics: "Diagnose", service: "Dienst beim Herunterfahren", runOk: "1 von 1 Controllern ausgeschaltet",
    time: "Zeit2000-01-01 12:00:00", duration: "Dauer1.2 s",
    toggleShutdown: "Beim Herunterfahren", toggleStandby: "Beim Standby",
    noReceiver: "Kein Xbox-360-Receiver gefunden", standbyUnavailable: "Standby-Ausschalten nicht verfügbar",
    noController: "Kein Controller verbunden", wheel: "Lenkrad", unknownType: "Unbekannt (0x1F)",
    busy: "Es läuft bereits ein Zugriff auf den Receiver.", libusb: "libusb nicht ladbar: libusb-1.0.so.0 missing",
    setupFailed: "Der Dienst konnte nicht eingerichtet werden: boom", fallbackError: "something technical",
    partial: "1 von 2 Controllern ausgeschaltet, Fehler: slot 2 timed out", optionOff: "(Option ist jetzt aus.)",
    installFailed: "Der Dienst ist nicht eingerichtet: no systemd", runFailed: "lief beim letzten Herunterfahren, scheiterte aber: OSError: x",
    find: "Controller finden", found: "Vibration gesendet", queriedNow: "soeben abgefragt", querying: "frage Akku ab", identify: "Erkennen",
    rumbleUnavailable: "Der Controller kann gerade nicht vibrieren (kein nutzbares Eingabegerät): denied",
    toggleStartup: "Akku beim Start abfragen", toggleLow: "Bei niedrigem Akku warnen", languageLabel: "Sprache",
    toastTitle: "Controller-Akku niedrig", toastBody: "Controller 2: Akkustufe 0/3",
    toastBodyDe: "Controller 2: Akkustufe 0/3", toastTitleDe: "Controller-Akku niedrig",
    optionAuto: "Automatisch (Steam-Sprache)", generalDe: "Allgemein", generalEn: "General",
    testButton: "Testbenachrichtigung senden", testBody: "Controller 1: Akkustufe 1/3 (Test)", testBodyDe: "Controller 1: Akkustufe 1/3 (Test)",
    findHint: "Lässt den Controller einige Sekunden vibrieren.", mode2: "2: Position 1 blinkt, dann an",
  },
};

const bundle = (await import(pathToFileURL(tmpBundle).href)).default;
const html = () => document.getElementById("root").innerHTML;
const plain = () => document.getElementById("root").textContent;
const flush = async () => { await act(async () => { await new Promise((r) => setTimeout(r, 60)); }); };
const click = async (el) => { await act(async () => { el.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true })); }); };
const fields = (text) => [...document.querySelectorAll(".field")].filter((f) => f.textContent.includes(text));
const toggle = (name) => [...document.querySelectorAll(".toggle")].find((t) => t.textContent.includes(name));

let currentPlugin = null;
async function mount(languages) {
  setNavigator(languages);
  const root = createRoot(document.getElementById("root"));
  currentPlugin = bundle();
  await act(async () => { root.render(currentPlugin.content); });
  await flush();
  return root;
}
async function unmount(root) {
  currentPlugin.onDismount(); // stops the low-battery poll
  await act(async () => { root.unmount(); });
}

async function runSuite(lang, languages) {
  const T = TEXT[lang];
  const label = `[${lang}]`;
  calls = []; answers = {}; status = base();
  const root = await mount(languages);

  // --- layout and order
  const out = plain();
  let pos = -1;
  for (const needle of T.order) { const i = out.indexOf(needle, pos + 1); assert.ok(i > pos, `${label} "${needle}" missing or in the wrong place`); pos = i; }
  // The monitor switch's hint mentions this label in prose, so look for the button, not for the text.
  const buttonTexts = () => [...document.querySelectorAll("button")].map((b) => b.textContent);
  assert.ok(!buttonTexts().some((text) => text.includes(T.query)), `${label} cards must start collapsed`);
  assert.ok(out.includes(T.moreControllers), `${label} unassigned controller is mentioned`);
  assert.ok(out.includes(T.ledsOfReceiver));
  assert.ok(out.includes(T.slotsInUse));
  assert.ok(out.includes(T.unofficial), `${label} unofficial receiver is marked`);
  assert.ok(html().includes(T.ariaLevel2), `${label} battery bar with label`);
  assert.ok(html().includes(T.ariaUnknown), `${label} bar without a value`);

  // --- expand
  await click(fields("Controller 1")[0] ?? fields("Controller")[0]);
  const open = plain();
  for (const needle of [T.query, T.turnOffController, T.details, T.slotOnReceiver, T.lastReport, T.twoMinutes]) assert.ok(open.includes(needle), `${label} ${needle} missing`);
  // The expanded area shows neither battery bar nor level; both appear only in the header row.
  assert.ok(!open.includes(T.level2of3), `${label} no battery level in the expanded area`);
  assert.equal(html().split(T.ariaLevel2).length - 1, 1, `${label} battery bar only once (header row)`);
  assert.equal(open.split(T.level2).length - 1, 1, `${label} level only once (header row)`);
  assert.ok(!open.slice(0, open.indexOf("Receiver 2")).includes(T.ledPattern), `${label} no LED group in the card without an assigned LED`);
  assert.ok(open.slice(open.indexOf("Receiver 2")).includes(`${T.ledPattern} (xpad4)`), `${label} unassignable LED sits at the receiver`);
  const card = open.slice(open.lastIndexOf(T.query) - 40); // the button comes after the General section's hint
  assert.ok(card.indexOf(TEXT[lang].order[2]) < card.indexOf(T.details), `${label} group order Battery → Power → Details`);

  // --- diagnostics: verdict visible, single steps only after expanding
  assert.ok(open.includes(T.diagnostics) && open.includes(T.service));
  assert.ok(open.includes(T.runOk), `${label} verdict text`);
  assert.ok(!open.includes(T.duration), `${label} steps collapsed at first`);
  const diag = fields(T.service)[0];
  await click(diag);
  assert.ok(plain().includes(T.duration) && plain().includes(T.time), `${label} diagnostic lines with translated labels`);
  await click(diag);
  assert.ok(!plain().includes(T.duration), `${label} collapsed again`);

  // --- switches call the backend
  await click(toggle(T.toggleShutdown));
  await click(toggle(T.toggleStandby));
  assert.deepEqual(calls.filter((c) => c[0] === "set_poweroff_on_shutdown"), [["set_poweroff_on_shutdown", true]]);
  assert.deepEqual(calls.filter((c) => c[0] === "set_auto_poweroff"), [["set_auto_poweroff", false]]);

  // --- query the battery with the right arguments
  const queryButton = () => [...document.querySelectorAll("button")].find((b) => b.textContent.includes(T.query));
  await click(queryButton());
  await flush();
  assert.deepEqual(calls.filter((c) => c[0] === "query_battery"), [["query_battery", 1, 2, 0]]);
  assert.ok(!plain().includes(T.queriedNow) && !plain().includes(T.querying), `${label} no message after a manual battery query`);

  // --- error codes from the backend are translated; details and unknown codes are handled
  answers.query_battery = { ok: false, error: "Another access to the receiver is already running.", code: "busy" };
  await click(queryButton()); await flush();
  assert.ok(plain().includes(T.busy), `${label} busy code translated`);
  answers.query_battery = { ok: false, error: "libusb could not be loaded: libusb-1.0.so.0 missing", code: "libusb_unavailable", detail: "libusb-1.0.so.0 missing" };
  await click(queryButton()); await flush();
  assert.ok(plain().includes(T.libusb), `${label} code with detail`);
  answers.query_battery = { ok: false, error: "something technical", code: "no_such_code" };
  await click(queryButton()); await flush();
  assert.ok(plain().includes(T.fallbackError), `${label} unknown code falls back to the backend text`);
  answers.query_battery = { ok: false, error: "something technical" };
  await click(queryButton()); await flush();
  assert.ok(plain().includes(T.fallbackError), `${label} no code falls back to the backend text`);
  answers.set_poweroff_on_shutdown = { ok: false, error: "Service not set up: boom", code: "unit_setup_failed", detail: "boom" };
  await click(toggle(T.toggleShutdown)); await flush();
  assert.ok(plain().includes(T.setupFailed), `${label} service setup error translated`);
  answers = {};

  // --- assigned LED appears in the card; the mode names are translated
  status = base();
  status.receivers[0].controllers = [slot(0, { battery_level: 3, led: "xpad0", last_led_mode: 6 })];
  status.receivers[0].unassigned_leds = [];
  await flush();
  assert.ok(plain().includes(`${T.ledPattern} (xpad0)`), `${label} LED group in the open card`);
  const dropdown = document.querySelector(`.dropdown[data-label^="${T.ledPattern}"]`);
  assert.equal(dropdown.dataset.selected, "6");
  assert.ok(dropdown.dataset.labels.split("|").includes(T.mode6), `${label} LED mode names are translated`);

  // --- the backend always sends a LED mode for an assigned LED (even without the monitor): the dropdown shows it
  status = base();
  status.receivers[0].controllers = [slot(0, { led: "xpad0", last_led_mode: 2, led_mode_source: "default" })];
  status.receivers[0].unassigned_leds = [];
  await flush();
  const ledDropdown = document.querySelector(`.dropdown[data-label^="${T.ledPattern}"]`);
  assert.equal(ledDropdown.dataset.selected, "2", `${label} default LED mode is selected`);

  // --- controller types: translated by subtype number, unknown types shown with their code
  status = base();
  status.receivers[0].controllers = [slot(0, { subtype: 2, subtype_name: "Wheel" }), slot(1, { subtype: 31, subtype_name: "Unknown (0x1F)" })];
  await flush();
  assert.ok(plain().includes(T.wheel), `${label} subtype name`);
  assert.ok(plain().includes(T.unknownType), `${label} unknown subtype`);

  // --- age of a report in hours uses the decimal separator of the language
  status = base();
  status.receivers[0].controllers = [slot(0, { battery_level: 1, state_age_s: 7200 })];
  await flush();
  assert.ok(plain().includes(T.twoHours), `${label} hours with decimal separator`);

  // --- find controller: backend call, message, translated error
  status = base();
  await flush();
  const findButton = () => [...document.querySelectorAll("button")].find((b) => b.textContent.includes(T.find));
  assert.ok(plain().includes(T.identify) && findButton(), `${label} identify group in the open card`);
  await click(findButton()); await flush();
  assert.deepEqual(calls.filter((c) => c[0] === "find_controller"), [["find_controller", 1, 2, 0]]);
  assert.ok(!plain().includes(T.found), `${label} no success message in the panel (only failures are shown)`);
  answers.find_controller = { ok: false, error: "Cannot open x", code: "rumble_unavailable", detail: "denied" };
  await click(findButton()); await flush();
  assert.ok(plain().includes(T.rumbleUnavailable), `${label} rumble error translated`);
  answers = {};

  // --- new switches and the language choice call the backend
  await click(toggle(T.toggleStartup));
  await click(toggle(T.toggleLow));
  assert.deepEqual(calls.filter((c) => c[0] === "set_startup_query"), [["set_startup_query", false]]);
  assert.deepEqual(calls.filter((c) => c[0] === "set_low_battery_toast"), [["set_low_battery_toast", false]]);
  const picker = dropdowns[T.languageLabel];
  assert.deepEqual(picker.rgOptions.map((o) => [o.data, o.label]),
                   [["auto", T.optionAuto], ["en", "English"], ["de", "Deutsch"]], `${label} language options`);
  assert.equal(document.querySelector(`.dropdown[data-label="${T.languageLabel}"]`).dataset.selected, "auto");
  await act(async () => { await picker.onChange({ data: "de" }); });
  assert.deepEqual(calls.filter((c) => c[0] === "set_language"), [["set_language", "de"]]);

  // --- the stored language choice overrides Steam's language
  const other = lang === "en" ? "de" : "en";
  status = base(); status.settings.language = other;
  await flush();
  assert.ok(plain().includes(other === "de" ? T.generalDe : T.generalEn), `${label} stored choice "${other}" wins over Steam's language`);
  status = base(); status.settings.language = "fr"; // unsupported choice: follow Steam again
  await flush();
  assert.ok(plain().includes(lang === "de" ? T.generalDe : T.generalEn), `${label} unsupported choice follows Steam`);
  status = base();
  await flush();

  // --- low-battery notices become toasts, in the language the notice carries
  toasts.length = 0;
  answers.take_low_battery_notices = [{ slot: 1, level: 0, language: "auto" }];
  await flush();
  assert.equal(toasts.length, 1, `${label} one toast`);
  assert.equal(toasts[0].title, T.toastTitle);
  assert.equal(toasts[0].body, T.toastBody);
  answers.take_low_battery_notices = [{ slot: 1, level: 0, language: "de" }];
  await flush();
  assert.equal(toasts.length, 2);
  assert.deepEqual([toasts[1].title, toasts[1].body], [T.toastTitleDe, T.toastBodyDe], `${label} notice language "de"`);
  await flush();
  assert.equal(toasts.length, 2, `${label} a notice is shown once`);

  // --- test notification button: shows a toast right away, in the UI language, without asking the backend
  toasts.length = 0;
  const testButton = [...document.querySelectorAll("button")].find((b) => b.textContent.includes(T.testButton));
  assert.ok(testButton, `${label} test notification button`);
  await click(testButton);
  assert.equal(toasts.length, 1, `${label} test toast shown`);
  assert.deepEqual([toasts[0].title, toasts[0].body], [T.toastTitle, T.testBody]);
  assert.ok(!calls.some((c) => c[0] === "take_low_battery_notices" && c.length > 1), `${label} no argument leaks`);

  // --- descriptions stay short
  const descriptions = [...document.querySelectorAll("i")].map((n) => n.textContent).filter(Boolean);
  const longest = descriptions.reduce((a, b) => (b.length > a.length ? b : a), "");
  assert.ok(longest.length <= 130, `${label} a description is too long (${longest.length}): ${longest}`);
  assert.ok(plain().includes(T.findHint), `${label} short find-controller hint`);

  // --- diagnostics verdicts
  const verdicts = [
    [{ code: "run_partial", sent: 1, total: 2, error: "slot 2 timed out" }, T.partial],
    [{ code: "run_ok", sent: 2, total: 2, option_off: true }, T.optionOff],
    [{ code: "install_failed", error: "no systemd" }, T.installFailed],
    [{ code: "run_failed", error: "OSError: x" }, T.runFailed],
  ];
  for (const [verdict, needle] of verdicts) {
    status = base(); status.diagnostics.verdict = verdict;
    await flush();
    assert.ok(plain().includes(needle), `${label} verdict ${verdict.code}`);
  }

  // --- without diagnostics there is no diagnostics group
  status = base(); status.diagnostics = null;
  await flush();
  assert.ok(!plain().includes(T.service));

  // --- no receivers / monitoring off / standby parameter unreadable
  status = base(); status.receivers = []; status.settings.auto_poweroff = null; status.settings.monitor_enabled = false;
  await flush();
  const empty = plain();
  assert.ok(empty.includes(T.noReceiver));
  assert.ok(empty.includes(T.standbyUnavailable));
  assert.ok(!empty.includes(T.toggleStandby));
  assert.ok(empty.includes(T.toggleShutdown));

  // --- receiver without controllers
  status = base(); status.receivers[1].unlocated_count = 0; status.receivers[1].unassigned_leds = [];
  await flush();
  assert.ok(plain().includes(T.noController));

  await unmount(root);
  console.log(`${label} render test OK, ${calls.length} backend calls`);
}

// --- language detection: first supported entry of the language list wins, English is the fallback
await runSuite("en", ["en-US", "en"]);
await runSuite("de", ["de-DE", "de"]);

async function languageOf(languages) {
  status = base(); calls = []; answers = {};
  const root = await mount(languages);
  const text = plain();
  await unmount(root);
  return text.includes("Allgemein") ? "de" : text.includes("General") ? "en" : "?";
}
assert.equal(await languageOf(["de"]), "de");
assert.equal(await languageOf(["de-AT"]), "de");
assert.equal(await languageOf(["en-GB"]), "en");
assert.equal(await languageOf(["fr-FR"]), "en", "unsupported language falls back to English");
assert.equal(await languageOf(["fr-FR", "de-DE"]), "de", "first supported entry wins");
assert.equal(await languageOf(["en-US", "de-DE"]), "en", "an earlier English entry beats a later German one");
assert.equal(await languageOf([]), "en", "empty list falls back to English");
assert.equal(await languageOf(undefined), "en", "no navigator falls back to English");
console.log("language detection OK");

process.exit(0);
