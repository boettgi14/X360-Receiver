// Decky frontend. Layout from top to bottom:
//   General (groups: Monitoring, Power) → one section per receiver → in it the connected
//   controllers as expandable cards → in them groups (Battery, Power, LED, Details).
// Every subgroup has a heading and an indented line on the left, so it is clear what a setting belongs
// to; the expanded card itself only indents. All texts come from `i18n.ts` (English and German,
// following the Steam UI language).
// The panel shows no progress or success messages, only failures; the low-battery notices are toasts.
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
import { callable, definePlugin, toaster } from "@decky/api";
import { ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import {
  FaChevronDown,
  FaEye,
  FaGamepad,
  FaLanguage,
  FaLightbulb,
  FaMoon,
  FaPowerOff,
  FaSearch,
  FaStethoscope,
  FaSyncAlt,
  FaUsb,
} from "react-icons/fa";
import {
  FailureLike,
  LowBatteryNotice,
  MESSAGES,
  Messages,
  Verdict,
  detectLanguage,
  errorText,
  formatAge,
  ledModeName,
  resolveLanguage,
  subtypeName,
  verdictText,
} from "./i18n";

// ---------------------------------------------------------------- Types

interface Controller {
  slot: number;
  detected_by: string[];
  led: string | null;
  headset: boolean;
  chatpad: boolean;
  subtype: number | null;
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
  unofficial: boolean;
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
    startup_query: boolean;
    low_battery_toast: boolean;
    language: string;
  };
  monitor: { enabled: boolean; setup_error: string | null; readers: Record<string, { error: string | null }> };
  receivers: Receiver[];
  led_modes: Record<string, string>;
  diagnostics: { verdict: Verdict; lines: { key: string; value: string }[] } | null;
}

interface Result extends FailureLike {
  ok: boolean;
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
const setStartupQuery = callable<[enabled: boolean], Result>("set_startup_query");
const setLowBatteryToast = callable<[enabled: boolean], Result>("set_low_battery_toast");
const setLanguage = callable<[language: string], Result>("set_language");
const takeLowBatteryNotices = callable<[], LowBatteryNotice[]>("take_low_battery_notices");
const findController = callable<[bus: number, devnum: number, slot: number], Result>("find_controller");
const powerOffAll = callable<[], PowerOffAllResult>("power_off_all");
const setLed = callable<[name: string, mode: number], Result>("set_led");
const resetLed = callable<[name: string], Result>("reset_led");
const queryBattery = callable<[bus: number, devnum: number, slot: number], BatteryResult>("query_battery");
const powerOff = callable<[bus: number, devnum: number, slot: number], PowerOffResult>("power_off");

// ---------------------------------------------------------------- Helpers

const LEVEL_COLORS = ["#ff5d5d", "#ff5d5d", "#ffb020", "#4cc38a"]; // level 0..3
const MUTED = "rgba(255,255,255,0.35)";
const LINE = "rgba(255,255,255,0.14)";

function levelText(t: Messages, level: number | null): string {
  return level === null ? "–" : t.level(level);
}

/** Typical battery bar: frame with a terminal, three segments; the color follows the level. */
function BatteryBar({ level, t }: { level: number | null; t: Messages }) {
  const color = level === null ? MUTED : (LEVEL_COLORS[level] ?? MUTED);
  const filled = level ?? 0;
  const width = 48;
  const height = 20;
  return (
    <div
      role="img"
      aria-label={level === null ? t.batteryLevelUnknown : t.batteryLevelLabel(level)}
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

/** Subgroup with a heading; the line on the left shows what belongs to it. */
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
    <Field label={label} focusable bottomSeparator="none" padding="compact" childrenLayout="inline">
      <span style={{ opacity: 0.85 }}>{value}</span>
    </Field>
  );
}

/** Shows a notification toast. Used for low-battery notices and for the test button. */
function showToast(t: Messages, body: string) {
  toaster.toast({ title: t.lowBatteryTitle, body, icon: <FaGamepad /> });
}

function describeController(t: Messages, c: Controller): string {
  const parts = [subtypeName(t, c.subtype, c.subtype_name) ?? t.controllerGeneric];
  if (c.headset) parts.push(t.headset);
  if (c.chatpad) parts.push(t.chatpad);
  return parts.join(" · ");
}

// ---------------------------------------------------------------- UI

function Content() {
  const [status, setStatus] = useState<Status | null>(null);
  const [message, setMessage] = useState<{ text: string; error: boolean } | null>(null);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState<boolean>(false);
  const detected = useMemo(() => detectLanguage(), []);
  const lang = resolveLanguage(status?.settings.language, detected); // the user's choice wins over Steam's language
  const t = MESSAGES[lang];

  const refresh = useCallback(async () => {
    try {
      setStatus(await getStatus());
    } catch (e) {
      setMessage({ text: t.backendUnreachable(String(e)), error: true });
    }
  }, [t]);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 2000);
    return () => clearInterval(timer);
  }, [refresh]);

  const say = (text: string, error = false) => setMessage({ text, error });
  const sayFailure = (failure: FailureLike) => say(errorText(t, failure), true);
  const report = (result: Result) => {
    if (!result.ok) sayFailure(result);
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
      const result = await queryBattery(bus, devnum, slot);
      if (!result.ok) sayFailure(result); // the new level shows in the card; no message on success
    });

  const runFind = (bus: number, devnum: number, slot: number) =>
    guarded(async () => {
      const result = await findController(bus, devnum, slot);
      if (!result.ok) sayFailure(result);
    });

  const confirmPowerOff = (bus: number, devnum: number, slot: number) =>
    showModal(
      <ConfirmModal
        strTitle={t.turnOffTitle(slot + 1)}
        strDescription={t.turnOffText}
        strOKButtonText={t.turnOffButton}
        onOK={() =>
          guarded(async () => {
            const result = await powerOff(bus, devnum, slot);
            if (!result.ok) sayFailure(result);
            else if (!result.confirmed) say(t.turnOffUnconfirmed(slot + 1), true);
          })
        }
      />,
    );

  const confirmPowerOffAll = () =>
    showModal(
      <ConfirmModal
        strTitle={t.turnOffAllTitle}
        strDescription={t.turnOffAllText}
        strOKButtonText={t.turnOffAllButton}
        onOK={() =>
          guarded(async () => {
            const result = await powerOffAll();
            // The error details come from the backend as English technical text.
            if (result.errors.length > 0) say(t.turnOffAllProblem(result.errors.join(" | ")), true);
          })
        }
      />,
    );

  if (status === null) {
    return <PanelSection title="X360 Receiver">{message ? message.text : t.loading}</PanelSection>;
  }

  const modeOptions = Object.entries(status.led_modes).map(([key, label]) => ({
    data: Number(key),
    label: `${key}: ${ledModeName(t, Number(key), label)}`,
  }));
  const readerErrors = Object.entries(status.monitor.readers).filter(([, r]) => r.error);
  const monitorOn = status.settings.monitor_enabled;

  const ledControls = (name: string, current: number | null) => (
    <>
      <PanelSectionRow>
        <DropdownItem
          label={t.ledPattern(name)}
          rgOptions={modeOptions}
          selectedOption={current}
          onChange={async (option: { data: number }) => report(await setLed(name, option.data))}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={async () => report(await resetLed(name))}>
          {t.ledReset}
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
      c.state_age_s === null ? (monitorOn ? t.notReportedYet : t.unknown) : formatAge(t, lang, c.state_age_s);
    const freshNote =
      c.state_age_s === null && !monitorOn
        ? t.freshnessMonitorOff(t.queryBattery)
        : c.state_source === "link"
          ? t.freshnessFromLink
          : undefined;
    return (
      <div key={key}>
        <PanelSectionRow>
          <Field
            icon={<FaGamepad />}
            label={t.controllerN(c.slot + 1)}
            description={describeController(t, c)}
            focusable
            bottomSeparator="none"
            onActivate={() => toggleOpen(key)}
            onClick={() => toggleOpen(key)}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <BatteryBar level={c.battery_level} t={t} />
              <span style={{ minWidth: 64, textAlign: "right", whiteSpace: "nowrap" }}>{levelText(t, c.battery_level)}</span>
              <Chevron open={isOpen} />
            </div>
          </Field>
        </PanelSectionRow>

        {isOpen && (
          <div style={{ margin: "0 0 10px 14px" }}>
            <Group title={t.groupBattery} icon={<FaSyncAlt />}>
              <PanelSectionRow>
                <Field label={t.lastReport} description={freshNote} bottomSeparator="none" childrenLayout="inline">
                  <span style={{ opacity: 0.85, whiteSpace: "nowrap" }}>{fresh}</span>
                </Field>
              </PanelSectionRow>
              <PanelSectionRow>
                <ButtonItem
                  layout="below"
                  disabled={busy}
                  description={t.queryBatteryHint}
                  onClick={() => runBattery(bus, devnum, c.slot)}
                >
                  {t.queryBattery}
                </ButtonItem>
              </PanelSectionRow>
            </Group>

            <Group title={t.groupPower} icon={<FaPowerOff />}>
              <PanelSectionRow>
                <ButtonItem layout="below" disabled={busy} onClick={() => confirmPowerOff(bus, devnum, c.slot)}>
                  {t.turnOffController}
                </ButtonItem>
              </PanelSectionRow>
            </Group>

            <Group title={t.groupIdentify} icon={<FaSearch />}>
              <PanelSectionRow>
                <ButtonItem
                  layout="below"
                  disabled={busy}
                  description={t.findControllerHint}
                  onClick={() => runFind(bus, devnum, c.slot)}
                >
                  {t.findController}
                </ButtonItem>
              </PanelSectionRow>
            </Group>

            {c.led !== null && (
              <Group title={t.groupLed} icon={<FaLightbulb />}>
                {ledControls(c.led, c.last_led_mode)}
              </Group>
            )}

            <Group title={t.groupDetails}>
              <Detail label={t.detailSlot} value={String(c.slot + 1)} />
              <Detail label={t.detailType} value={subtypeName(t, c.subtype, c.subtype_name) ?? t.unknown} />
              <Detail label={t.detailHeadset} value={c.headset ? t.yes : t.no} />
              <Detail label={t.detailChatpad} value={c.chatpad ? t.yes : t.no} />
              <Detail
                label={t.detailDetectedVia}
                value={c.detected_by.map((s) => (s === "monitor" ? t.viaMonitor : t.viaSystem)).join(", ")}
              />
            </Group>
          </div>
        )}
      </div>
    );
  };

  const receiverSection = (r: Receiver, index: number) => {
    const known = r.bus !== null && r.devnum !== null;
    const where = known ? ` · ${t.busDevice(r.bus as number, r.devnum as number)}` : "";
    return (
      <PanelSection key={r.usb_path} title={t.receiverN(index + 1)}>
        <PanelSectionRow>
          <Field
            icon={<FaUsb />}
            label={r.unofficial ? `${r.label} · ${t.unofficial}` : r.label}
            description={`USB ${r.usb_path}${where} · ${t.slotsInUse(r.controllers.length, r.slot_count)}`}
            bottomSeparator="none"
          />
        </PanelSectionRow>

        <Group title={t.groupControllers} icon={<FaGamepad />}>
          {r.controllers.length === 0 && r.unlocated_count === 0 && (
            <PanelSectionRow>
              <Field label={t.noControllerConnected} bottomSeparator="none" />
            </PanelSectionRow>
          )}
          {r.unlocated_count > 0 && (
            <PanelSectionRow>
              <Field
                label={t.moreControllers(r.unlocated_count)}
                description={t.moreControllersHint(t.monitorToggle)}
                bottomSeparator="none"
              />
            </PanelSectionRow>
          )}
          {known && r.controllers.map((c) => controllerCard(r, c))}
        </Group>

        {r.unassigned_leds.length > 0 && (
          <Group title={t.groupReceiverLeds} icon={<FaLightbulb />}>
            <PanelSectionRow>
              <Field label={t.ledUnassigned} description={t.ledUnassignedHint} bottomSeparator="none" />
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
              description={t.dismissHint}
            />
          </PanelSectionRow>
        </PanelSection>
      )}

      <PanelSection title={t.general}>
        <Group title={t.groupMonitoring} icon={<FaEye />}>
          <PanelSectionRow>
            <ToggleField
              label={t.monitorToggle}
              description={t.monitorToggleHint}
              checked={monitorOn}
              onChange={async (value: boolean) => {
                report(await setMonitorEnabled(value));
                refresh();
              }}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <ToggleField
              label={t.startupQueryToggle}
              description={t.startupQueryHint}
              checked={status.settings.startup_query}
              onChange={async (value: boolean) => {
                report(await setStartupQuery(value));
                refresh();
              }}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <ToggleField
              label={t.lowBatteryToggle}
              description={t.lowBatteryHint}
              checked={status.settings.low_battery_toast}
              onChange={async (value: boolean) => {
                report(await setLowBatteryToast(value));
                refresh();
              }}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              description={t.testNotificationHint}
              onClick={() => showToast(t, t.testNotificationBody)}
            >
              {t.testNotification}
            </ButtonItem>
          </PanelSectionRow>
          {status.monitor.setup_error && (
            <PanelSectionRow>
              <Field label={t.monitorCannotStart} description={status.monitor.setup_error} bottomSeparator="none" />
            </PanelSectionRow>
          )}
          {readerErrors.map(([bus, reader]) => (
            <PanelSectionRow key={bus}>
              <Field label={t.busN(bus)} description={reader.error ?? ""} bottomSeparator="none" />
            </PanelSectionRow>
          ))}
        </Group>

        <Group title={t.groupPower} icon={<FaMoon />}>
          {status.settings.auto_poweroff === null ? (
            <PanelSectionRow>
              <Field label={t.standbyUnavailable} description={t.standbyUnavailableHint} bottomSeparator="none" />
            </PanelSectionRow>
          ) : (
            <PanelSectionRow>
              <ToggleField
                label={t.standbyToggle}
                description={t.standbyHint}
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
              label={t.shutdownToggle}
              description={t.shutdownHint}
              checked={status.settings.poweroff_on_shutdown}
              onChange={async (value: boolean) => {
                report(await setPoweroffOnShutdown(value));
                refresh();
              }}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={busy} description={t.turnOffAllNowHint} onClick={confirmPowerOffAll}>
              {t.turnOffAllNow}
            </ButtonItem>
          </PanelSectionRow>
        </Group>

        <Group title={t.groupLanguage} icon={<FaLanguage />}>
          <PanelSectionRow>
            <DropdownItem
              label={t.languageSetting}
              description={t.languageHint}
              rgOptions={[
                { data: "auto", label: t.languageAuto },
                { data: "en", label: t.languageEnglish },
                { data: "de", label: t.languageGerman },
              ]}
              selectedOption={status.settings.language}
              onChange={async (option: { data: string }) => {
                report(await setLanguage(option.data));
                refresh();
              }}
            />
          </PanelSectionRow>
        </Group>

        {status.diagnostics !== null && (
          <Group title={t.groupDiagnostics} icon={<FaStethoscope />}>
            <PanelSectionRow>
              <Field
                label={t.shutdownService}
                description={verdictText(t, status.diagnostics.verdict)}
                focusable
                bottomSeparator="none"
                onActivate={() => toggleOpen("diagnostics")}
                onClick={() => toggleOpen("diagnostics")}
              >
                <Chevron open={open["diagnostics"] === true} />
              </Field>
            </PanelSectionRow>
            {open["diagnostics"] === true && (
              <div style={{ marginLeft: 14 }}>
                {status.diagnostics.lines.map((line, i) => (
                  <PanelSectionRow key={i}>
                    <Field
                      label={(t.diagnosticLines as Record<string, string | undefined>)[line.key] ?? line.key}
                      focusable
                      bottomSeparator="none"
                      padding="compact"
                      childrenLayout="below"
                    >
                      <div style={{ fontFamily: "monospace", fontSize: 11, opacity: 0.8, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                        {line.value}
                      </div>
                    </Field>
                  </PanelSectionRow>
                ))}
              </div>
            )}
          </Group>
        )}
      </PanelSection>

      {status.receivers.length === 0 ? (
        <PanelSection title={t.receiverTitle}>
          <PanelSectionRow>
            <Field label={t.noReceiver} description={t.noReceiverHint} bottomSeparator="none" />
          </PanelSectionRow>
        </PanelSection>
      ) : (
        status.receivers.map(receiverSection)
      )}
    </>
  );
}

/** Low-battery notices are pulled from the backend and shown as toasts, also while the panel is closed. */
export default definePlugin(() => {
  const showNotices = async () => {
    try {
      const notices = await takeLowBatteryNotices();
      if (!Array.isArray(notices)) return;
      for (const notice of notices) {
        const t = MESSAGES[resolveLanguage(notice.language, detectLanguage())];
        showToast(t, t.lowBatteryBody(notice.slot + 1, notice.level));
      }
    } catch {
      // The backend may not be ready yet; the next poll tries again.
    }
  };
  const firstPoll = setTimeout(showNotices, 3000);
  const timer = setInterval(showNotices, 10000);
  return {
    name: "X360 Receiver",
    titleView: <div className={staticClasses.Title}>X360 Receiver</div>,
    content: <Content />,
    icon: <FaGamepad />,
    onDismount() {
      clearTimeout(firstPoll);
      clearInterval(timer);
    },
  };
});
