// Decky-Frontend. Aufbau von oben nach unten:
//   Allgemein (Gruppen: Überwachung, Energie) → je Receiver ein Abschnitt → darin die verbundenen
//   Controller als ausklappbare Karten → darin Gruppen (Akku, Energie, LED, Details).
// Jede Untergruppe hat eine Überschrift und eine Einrückung mit Linie links, damit klar ist, wozu eine
// Einstellung gehört. Am Gerät nie gerendert; gebaut und typgeprüft wird nur in einer Testkopie.
import {
  ButtonItem,
  ConfirmModal,
  DropdownItem,
  Field,
  PanelSection,
  PanelSectionRow,
  ToggleField,
  showModal,
  staticClasses,
} from "@decky/ui";
import { callable, definePlugin } from "@decky/api";
import { ReactNode, useCallback, useEffect, useState } from "react";
import {
  FaChevronDown,
  FaEye,
  FaGamepad,
  FaLightbulb,
  FaMoon,
  FaPowerOff,
  FaStethoscope,
  FaSyncAlt,
  FaUsb,
} from "react-icons/fa";

// ---------------------------------------------------------------- Typen

interface Controller {
  slot: number;
  detected_by: string[];
  led: string | null;
  headset: boolean;
  chatpad: boolean;
  subtype_name: string | null;
  battery_level: number | null;
  state_age_s: number | null;
  state_source: string | null;
  connected_age_s: number | null;
  last_led_mode: number | null;
}

interface Receiver {
  usb_path: string;
  label: string;
  bus: number | null;
  devnum: number | null;
  controllers: Controller[];
  unassigned_leds: string[];
  unlocated_count: number;
  slot_count: number;
}

interface Status {
  settings: {
    monitor_enabled: boolean;
    auto_poweroff: boolean | null;
    poweroff_on_shutdown: boolean;
  };
  monitor: { enabled: boolean; setup_error: string | null; readers: Record<string, { error: string | null }> };
  receivers: Receiver[];
  led_modes: Record<string, string>;
  diagnostics: { verdict: string; lines: string[] } | null;
}

interface Result {
  ok: boolean;
  error?: string;
}

interface BatteryResult extends Result {
  state?: { battery_level: number; power_state_raw: number } | null;
}

interface PowerOffResult extends Result {
  confirmed?: boolean;
}

interface PowerOffAllResult {
  ok: boolean;
  sent: number;
  confirmed: number;
  errors: string[];
}

const getStatus = callable<[], Status>("get_status");
const setMonitorEnabled = callable<[enabled: boolean], Result>("set_monitor_enabled");
const setAutoPoweroff = callable<[enabled: boolean], Result>("set_auto_poweroff");
const setPoweroffOnShutdown = callable<[enabled: boolean], Result>("set_poweroff_on_shutdown");
const powerOffAll = callable<[], PowerOffAllResult>("power_off_all");
const setLed = callable<[name: string, mode: number], Result>("set_led");
const resetLed = callable<[name: string], Result>("reset_led");
const queryBattery = callable<[bus: number, devnum: number, slot: number], BatteryResult>("query_battery");
const powerOff = callable<[bus: number, devnum: number, slot: number], PowerOffResult>("power_off");

// ---------------------------------------------------------------- Hilfen

const LEVEL_COLORS = ["#ff5d5d", "#ff5d5d", "#ffb020", "#4cc38a"]; // Stufe 0..3
const MUTED = "rgba(255,255,255,0.35)";
const LINE = "rgba(255,255,255,0.14)";

function formatAge(seconds: number | null): string {
  if (seconds === null) return "unbekannt";
  if (seconds < 90) return `vor ${Math.round(seconds)} s`;
  if (seconds < 5400) return `vor ${Math.round(seconds / 60)} min`;
  return `vor ${(seconds / 3600).toFixed(1)} h`;
}

function levelText(level: number | null): string {
  return level === null ? "–" : `Stufe ${level}/3`;
}

/** Typischer Akkubalken: Rahmen mit Pol, drei Segmente; die Farbe folgt der Stufe. */
function BatteryBar({ level }: { level: number | null }) {
  const color = level === null ? MUTED : (LEVEL_COLORS[level] ?? MUTED);
  const filled = level ?? 0;
  const width = 48;
  const height = 20;
  return (
    <div
      role="img"
      aria-label={level === null ? "Akkustand unbekannt" : `Akkustufe ${level} von 3`}
      style={{ display: "flex", alignItems: "center", flexShrink: 0 }}
    >
      <div
        style={{
          display: "flex",
          gap: 2,
          padding: 2,
          width,
          height,
          boxSizing: "border-box",
          border: `2px solid ${color}`,
          borderRadius: 5,
        }}
      >
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            style={{ flex: 1, borderRadius: 2, background: i <= filled && level !== null ? color : "rgba(255,255,255,0.1)" }}
          />
        ))}
      </div>
      <div style={{ width: 3, height: height * 0.4, marginLeft: 1, borderRadius: "0 2px 2px 0", background: color }} />
    </div>
  );
}

/** Untergruppe mit Überschrift; die Linie links zeigt, was dazugehört. */
function Group({ title, icon, children }: { title: string; icon?: ReactNode; children: ReactNode }) {
  return (
    <div style={{ margin: "10px 0 6px 0" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          fontSize: 12,
          fontWeight: 600,
          letterSpacing: "0.06em",
          textTransform: "uppercase",
          opacity: 0.75,
          padding: "0 0 4px 2px",
        }}
      >
        {icon}
        <span>{title}</span>
      </div>
      <div style={{ borderLeft: `2px solid ${LINE}`, paddingLeft: 10, marginLeft: 4 }}>{children}</div>
    </div>
  );
}

function Chevron({ open }: { open: boolean }) {
  return (
    <FaChevronDown
      style={{ transition: "transform 0.15s", transform: open ? "none" : "rotate(-90deg)", opacity: 0.8 }}
    />
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <Field label={label} bottomSeparator="none" padding="compact" childrenLayout="inline">
      <span style={{ opacity: 0.85 }}>{value}</span>
    </Field>
  );
}

function describeController(c: Controller): string {
  const parts = [c.subtype_name ?? "Controller"];
  if (c.headset) parts.push("Headset");
  if (c.chatpad) parts.push("Chatpad");
  return parts.join(" · ");
}

// ---------------------------------------------------------------- Oberfläche

function Content() {
  const [status, setStatus] = useState<Status | null>(null);
  const [message, setMessage] = useState<{ text: string; error: boolean } | null>(null);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState<boolean>(false);

  const refresh = useCallback(async () => {
    try {
      setStatus(await getStatus());
    } catch (e) {
      setMessage({ text: `Backend nicht erreichbar: ${String(e)}`, error: true });
    }
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 2000);
    return () => clearInterval(timer);
  }, [refresh]);

  const say = (text: string, error = false) => setMessage({ text, error });
  const report = (result: Result) => {
    if (!result.ok) say(result.error ?? "Fehler", true);
  };
  const toggleOpen = (key: string) => setOpen((o) => ({ ...o, [key]: !o[key] }));

  const guarded = async (action: () => Promise<void>) => {
    setBusy(true);
    try {
      await action();
    } finally {
      setBusy(false);
      refresh();
    }
  };

  const runBattery = (bus: number, devnum: number, slot: number) =>
    guarded(async () => {
      say(`Controller ${slot + 1}: frage Akku ab …`);
      const result = await queryBattery(bus, devnum, slot);
      if (!result.ok) say(result.error ?? "Fehler", true);
      else if (!result.state) say(`Controller ${slot + 1}: keine Antwort (aus oder nicht verbunden?)`, true);
      else say(`Controller ${slot + 1}: Akku ${levelText(result.state.battery_level)}, soeben abgefragt`);
    });

  const confirmPowerOff = (bus: number, devnum: number, slot: number) =>
    showModal(
      <ConfirmModal
        strTitle={`Controller ${slot + 1} ausschalten?`}
        strDescription="Der Controller geht aus und muss mit der Guide-Taste wieder eingeschaltet werden."
        strOKButtonText="Ausschalten"
        onOK={() =>
          guarded(async () => {
            const result = await powerOff(bus, devnum, slot);
            if (!result.ok) say(result.error ?? "Fehler", true);
            else if (result.confirmed) say(`Controller ${slot + 1}: ausgeschaltet`);
            else say(`Controller ${slot + 1}: Befehl gesendet, keine Bestätigung (war evtl. schon aus)`, true);
          })
        }
      />,
    );

  const confirmPowerOffAll = () =>
    showModal(
      <ConfirmModal
        strTitle="Alle Controller ausschalten?"
        strDescription="Alle verbundenen Controller an allen Receivern gehen aus. Derselbe Ablauf wie beim Herunterfahren."
        strOKButtonText="Alle ausschalten"
        onOK={() =>
          guarded(async () => {
            say("Schalte Controller aus …");
            const result = await powerOffAll();
            if (result.errors.length > 0) say(result.errors.join(" | "), true);
            else if (result.sent === 0) say("Kein verbundener Controller gefunden");
            else say(`${result.sent} Controller ausgeschaltet (${result.confirmed} bestätigt)`);
          })
        }
      />,
    );

  if (status === null) {
    return <PanelSection title="X360 Receiver">{message ? message.text : "Lade …"}</PanelSection>;
  }

  const modeOptions = Object.entries(status.led_modes).map(([key, label]) => ({
    data: Number(key),
    label: `${key}: ${label}`,
  }));
  const readerErrors = Object.entries(status.monitor.readers).filter(([, r]) => r.error);
  const monitorOn = status.settings.monitor_enabled;

  const ledControls = (name: string, current: number | null) => (
    <>
      <PanelSectionRow>
        <DropdownItem
          label={`LED-Muster (${name})`}
          rgOptions={modeOptions}
          selectedOption={current}
          onChange={async (option: { data: number }) => report(await setLed(name, option.data))}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={async () => report(await resetLed(name))}>
          Auf Standard zurücksetzen
        </ButtonItem>
      </PanelSectionRow>
    </>
  );

  const controllerCard = (r: Receiver, c: Controller) => {
    const bus = r.bus as number;
    const devnum = r.devnum as number;
    const key = `${bus}-${devnum}-${c.slot}`;
    const isOpen = open[key] === true;
    const fresh =
      c.state_age_s === null ? (monitorOn ? "noch nicht gemeldet" : "unbekannt") : formatAge(c.state_age_s);
    const freshNote =
      c.state_age_s === null && !monitorOn
        ? "Die Überwachung ist aus. Der Akkustand wird beim Start des Plugins und mit „Akku jetzt abfragen“ ermittelt, nicht laufend."
        : c.state_source === "link"
          ? "Aus der Verbindungsmeldung; wie frisch der Wert ist, ist unklar."
          : undefined;
    return (
      <div key={key}>
        <PanelSectionRow>
          <Field
            icon={<FaGamepad />}
            label={`Controller ${c.slot + 1}`}
            description={describeController(c)}
            focusable
            bottomSeparator="none"
            onActivate={() => toggleOpen(key)}
            onClick={() => toggleOpen(key)}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <BatteryBar level={c.battery_level} />
              <span style={{ minWidth: 64, textAlign: "right", whiteSpace: "nowrap" }}>{levelText(c.battery_level)}</span>
              <Chevron open={isOpen} />
            </div>
          </Field>
        </PanelSectionRow>

        {isOpen && (
          <div style={{ borderLeft: `3px solid ${LINE}`, margin: "0 0 10px 14px", paddingLeft: 6 }}>
            <Group title="Akku" icon={<FaSyncAlt />}>
              <PanelSectionRow>
                <Field label="Letzte Meldung" description={freshNote} bottomSeparator="none" childrenLayout="inline">
                  <span style={{ opacity: 0.85, whiteSpace: "nowrap" }}>{fresh}</span>
                </Field>
              </PanelSectionRow>
              <PanelSectionRow>
                <ButtonItem
                  layout="below"
                  disabled={busy}
                  description="Der Controller verschwindet dafür ca. 3 Sekunden. Nicht im Spiel benutzen."
                  onClick={() => runBattery(bus, devnum, c.slot)}
                >
                  Akku jetzt abfragen
                </ButtonItem>
              </PanelSectionRow>
            </Group>

            <Group title="Energie" icon={<FaPowerOff />}>
              <PanelSectionRow>
                <ButtonItem layout="below" disabled={busy} onClick={() => confirmPowerOff(bus, devnum, c.slot)}>
                  Controller ausschalten
                </ButtonItem>
              </PanelSectionRow>
            </Group>

            {c.led !== null && (
              <Group title="LED" icon={<FaLightbulb />}>
                {ledControls(c.led, c.last_led_mode)}
              </Group>
            )}

            <Group title="Details">
              <Detail label="Slot am Receiver" value={String(c.slot + 1)} />
              <Detail label="Typ" value={c.subtype_name ?? "unbekannt"} />
              <Detail label="Headset" value={c.headset ? "ja" : "nein"} />
              <Detail label="Chatpad" value={c.chatpad ? "ja" : "nein"} />
              <Detail label="Erkannt über" value={c.detected_by.map((s) => (s === "monitor" ? "Überwachung" : "System")).join(", ")} />
            </Group>
          </div>
        )}
      </div>
    );
  };

  const receiverSection = (r: Receiver, index: number) => {
    const known = r.bus !== null && r.devnum !== null;
    return (
      <PanelSection key={r.usb_path} title={`Receiver ${index + 1}`}>
        <PanelSectionRow>
          <Field
            icon={<FaUsb />}
            label={r.label}
            description={`USB ${r.usb_path}${known ? ` · Bus ${r.bus}, Gerät ${r.devnum}` : ""} · ${r.controllers.length} von ${r.slot_count} Slots belegt`}
            bottomSeparator="none"
          />
        </PanelSectionRow>

        <Group title="Controller" icon={<FaGamepad />}>
          {r.controllers.length === 0 && r.unlocated_count === 0 && (
            <PanelSectionRow>
              <Field label="Kein Controller verbunden" bottomSeparator="none" />
            </PanelSectionRow>
          )}
          {r.unlocated_count > 0 && (
            <PanelSectionRow>
              <Field
                label={`${r.unlocated_count} weiterer Controller verbunden`}
                description="Der Slot wurde nicht erkannt. Mit „Akku-Status mitlesen“ (oben) erscheint er hier."
                bottomSeparator="none"
              />
            </PanelSectionRow>
          )}
          {known && r.controllers.map((c) => controllerCard(r, c))}
        </Group>

        {r.unassigned_leds.length > 0 && (
          <Group title="LEDs dieses Receivers" icon={<FaLightbulb />}>
            <PanelSectionRow>
              <Field
                label="Zuordnung nicht möglich"
                description="Die Zahl der LEDs passt nicht zur Zahl der erkannten Controller (xpad0 ist Controller 1, xpad1 Controller 2 usw.)."
                bottomSeparator="none"
              />
            </PanelSectionRow>
            {r.unassigned_leds.map((name) => (
              <div key={name}>{ledControls(name, null)}</div>
            ))}
          </Group>
        )}
      </PanelSection>
    );
  };

  return (
    <>
      {message && (
        <PanelSection>
          <PanelSectionRow>
            <Field
              label={<span style={{ color: message.error ? "#ff8a8a" : undefined }}>{message.text}</span>}
              bottomSeparator="none"
              focusable
              onActivate={() => setMessage(null)}
              onClick={() => setMessage(null)}
              description="Zum Ausblenden auswählen"
            />
          </PanelSectionRow>
        </PanelSection>
      )}

      <PanelSection title="Allgemein">
        <Group title="Überwachung" icon={<FaEye />}>
          <PanelSectionRow>
            <ToggleField
              label="Akku-Status mitlesen"
              description="Liest den USB-Verkehr der Receiver mit (usbmon), um Akkustand und Verbindungen zu zeigen. Gespeichert werden nur Status und Zähler, nie Tastendrücke."
              checked={monitorOn}
              onChange={async (value: boolean) => {
                report(await setMonitorEnabled(value));
                refresh();
              }}
            />
          </PanelSectionRow>
          {status.monitor.setup_error && (
            <PanelSectionRow>
              <Field label="Monitor nicht startbar" description={status.monitor.setup_error} bottomSeparator="none" />
            </PanelSectionRow>
          )}
          {readerErrors.map(([bus, reader]) => (
            <PanelSectionRow key={bus}>
              <Field label={`Bus ${bus}`} description={reader.error ?? ""} bottomSeparator="none" />
            </PanelSectionRow>
          ))}
        </Group>

        <Group title="Energie" icon={<FaMoon />}>
          {status.settings.auto_poweroff === null ? (
            <PanelSectionRow>
              <Field
                label="Standby-Ausschalten nicht verfügbar"
                description="Der Kernelparameter xpad.auto_poweroff ist nicht lesbar (Treiber xpad geladen?)."
                bottomSeparator="none"
              />
            </PanelSectionRow>
          ) : (
            <PanelSectionRow>
              <ToggleField
                label="Beim Standby ausschalten"
                description="Alle Controller gehen aus, wenn das Gerät in den Standby geht. Gilt für alle Receiver."
                checked={status.settings.auto_poweroff}
                onChange={async (value: boolean) => {
                  report(await setAutoPoweroff(value));
                  refresh();
                }}
              />
            </PanelSectionRow>
          )}
          <PanelSectionRow>
            <ToggleField
              label="Beim Herunterfahren ausschalten"
              description="Alle Controller gehen aus, wenn das Gerät herunterfährt oder neu startet. Gilt für alle Receiver. Richtet dafür einen kleinen Systemdienst ein, der beim Ausschalten der Option und beim Entfernen des Plugins wieder gelöscht wird."
              checked={status.settings.poweroff_on_shutdown}
              onChange={async (value: boolean) => {
                report(await setPoweroffOnShutdown(value));
                refresh();
              }}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              disabled={busy}
              description="Gleicher Ablauf wie beim Herunterfahren, zum Ausprobieren."
              onClick={confirmPowerOffAll}
            >
              Alle Controller jetzt ausschalten
            </ButtonItem>
          </PanelSectionRow>
        </Group>

        {status.diagnostics !== null && (
          <Group title="Diagnose" icon={<FaStethoscope />}>
            <PanelSectionRow>
              <Field
                label="Dienst beim Herunterfahren"
                description={status.diagnostics.verdict}
                focusable
                bottomSeparator="none"
                onActivate={() => toggleOpen("diagnostics")}
                onClick={() => toggleOpen("diagnostics")}
              >
                <Chevron open={open["diagnostics"] === true} />
              </Field>
            </PanelSectionRow>
            {open["diagnostics"] === true &&
              status.diagnostics.lines.map((line, i) => (
                <PanelSectionRow key={i}>
                  <div style={{ fontFamily: "monospace", fontSize: 11, opacity: 0.8, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                    {line}
                  </div>
                </PanelSectionRow>
              ))}
          </Group>
        )}
      </PanelSection>

      {status.receivers.length === 0 ? (
        <PanelSection title="Receiver">
          <PanelSectionRow>
            <Field label="Kein Xbox-360-Receiver gefunden" description="USB-Dongle einstecken." bottomSeparator="none" />
          </PanelSectionRow>
        </PanelSection>
      ) : (
        status.receivers.map(receiverSection)
      )}
    </>
  );
}

export default definePlugin(() => ({
  name: "X360 Receiver",
  titleView: <div className={staticClasses.Title}>X360 Receiver</div>,
  content: <Content />,
  icon: <FaGamepad />,
  onDismount() {},
}));
