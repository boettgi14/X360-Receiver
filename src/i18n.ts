// Texts of the plugin UI in English and German.
//
// The UI follows the language of the Steam client (SteamOS and Bazzite alike), the way Decky Loader's
// own UI does: it reads `navigator.language` (Decky: i18next with `lng: navigator.language`, source read
// 2026-11-06; not verified on a device yet). German is used for "de", "de-DE", ...; everything else
// falls back to English.
//
// The Python backend is language-neutral. It returns English technical messages plus, where a user
// can act on a failure, a stable `code` (and `detail`) that is translated here (see `errorText`), and
// the diagnostics verdict as a code with parameters (see `verdictText`). Technical details such as
// kernel or libusb messages are shown untranslated.
//
// `en` defines the shape of all messages; `de` must match it, so a missing or mistyped German entry
// fails `npm run typecheck`.

export type Lang = "en" | "de";

const en = {
  // ---- generic
  loading: "Loading …",
  error: "Error",
  unknown: "unknown",
  yes: "yes",
  no: "no",
  controllerGeneric: "Controller",
  headset: "Headset",
  chatpad: "Chatpad",
  unofficial: "unofficial",
  backendUnreachable: (detail: string) => `Backend unreachable: ${detail}`,
  dismissHint: "Select to dismiss",

  // ---- language setting
  groupLanguage: "Language",
  languageSetting: "Language",
  languageHint: "Automatic follows the Steam language.",
  languageAuto: "Automatic (Steam language)",
  languageEnglish: "English",
  languageGerman: "Deutsch",

  // ---- battery options and the low-battery notification
  startupQueryToggle: "Query battery at start",
  startupQueryHint:
    "When the plugin starts, each connected controller is queried once and disappears for about 3 seconds. Without this, a controller that was already connected shows no battery level until you query it.",
  lowBatteryToggle: "Warn when battery is low",
  lowBatteryHint:
    "Shows a notification when a controller reports battery level 0 or 1 of 3. The receiver only reports the level when a controller connects or when it is queried, so the warning appears at those moments. Assumes that 0 means empty and 1 means low (not verified on a device).",
  lowBatteryTitle: "Controller battery low",
  lowBatteryBody: (n: number, level: number) => `Controller ${n}: battery level ${level}/3`,

  // ---- find controller
  groupIdentify: "Identify",
  findController: "Find controller",
  findControllerHint: "Vibrates the controller for about a second and blinks its LED once.",
  foundController: (n: number) => `Controller ${n}: vibration sent`,

  // ---- ages and levels
  ageSeconds: (n: number) => `${n} s ago`,
  ageMinutes: (n: number) => `${n} min ago`,
  ageHours: (hours: string) => `${hours} h ago`,
  level: (n: number) => `Level ${n}/3`,
  batteryLevelUnknown: "Battery level unknown",
  batteryLevelLabel: (n: number) => `Battery level ${n} of 3`,

  // ---- controller types (XInput subtypes, keyed by subtype number)
  unknownSubtype: (hex: string) => `Unknown (${hex})`,
  subtypes: {
    1: "Gamepad",
    2: "Wheel",
    3: "Arcade Stick",
    4: "Flight Stick",
    5: "Dance Pad",
    6: "Guitar",
    7: "Guitar (alternate)",
    8: "Drum Kit",
    11: "Guitar (bass)",
    19: "Arcade Pad",
  },

  // ---- LED modes (xpad.c), keyed by mode number
  ledModes: {
    0: "off",
    1: "all blinking, then previous state",
    2: "position 1 blinking, then on",
    3: "position 2 blinking, then on",
    4: "position 3 blinking, then on",
    5: "position 4 blinking, then on",
    6: "position 1 on",
    7: "position 2 on",
    8: "position 3 on",
    9: "position 4 on",
    10: "rotating",
    11: "blinking, based on previous state",
    12: "slow blinking, based on previous state",
    13: "rotating with two lights",
    14: "all slowly blinking, permanently",
    15: "blink once, then previous state",
  },
  ledPattern: (name: string) => `LED pattern (${name})`,
  ledReset: "Reset to default",

  // ---- messages after actions
  controllerN: (n: number) => `Controller ${n}`,
  queryingBattery: (n: number) => `Controller ${n}: querying battery …`,
  noResponse: (n: number) => `Controller ${n}: no response (off or not connected?)`,
  batteryQueried: (n: number, level: string) => `Controller ${n}: battery ${level.toLowerCase()}, queried just now`,
  turnOffTitle: (n: number) => `Turn off controller ${n}?`,
  turnOffText: "The controller turns off and has to be switched back on with its Guide button.",
  turnOffButton: "Turn off",
  turnedOff: (n: number) => `Controller ${n}: turned off`,
  turnOffUnconfirmed: (n: number) => `Controller ${n}: command sent, no confirmation (may have been off already)`,
  turnOffAllTitle: "Turn off all controllers?",
  turnOffAllText: "All connected controllers on all receivers turn off. Same procedure as on shutdown.",
  turnOffAllButton: "Turn off all",
  turningOffAll: "Turning off controllers …",
  turnOffAllProblem: (details: string) => `Problem while turning off: ${details}`,
  noConnectedController: "No connected controller found",
  turnedOffAll: (sent: number, confirmed: number) =>
    `${sent} ${sent === 1 ? "controller" : "controllers"} turned off (${confirmed} confirmed)`,

  // ---- "General" section
  general: "General",
  groupMonitoring: "Monitoring",
  monitorToggle: "Live USB monitoring",
  monitorToggleHint:
    "Follows the receivers' USB traffic (usbmon) to see connections and battery reports the moment they happen. Without it, controllers are still listed (found through the system) and show the battery level of the last query: at plugin start or with “Query battery now”. Only status and counters are kept, never button presses.",
  monitorCannotStart: "Monitor cannot start",
  busN: (bus: string) => `Bus ${bus}`,
  groupPower: "Power",
  standbyUnavailable: "Turn-off on standby unavailable",
  standbyUnavailableHint: "The kernel parameter xpad.auto_poweroff cannot be read (is the xpad driver loaded?).",
  standbyToggle: "Turn off on standby",
  standbyHint: "All controllers turn off when the device goes to standby. Applies to all receivers.",
  shutdownToggle: "Turn off on shutdown",
  shutdownHint:
    "All controllers turn off when the device shuts down or restarts. Applies to all receivers. Sets up a small system service for this, which is deleted again when the option is switched off and when the plugin is removed.",
  turnOffAllNow: "Turn off all controllers now",
  turnOffAllNowHint: "Same procedure as on shutdown, for trying it out.",

  // ---- receivers
  receiverTitle: "Receiver",
  receiverN: (n: number) => `Receiver ${n}`,
  noReceiver: "No Xbox 360 receiver found",
  noReceiverHint: "Plug in the USB dongle.",
  busDevice: (bus: number, device: number) => `bus ${bus}, device ${device}`,
  slotsInUse: (used: number, total: number) => `${used} of ${total} slots in use`,
  groupControllers: "Controllers",
  noControllerConnected: "No controller connected",
  moreControllers: (n: number) => `${n} more ${n === 1 ? "controller" : "controllers"} connected`,
  moreControllersHint: (monitorLabel: string) =>
    `The slot was not detected. Turn on “${monitorLabel}” (above) to show it here.`,
  groupReceiverLeds: "LEDs of this receiver",
  ledUnassigned: "Cannot assign",
  ledUnassignedHint:
    "The number of LEDs does not match the number of detected controllers (xpad0 is controller 1, xpad1 is controller 2, and so on).",

  // ---- controller card
  groupBattery: "Battery",
  groupLed: "LED",
  groupDetails: "Details",
  lastReport: "Last report",
  notReportedYet: "not reported yet",
  freshnessMonitorOff: (queryLabel: string) =>
    `Monitoring is off. The battery level is determined when the plugin starts and with “${queryLabel}”, not continuously.`,
  freshnessFromLink: "From the connection message; how fresh the value is, is unclear.",
  queryBattery: "Query battery now",
  queryBatteryHint: "The controller disappears for about 3 seconds. Do not use during a game.",
  turnOffController: "Turn off controller",
  detailSlot: "Slot on receiver",
  detailType: "Type",
  detailHeadset: "Headset",
  detailChatpad: "Chatpad",
  detailDetectedVia: "Detected via",
  viaMonitor: "monitoring",
  viaSystem: "system",

  // ---- diagnostics (service that runs on shutdown)
  groupDiagnostics: "Diagnostics",
  shutdownService: "Shutdown service",
  optionNowOff: " (The option is now off.)",
  verdictInstallFailed: (error: string) => `The service is not set up: ${error}`,
  verdictNotInstalled: "The service is not set up.",
  verdictNotRunYet: "The service is set up and has not run yet. It runs at the next shutdown.",
  verdictRunFailed: (error: string) => `The service ran at the last shutdown but failed: ${error}`,
  verdictNoControllers: "The service ran at the last shutdown but found no connected controller.",
  verdictRunPartial: (sent: number, total: number, error: string) =>
    `The service ran at the last shutdown: ${sent} of ${total} controllers turned off, error: ${error}`,
  verdictRunOk: (sent: number, total: number) =>
    `The service ran at the last shutdown: ${sent} of ${total} controllers turned off.`,
  diagnosticLines: {
    time: "Time",
    duration: "Duration",
    receivers: "Receivers",
    targets: "Targets (bus, device, slot)",
    result: "Result",
    error: "Error",
    write_error: "Report not written",
  },

  // ---- error codes from the backend (see main.py); a `detail` is appended after a colon
  errors: {
    busy: "Another access to the receiver is already running.",
    receiver_not_found: "Receiver not found.",
    led_missing: "The LED does not exist (controller still connected?)",
    libusb_unavailable: "libusb could not be loaded",
    unit_setup_failed: "The service could not be set up",
    unit_removal_failed: "The service could not be removed completely",
    settings_not_saved: "The setting could not be saved",
    rumble_unavailable: "The controller cannot vibrate right now (no usable input device)",
  },
};

export type Messages = typeof en;

const de: Messages = {
  loading: "Lade …",
  error: "Fehler",
  unknown: "unbekannt",
  yes: "ja",
  no: "nein",
  controllerGeneric: "Controller",
  headset: "Headset",
  chatpad: "Chatpad",
  unofficial: "inoffiziell",
  backendUnreachable: (detail) => `Backend nicht erreichbar: ${detail}`,
  dismissHint: "Zum Ausblenden auswählen",

  groupLanguage: "Sprache",
  languageSetting: "Sprache",
  languageHint: "Automatisch folgt der Steam-Sprache.",
  languageAuto: "Automatisch (Steam-Sprache)",
  languageEnglish: "English",
  languageGerman: "Deutsch",

  startupQueryToggle: "Akku beim Start abfragen",
  startupQueryHint:
    "Beim Start des Plugins wird jeder verbundene Controller einmal abgefragt und verschwindet dabei für etwa 3 Sekunden. Ohne das zeigt ein schon verbundener Controller keinen Akkustand, bis du ihn abfragst.",
  lowBatteryToggle: "Bei niedrigem Akku warnen",
  lowBatteryHint:
    "Zeigt eine Benachrichtigung, wenn ein Controller Akkustufe 0 oder 1 von 3 meldet. Der Receiver meldet die Stufe nur beim Verbinden eines Controllers oder bei einer Abfrage, die Warnung erscheint daher zu diesen Zeitpunkten. Annahme: 0 heißt leer, 1 niedrig (am Gerät nicht geprüft).",
  lowBatteryTitle: "Controller-Akku niedrig",
  lowBatteryBody: (n, level) => `Controller ${n}: Akkustufe ${level}/3`,

  groupIdentify: "Erkennen",
  findController: "Controller finden",
  findControllerHint: "Lässt den Controller etwa eine Sekunde vibrieren und seine LED einmal blinken.",
  foundController: (n) => `Controller ${n}: Vibration gesendet`,

  ageSeconds: (n) => `vor ${n} s`,
  ageMinutes: (n) => `vor ${n} min`,
  ageHours: (hours) => `vor ${hours} h`,
  level: (n) => `Stufe ${n}/3`,
  batteryLevelUnknown: "Akkustand unbekannt",
  batteryLevelLabel: (n) => `Akkustufe ${n} von 3`,

  unknownSubtype: (hex) => `Unbekannt (${hex})`,
  subtypes: {
    1: "Gamepad",
    2: "Lenkrad",
    3: "Arcade-Stick",
    4: "Flight-Stick",
    5: "Tanzmatte",
    6: "Gitarre",
    7: "Gitarre (alternativ)",
    8: "Schlagzeug",
    11: "Bassgitarre",
    19: "Arcade-Pad",
  },

  ledModes: {
    0: "aus",
    1: "alle blinken, dann vorheriger Zustand",
    2: "Position 1 blinkt, dann an",
    3: "Position 2 blinkt, dann an",
    4: "Position 3 blinkt, dann an",
    5: "Position 4 blinkt, dann an",
    6: "Position 1 an",
    7: "Position 2 an",
    8: "Position 3 an",
    9: "Position 4 an",
    10: "rotierend",
    11: "blinkend, nach vorherigem Zustand",
    12: "langsam blinkend, nach vorherigem Zustand",
    13: "rotierend mit zwei Lichtern",
    14: "dauerhaft langsam alle blinkend",
    15: "einmal blinken, dann vorheriger Zustand",
  },
  ledPattern: (name) => `LED-Muster (${name})`,
  ledReset: "Auf Standard zurücksetzen",

  controllerN: (n) => `Controller ${n}`,
  queryingBattery: (n) => `Controller ${n}: frage Akku ab …`,
  noResponse: (n) => `Controller ${n}: keine Antwort (aus oder nicht verbunden?)`,
  batteryQueried: (n, level) => `Controller ${n}: Akku ${level}, soeben abgefragt`,
  turnOffTitle: (n) => `Controller ${n} ausschalten?`,
  turnOffText: "Der Controller geht aus und muss mit der Guide-Taste wieder eingeschaltet werden.",
  turnOffButton: "Ausschalten",
  turnedOff: (n) => `Controller ${n}: ausgeschaltet`,
  turnOffUnconfirmed: (n) => `Controller ${n}: Befehl gesendet, keine Bestätigung (war evtl. schon aus)`,
  turnOffAllTitle: "Alle Controller ausschalten?",
  turnOffAllText: "Alle verbundenen Controller an allen Receivern gehen aus. Derselbe Ablauf wie beim Herunterfahren.",
  turnOffAllButton: "Alle ausschalten",
  turningOffAll: "Schalte Controller aus …",
  turnOffAllProblem: (details) => `Problem beim Ausschalten: ${details}`,
  noConnectedController: "Kein verbundener Controller gefunden",
  turnedOffAll: (sent, confirmed) => `${sent} Controller ausgeschaltet (${confirmed} bestätigt)`,

  general: "Allgemein",
  groupMonitoring: "Überwachung",
  monitorToggle: "Live-Überwachung per USB",
  monitorToggleHint:
    "Verfolgt den USB-Verkehr der Receiver (usbmon), um Verbindungen und Akkumeldungen im Moment ihres Auftretens zu sehen. Ohne das werden Controller trotzdem angezeigt (über das System erkannt) und zeigen den Akkustand der letzten Abfrage: beim Start des Plugins oder mit „Akku jetzt abfragen“. Gespeichert werden nur Status und Zähler, nie Tastendrücke.",
  monitorCannotStart: "Monitor nicht startbar",
  busN: (bus) => `Bus ${bus}`,
  groupPower: "Energie",
  standbyUnavailable: "Standby-Ausschalten nicht verfügbar",
  standbyUnavailableHint: "Der Kernelparameter xpad.auto_poweroff ist nicht lesbar (Treiber xpad geladen?).",
  standbyToggle: "Beim Standby ausschalten",
  standbyHint: "Alle Controller gehen aus, wenn das Gerät in den Standby geht. Gilt für alle Receiver.",
  shutdownToggle: "Beim Herunterfahren ausschalten",
  shutdownHint:
    "Alle Controller gehen aus, wenn das Gerät herunterfährt oder neu startet. Gilt für alle Receiver. Richtet dafür einen kleinen Systemdienst ein, der beim Ausschalten der Option und beim Entfernen des Plugins wieder gelöscht wird.",
  turnOffAllNow: "Alle Controller jetzt ausschalten",
  turnOffAllNowHint: "Gleicher Ablauf wie beim Herunterfahren, zum Ausprobieren.",

  receiverTitle: "Receiver",
  receiverN: (n) => `Receiver ${n}`,
  noReceiver: "Kein Xbox-360-Receiver gefunden",
  noReceiverHint: "USB-Dongle einstecken.",
  busDevice: (bus, device) => `Bus ${bus}, Gerät ${device}`,
  slotsInUse: (used, total) => `${used} von ${total} Slots belegt`,
  groupControllers: "Controller",
  noControllerConnected: "Kein Controller verbunden",
  moreControllers: (n) => `${n} weiterer Controller verbunden`,
  moreControllersHint: (monitorLabel) =>
    `Der Slot wurde nicht erkannt. Mit „${monitorLabel}“ (oben) erscheint er hier.`,
  groupReceiverLeds: "LEDs dieses Receivers",
  ledUnassigned: "Zuordnung nicht möglich",
  ledUnassignedHint:
    "Die Zahl der LEDs passt nicht zur Zahl der erkannten Controller (xpad0 ist Controller 1, xpad1 Controller 2 usw.).",

  groupBattery: "Akku",
  groupLed: "LED",
  groupDetails: "Details",
  lastReport: "Letzte Meldung",
  notReportedYet: "noch nicht gemeldet",
  freshnessMonitorOff: (queryLabel) =>
    `Die Überwachung ist aus. Der Akkustand wird beim Start des Plugins und mit „${queryLabel}“ ermittelt, nicht laufend.`,
  freshnessFromLink: "Aus der Verbindungsmeldung; wie frisch der Wert ist, ist unklar.",
  queryBattery: "Akku jetzt abfragen",
  queryBatteryHint: "Der Controller verschwindet dafür ca. 3 Sekunden. Nicht im Spiel benutzen.",
  turnOffController: "Controller ausschalten",
  detailSlot: "Slot am Receiver",
  detailType: "Typ",
  detailHeadset: "Headset",
  detailChatpad: "Chatpad",
  detailDetectedVia: "Erkannt über",
  viaMonitor: "Überwachung",
  viaSystem: "System",

  groupDiagnostics: "Diagnose",
  shutdownService: "Dienst beim Herunterfahren",
  optionNowOff: " (Option ist jetzt aus.)",
  verdictInstallFailed: (error) => `Der Dienst ist nicht eingerichtet: ${error}`,
  verdictNotInstalled: "Der Dienst ist nicht eingerichtet.",
  verdictNotRunYet: "Der Dienst ist eingerichtet und hat noch nicht gelaufen. Er läuft beim nächsten Herunterfahren.",
  verdictRunFailed: (error) => `Der Dienst lief beim letzten Herunterfahren, scheiterte aber: ${error}`,
  verdictNoControllers: "Der Dienst lief beim letzten Herunterfahren, fand aber keinen verbundenen Controller.",
  verdictRunPartial: (sent, total, error) =>
    `Der Dienst lief beim letzten Herunterfahren: ${sent} von ${total} Controllern ausgeschaltet, Fehler: ${error}`,
  verdictRunOk: (sent, total) =>
    `Der Dienst lief beim letzten Herunterfahren: ${sent} von ${total} Controllern ausgeschaltet.`,
  diagnosticLines: {
    time: "Zeit",
    duration: "Dauer",
    receivers: "Receiver",
    targets: "Ziele (Bus, Gerät, Slot)",
    result: "Ergebnis",
    error: "Fehler",
    write_error: "Bericht nicht geschrieben",
  },

  errors: {
    busy: "Es läuft bereits ein Zugriff auf den Receiver.",
    receiver_not_found: "Receiver nicht gefunden.",
    led_missing: "Die LED existiert nicht (Controller noch verbunden?)",
    libusb_unavailable: "libusb nicht ladbar",
    unit_setup_failed: "Der Dienst konnte nicht eingerichtet werden",
    unit_removal_failed: "Der Dienst konnte nicht vollständig entfernt werden",
    settings_not_saved: "Die Einstellung konnte nicht gespeichert werden",
    rumble_unavailable: "Der Controller kann gerade nicht vibrieren (kein nutzbares Eingabegerät)",
  },
};

export const MESSAGES: Record<Lang, Messages> = { en, de };

// ---------------------------------------------------------------- language

/** The part of the browser's `navigator` that language detection needs. */
interface NavigatorLike {
  language?: string;
  languages?: readonly string[];
}

/** Picks the UI language: the first entry of the browser's language list that is supported, else English. */
export function detectLanguage(
  nav: NavigatorLike | undefined = typeof navigator === "undefined" ? undefined : navigator,
): Lang {
  const list = nav?.languages && nav.languages.length > 0 ? nav.languages : [nav?.language ?? ""];
  for (const entry of list) {
    const code = String(entry).toLowerCase();
    if (code === "de" || code.startsWith("de-") || code.startsWith("de_")) return "de";
    if (code === "en" || code.startsWith("en-") || code.startsWith("en_")) return "en";
  }
  return "en";
}

/** The language choice stored in the backend: "auto" or a language code; anything unsupported means "auto". */
export function resolveLanguage(setting: string | undefined, detected: Lang): Lang {
  return setting === "en" || setting === "de" ? setting : detected;
}

/** A pending low-battery notice from the backend; `language` is the stored language choice. */
export interface LowBatteryNotice {
  slot: number;
  level: number;
  language?: string;
}

// ---------------------------------------------------------------- text helpers

/** Result of a backend action; `code` and `detail` are set for failures that have a translated message. */
export interface FailureLike {
  error?: string;
  code?: string;
  detail?: string;
}

/** Text for a failed backend action: translated if the backend sent a known code, else its English text. */
export function errorText(t: Messages, failure: FailureLike): string {
  const known = failure.code ? (t.errors as Record<string, string | undefined>)[failure.code] : undefined;
  if (known) return failure.detail ? `${known}: ${failure.detail}` : known;
  return failure.error ?? t.error;
}

/** Diagnostics verdict as sent by `poweroff_unit.summarize`: a code plus parameters. */
export interface Verdict {
  code: string;
  error?: string;
  sent?: number;
  total?: number;
  option_off?: boolean;
}

export function verdictText(t: Messages, verdict: Verdict): string {
  const error = verdict.error ?? "";
  const sent = verdict.sent ?? 0;
  const total = verdict.total ?? 0;
  let text: string;
  switch (verdict.code) {
    case "install_failed":
      text = t.verdictInstallFailed(error);
      break;
    case "not_installed":
      text = t.verdictNotInstalled;
      break;
    case "not_run_yet":
      text = t.verdictNotRunYet;
      break;
    case "run_failed":
      text = t.verdictRunFailed(error);
      break;
    case "run_no_controllers":
      text = t.verdictNoControllers;
      break;
    case "run_partial":
      text = t.verdictRunPartial(sent, total, error);
      break;
    case "run_ok":
      text = t.verdictRunOk(sent, total);
      break;
    default:
      text = verdict.code;
  }
  return verdict.option_off ? text + t.optionNowOff : text;
}

/** Name of a controller type: translated by subtype number, else the backend's English name. */
export function subtypeName(t: Messages, subtype: number | null, backendName: string | null): string | null {
  if (subtype === null) return backendName;
  const known = (t.subtypes as Record<number, string | undefined>)[subtype];
  if (known) return known;
  return t.unknownSubtype(`0x${subtype.toString(16).toUpperCase().padStart(2, "0")}`);
}

/** Name of an LED mode: translated by mode number, else the backend's English description. */
export function ledModeName(t: Messages, mode: number, backendName: string): string {
  return (t.ledModes as Record<number, string | undefined>)[mode] ?? backendName;
}

/** "5 s ago", "3 min ago", "1.5 h ago", with the decimal separator of the UI language. */
export function formatAge(t: Messages, lang: Lang, seconds: number | null): string {
  if (seconds === null) return t.unknown;
  if (seconds < 90) return t.ageSeconds(Math.round(seconds));
  if (seconds < 5400) return t.ageMinutes(Math.round(seconds / 60));
  const hours = new Intl.NumberFormat(lang, { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(
    seconds / 3600,
  );
  return t.ageHours(hours);
}
