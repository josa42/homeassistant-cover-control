/**
 * Dashboard strategy for the Cover Control integration.
 *
 * Generates the whole dashboard from the entity registry at render time, so
 * covers added later show up without anyone editing a dashboard. Two views:
 * an overview with the controls, and a debug view that lays out the decision
 * record behind every cover.
 *
 * Use it with:
 *
 *   strategy:
 *     type: custom:cover-control
 */

const DOMAIN = "cover_control";

const LABELS = {
  en: {
    overview: "Overview",
    debug: "Debug",
    control: "Control",
    noEntities: [
      "## Cover Control is not set up yet",
      "",
      "Add the integration under **Settings → Devices & Services**, then add a",
      "cover to it. This dashboard fills itself in automatically.",
    ].join("\n"),
    decision: "Decision",
    reason: "Reason",
    target: "Target",
    didMove: "moved it",
    wouldMoveNow: "would move it",
    nothingToDo: "nothing to do",
    blockedBy: "Blocked by",
    sun: "Sun",
    evPaused: "paused",
    evResumed: "resumed",
    evOverride: "moved by hand to",
    evSlats: "slats",
    covers: "Covers",
    details: "Details",
    noCoverNeeded: "no cover needed",
    ofAllowed: "of",
    allowed: "allowed",
    weatherWords: {
    },
    intent: "Intent",
    goal: "Goal",
    fullyOpen: "fully open",
    fullyShut: "fully shut",
    slats: "slats",
    criteria: "Conditions",
    actionsToday: "Sent today",
    noActions: "Nothing sent today.",
    cSun: "Sun on the window",
    cSunNo: "sun is not on this window",
    cBright: "Bright enough",
    cTemp: "Temperature calls for it",
    cWindow: "Window closed",
    cStorm: "No storm",
    cPaused: "Not paused",
    cOverride: "Not moved by hand",
    cEnabled: "Switched on",
    reaches: "reaches",
    notOnThisWindow: "not on this window",
    intoRoom: "into the room",
    readings: "Readings",
    outIn: "out/in",
    episodeLabel: "Episode",
    episodeRunning: "running",
    episodeIdle: "none",
    brightness: "Brightness",
    brightYes: "bright enough",
    brightNo: "not bright enough",
    brightUnknown: "not reached, an earlier gate decided",
    weatherAllowed: "counts as bright",
    weatherNotAllowed: "does not count as bright",
    pvOverriding: "PV overrides the weather",
    pvOverrideIn: "PV overrides the weather in",
    pvOverrideMinutes: "min, if it stays this high.",
    coversTotal: "Covers configured",
    coversShading: "Shading",
    coversHeating: "Solar heating",
    coversOverridden: "Manually overridden",
    coversPaused: "Paused",
    coversStorm: "Storm protection",
    enabled: "Enabled",
    dryRunNotice: "**Dry run.** Nothing is being moved; this is what would happen.",
  },
  de: {
    overview: "Übersicht",
    debug: "Debug",
    control: "Steuerung",
    noEntities: [
      "## Cover Control ist noch nicht eingerichtet",
      "",
      "Füge die Integration unter **Einstellungen → Geräte & Dienste** hinzu und",
      "danach einen Rollladen. Dieses Dashboard füllt sich dann von selbst.",
    ].join("\n"),
    decision: "Entscheidung",
    reason: "Grund",
    target: "Ziel",
    didMove: "bewegt",
    wouldMoveNow: "würde bewegen",
    nothingToDo: "nichts zu tun",
    blockedBy: "Blockiert durch",
    sun: "Sonne",
    evPaused: "pausiert",
    evResumed: "fortgesetzt",
    evOverride: "von Hand bewegt auf",
    evSlats: "Lamellen",
    covers: "Rollläden",
    details: "Details",
    noCoverNeeded: "kein Behang nötig",
    ofAllowed: "von",
    allowed: "erlaubt",
    weatherWords: {
      "sunny": "sonnig",
      "partlycloudy": "teils bewölkt",
      "cloudy": "bewölkt",
      "rainy": "regnerisch",
      "pouring": "starker Regen",
      "snowy": "Schnee",
      "snowy-rainy": "Schneeregen",
      "fog": "Nebel",
      "hail": "Hagel",
      "lightning": "Gewitter",
      "lightning-rainy": "Gewitter mit Regen",
      "windy": "windig",
      "windy-variant": "windig",
      "clear-night": "klar",
      "exceptional": "außergewöhnlich",
    },
    intent: "Absicht",
    goal: "Ziel",
    fullyOpen: "ganz offen",
    fullyShut: "ganz zu",
    slats: "Lamellen",
    criteria: "Bedingungen",
    actionsToday: "Heute gestellt",
    noActions: "Heute nichts gestellt.",
    cSun: "Sonne auf dem Fenster",
    cSunNo: "Sonne steht nicht auf diesem Fenster",
    cBright: "Hell genug",
    cTemp: "Temperatur verlangt es",
    cWindow: "Fenster geschlossen",
    cStorm: "Kein Sturm",
    cPaused: "Nicht pausiert",
    cOverride: "Nicht von Hand bewegt",
    cEnabled: "Eingeschaltet",
    reaches: "reicht",
    notOnThisWindow: "nicht auf diesem Fenster",
    intoRoom: "in den Raum",
    readings: "Werte",
    outIn: "außen/innen",
    episodeLabel: "Episode",
    episodeRunning: "läuft",
    episodeIdle: "keine",
    brightness: "Helligkeit",
    brightYes: "hell genug",
    brightNo: "nicht hell genug",
    brightUnknown: "nicht geprüft, ein früheres Gate hat entschieden",
    weatherAllowed: "gilt als hell",
    weatherNotAllowed: "gilt nicht als hell",
    pvOverriding: "PV übersteuert das Wetter",
    pvOverrideIn: "PV übersteuert das Wetter in",
    pvOverrideMinutes: "Min., wenn sie so hoch bleibt.",
    coversTotal: "Konfigurierte Rollläden",
    coversShading: "Beschattung",
    coversHeating: "Sonnenheizen",
    coversOverridden: "Manueller Eingriff",
    coversPaused: "Pausiert",
    coversStorm: "Sturmschutz",
    enabled: "Aktiviert",
    dryRunNotice: "**Testlauf.** Es wird nichts bewegt; das ist, was passieren würde.",
  },
};

function labels(hass) {
  const lang = (hass.locale && hass.locale.language) || "en";
  return LABELS[lang.split("-")[0]] || LABELS.en;
}

/**
 * The entity's own name, without the device name in front of it.
 *
 * Friendly names are "<device> <entity>", e.g. "Arbeitszimmer Raffstore
 * Fortsetzen". Every tile sits under a heading that already names the device,
 * and a tile truncates, so the part that says what it is got cut off.
 */
function entityName(hass, entityId, device) {
  const state = hass.states[entityId];
  const friendly = state && state.attributes.friendly_name;
  if (friendly && device && friendly.startsWith(`${device} `)) {
    return friendly.slice(device.length + 1);
  }
  return undefined;
}

function deviceName(device) {
  return device.name_by_user || device.name || "";
}

/**
 * One tile's worth of entity, or null when the entity is not there.
 *
 * Entities are keyed by their translation key, because a device carries more
 * than one of some domains: two buttons and two binary sensors per cover. The
 * domain is kept as a fallback key so that a registry entry without a
 * translation key still renders its device's main tile rather than nothing.
 */
function pick(group, key, fallbackDomain) {
  const entity = group.entities[key] || (fallbackDomain && group.entities[fallbackDomain]);
  if (!entity) return null;
  const name = group.names[key] || (fallbackDomain && group.names[fallbackDomain]);
  return { entity, name };
}

/**
 * Split our entities into the hub device and the controlled covers.
 *
 * The hub is the device nothing points at; every cover device carries a
 * via_device_id back to it.
 */
function collect(hass) {
  const byDevice = new Map();
  for (const entry of Object.values(hass.entities || {})) {
    if (entry.platform !== DOMAIN || !entry.device_id) continue;
    if (!byDevice.has(entry.device_id)) byDevice.set(entry.device_id, []);
    byDevice.get(entry.device_id).push(entry);
  }

  let hub = null;
  const covers = [];
  for (const [deviceId, entries] of byDevice) {
    const device = (hass.devices || {})[deviceId];
    if (!device) continue;
    const group = { device, name: deviceName(device), entities: {}, names: {}, buttons: [] };
    for (const entry of entries) {
      const entityId = entry.entity_id;
      const domain = entityId.split(".")[0];
      const key = entry.translation_key || domain;
      group.entities[key] = entityId;
      group.names[key] = entityName(hass, entityId, group.name);
      if (domain === "button") {
        group.buttons.push({ entity: entityId, name: group.names[key] });
      }
    }
    // Sorted so the dashboard does not reshuffle with the registry's order.
    group.buttons.sort((a, b) => a.entity.localeCompare(b.entity));
    if (device.via_device_id && byDevice.has(device.via_device_id)) {
      covers.push(group);
    } else {
      hub = group;
    }
  }

  // The controlled cover is not one of our entities, so take it from the
  // decision sensor, which reports the entity it is driving.
  for (const cover of covers) {
    const decision = pick(cover, "decision", "sensor");
    const state = decision ? hass.states[decision.entity] : undefined;
    cover.coverEntity = state && state.attributes.cover_entity;
    cover.dryRun = Boolean(state && state.attributes.dry_run);
    // Four of the conditions are entities in their own right rather than
    // anything the decision record carries, so the debug view reads them
    // straight from the switches and sensors that hold them.
    cover.pausedEntity = cover.entities.paused;
    cover.overrideEntity = cover.entities.override_active;
    cover.enabledEntity = cover.entities.enabled;
    cover.stormEntity = hub && hub.entities.storm_active;
    cover.todayEntity = cover.entities.today;
    cover.hasWindowSensor =
      state != null && state.attributes.window_open !== undefined
      && state.attributes.window_open !== null;
  }

  covers.sort((a, b) => a.name.localeCompare(b.name));

  // Sorted first, so the paths do not shuffle when a cover is added.
  const taken = new Set(["overview"]);
  for (const cover of covers) cover.viewPath = viewPath(cover.name, taken);
  return { hub, covers };
}
/** A rounded reading, or a dash where the sensor has nothing to say. */
function num(entity, name, digits, unit) {
  const a = attrOf(entity, name);
  const rounded = digits === 0 ? `${a} | round(0) | int` : `${a} | round(${digits})`;
  return `{% if ${a} is none %}\u2013{% else %}{{ ${rounded} }}${unit}{% endif %}`;
}

function attrOf(entity, name) {
  return `state_attr('${entity}', '${name}')`;
}
function statusRows(entity, t) {
  return [
    ["total", t.coversTotal],
    ["shading", t.coversShading],
    ["heating", t.coversHeating],
    ["overridden", t.coversOverridden],
    ["paused", t.coversPaused],
    ["storm", t.coversStorm],
    ["enabled", t.enabled],
  ].map(([attribute, name]) => ({ type: "attribute", entity, attribute, name }));
}

/**
 * A URL path for one cover's own view, unique within the dashboard.
 *
 * Two covers may carry the same name, and a view path that collides would
 * silently take the reader to the wrong one.
 */
/** A condition line: a tick or a cross, then what it says in words. */
function criterion(label, test, detail) {
  const mark = `{% if ${test} %}\u2705{% else %}\u274c{% endif %}`;
  return `- ${mark} ${label}${detail ? " \u2014 " + detail : ""}`;
}

/** The weather condition in the reader's language; state_attr gives the raw id. */
function weatherWord(entity, t) {
  const raw = attrOf(entity, "weather");
  const pairs = Object.entries(t.weatherWords)
    .map(([id, word]) => `'${id}': '${word}'`)
    .join(", ");
  return pairs ? `{{ {${pairs}}.get(${raw}, ${raw}) }}` : `{{ ${raw} }}`;
}

/**
 * What happened to this cover today, in order.
 *
 * Read from an entity of its own rather than from the logbook: the logbook
 * shows every change to the cover including ones nothing here made, rolls over
 * the last 24 hours rather than the day, and phrases it its own way.
 */
function todayCard(entity, t) {
  return {
    type: "markdown",
    title: t.actionsToday,
    content: [
      `{% set events = state_attr('${entity}', 'events') or [] %}`
        + "{% if events | count == 0 %}" + t.noActions + "{% endif %}"
        + "{% for e in events %}"
        + "{{ as_local(as_datetime(e.at)).strftime('%H:%M') }}"
        + `{% if e.kind == 'move' %} {% if e.up %}\u2191{% else %}\u2193{% endif %}`
        + "{% if e.position is defined %} {{ e.position }} %{% endif %}"
        + `{% if e.tilt is defined %} \u00b7 ${t.evSlats} {{ e.tilt }} \u00b0{% endif %}`
        + `{% elif e.kind == 'paused' %} \u23f8 ${t.evPaused}`
        + `{% elif e.kind == 'resumed' %} \u25b6 ${t.evResumed}`
        + `{% elif e.kind == 'override' %} \u270b ${t.evOverride} {{ e.position }} %`
        + "{% endif %}  \n"
        + "{% endfor %}",
    ].join("\n"),
  };
}

function viewPath(name, taken) {
  const umlauts = { "\u00e4": "ae", "\u00f6": "oe", "\u00fc": "ue", "\u00df": "ss" };
  const base =
    "cover-" +
      (name || "")
        .toLowerCase()
        .replace(/[\u00e4\u00f6\u00fc\u00df]/g, (c) => umlauts[c])
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-+|-+$/g, "") || "cover";
  let path = base;
  for (let n = 2; taken.has(path); n += 1) path = `${base}-${n}`;
  taken.add(path);
  return path;
}

function overviewView(hub, covers, t) {
  const sections = [];

  if (hub) {
    // The central controls stay: the master switch, what it is doing, the
    // storm sensor and pause-all / resume-all.
    const cards = [{ type: "heading", heading: t.control }];
    const enabled = pick(hub, "enabled", "switch");
    if (enabled) cards.push({ type: "tile", ...enabled });
    const status = pick(hub, "status", "sensor");
    if (status) {
      // The count alone does not say what it counts, so break it down.
      cards.push({
        type: "entities",
        entities: [status.entity, ...statusRows(status.entity, t)],
      });
    }
    const storm = pick(hub, "storm_active", "binary_sensor");
    if (storm) cards.push({ type: "tile", ...storm });
    for (const button of hub.buttons) {
      cards.push({ type: "tile", ...button, tap_action: { action: "toggle" } });
    }
    sections.push({ type: "grid", cards });
  }

  // One tile per cover, and nothing to operate: the question this view answers
  // is which cover is in which state. Everything about one of them, including
  // its buttons, is a tap away in its own view.
  const cards = [{ type: "heading", heading: t.covers }];
  for (const cover of covers) {
    if (!cover.coverEntity) continue;
    cards.push({
      type: "tile",
      entity: cover.coverEntity,
      name: cover.name,
      state_content: ["state", "current_position"],
      ...(cover.dryRun ? { icon: "mdi:test-tube" } : {}),
      tap_action: { action: "navigate", navigation_path: cover.viewPath },
      icon_tap_action: { action: "navigate", navigation_path: cover.viewPath },
    });
  }
  if (cards.length > 1) sections.push({ type: "grid", cards });

  return {
    title: t.overview,
    path: "overview",
    type: "sections",
    max_columns: 3,
    sections,
  };
}

/**
 * One cover, everything about it: what it wants, why, its buttons and its day.
 *
 * A subview rather than a tab, so it does not widen the tab bar with one entry
 * per window and comes with a way back to the overview that sent the reader.
 */
function coverView(cover, t) {
  const picked = pick(cover, "decision", "sensor");
  if (!picked) return null;
  const decision = picked.entity;
  const a = (name) => attrOf(decision, name);

  const cards = [
    {
      // One card, and every line in it is one rendered line. A bare Jinja
      // statement on its own line leaves a blank one behind, and a blank
      // line inside a list ends the list and starts another with a
      // paragraph of air between them.
      type: "markdown",
      content: [
        // Trimmed on both ends, so a cover not in dry run is not given a
        // blank line where the notice would have been.
        `{%- if ${a("dry_run")} %}${t.dryRunNotice}\n\n{% endif -%}`,
        // Two trailing spaces: a hard break, so the goal is its own line
        // without the blank one a new paragraph would cost.
        `**${t.intent}:** {{ state_translated('${decision}') }}  `,
        `{% set p = ${a("target_position")} %}`
          + `{%- set s = ${a("target_tilt")} %}`
          + `{%- set d = ${a("penetration_depth")} %}`
          + `{%- set limit = ${a("max_penetration_depth")} -%}`,
        `**${t.goal}:** {% if p is none %}${t.nothingToDo}{% else %}{{ p }} %`
          + `{% if p == 100 %} (${t.fullyOpen}){% elif p == 0 %} (${t.fullyShut}){% endif %}`
          + `{% if s is not none %} · ${t.slats} {{ s }} °{% endif %}`
          + ` — {% if p == 100 and d is not none and limit is not none %}`
          + `${t.noCoverNeeded}: {{ d }} m ${t.ofAllowed} {{ limit }} m ${t.allowed}`
          + `{% elif ${a("acted")} %}${t.didMove}`
          + `{% elif ${a("would_move")} %}${t.wouldMoveNow}`
          + `{% else %}${t.nothingToDo}{% endif %}{% endif %}`,
        "",
        criterion(
          t.cSun,
          a("sun_on_window"),
          `{% if ${a("sun_on_window")} %}${num(decision, "profile_angle", 1, " °")}`
            + `, ${t.reaches} ${num(decision, "penetration_depth", 2, " m")}`
            + `{% if limit is not none %} ${t.ofAllowed} {{ limit }} m ${t.allowed}{% endif %}`
            + `{% else %}${t.cSunNo}{% endif %}`,
        ),
        criterion(
          t.cBright,
          a("bright"),
          `${weatherWord(decision, t)} · ${num(decision, "pv_power", 0, " W")}`
            + `{% if ${a("pv_override_active")} %} · ${t.pvOverriding}`
            + `{% else %}{% set at = ${a("pv_override_at")} %}{% if at %}`
            + "{% set mins = ((as_datetime(at) - now()).total_seconds() / 60)"
            + " | round(0, 'ceil') | int %}"
            + ` · ${t.pvOverrideIn} {{ [mins, 0] | max }} ${t.pvOverrideMinutes}`
            + `{% endif %}{% endif %}`,
        ),
        criterion(
          t.cTemp,
          a("temperature_ok"),
          `${num(decision, "outdoor_temp", 1, "")} / `
            + `${num(decision, "indoor_temp", 1, " °C")} ${t.outIn}`,
        ),
        // Whether there is a window contact at all is settled here rather
        // than in the template, so no line is spent on a cover without one.
        ...(cover.hasWindowSensor
          ? [criterion(t.cWindow, `not ${a("window_open")}`, "")]
          : []),
        ...(cover.stormEntity
          ? [
              criterion(
                t.cStorm,
                `is_state('${cover.stormEntity}', 'off')`,
                num(decision, "wind_speed", 1, " km/h"),
              ),
            ]
          : []),
        ...(cover.pausedEntity
          ? [criterion(t.cPaused, `is_state('${cover.pausedEntity}', 'off')`, "")]
          : []),
        ...(cover.overrideEntity
          ? [criterion(t.cOverride, `is_state('${cover.overrideEntity}', 'off')`, "")]
          : []),
        ...(cover.enabledEntity
          ? [criterion(t.cEnabled, `is_state('${cover.enabledEntity}', 'on')`, "")]
          : []),
      ].join("\n"),
    },
    ...(cover.todayEntity ? [todayCard(cover.todayEntity, t)] : []),
    {
      type: "history-graph",
      hours_to_show: 24,
      entities: [
        ...(cover.coverEntity ? [{ entity: cover.coverEntity }] : []),
        { entity: decision },
      ],
    },
  ];

  // The controls the overview no longer carries live here instead.
  const controls = [{ type: "heading", heading: t.control }];
  if (cover.coverEntity) {
    controls.push({
      type: "tile",
      entity: cover.coverEntity,
      features_position: "bottom",
      features: [{ type: "cover-open-close" }, { type: "cover-position" }],
    });
  }
  const enabled = pick(cover, "enabled", "switch");
  if (enabled) controls.push({ type: "tile", ...enabled });
  for (const button of cover.buttons) {
    controls.push({ type: "tile", ...button, tap_action: { action: "toggle" } });
  }

return {
  title: cover.name,
  path: cover.viewPath,
  subview: true,
  type: "sections",
  max_columns: 2,
  sections: [
    { type: "grid", cards },
    { type: "grid", cards: controls },
  ],
};
}

function generateViews(hass) {
  const t = labels(hass);
  const { hub, covers } = collect(hass);

  if (!hub && covers.length === 0) {
    return [
      {
        title: t.overview,
        path: "overview",
        cards: [{ type: "markdown", content: t.noEntities }],
      },
    ];
  }

  return [
    overviewView(hub, covers, t),
    ...covers.map((cover) => coverView(cover, t)).filter(Boolean),
  ];
}

class CoverControlDashboardStrategy extends HTMLElement {
  static async generate(_config, hass) {
    return {
      title: "Cover Control",
      views: generateViews(hass),
    };
  }
}

class CoverControlViewStrategy extends HTMLElement {
  static async generate(config, hass) {
    const views = generateViews(hass);
    const wanted = config && config.view === "debug" ? "debug" : "overview";
    const view = views.find((v) => v.path === wanted) || views[0];
    return { ...view, title: undefined, path: undefined };
  }
}

const STRATEGIES = {
  "ll-strategy-dashboard-cover-control": CoverControlDashboardStrategy,
  "ll-strategy-view-cover-control": CoverControlViewStrategy,
};

function register(registry) {
  for (const [tag, element] of Object.entries(STRATEGIES)) {
    if (!registry.get(tag)) registry.define(tag, element);
  }
}

// This module is loaded with add_extra_js_url, in parallel with the frontend's
// app bundle. That bundle installs a scoped custom element polyfill which
// replaces window.customElements with a new, empty registry. When this module
// runs first, which is the usual case once it is cached, the definitions land
// in the registry that is thrown away, and the dashboard times out waiting for
// an element it can never find.
//
// So register now, and keep registering into whatever window.customElements is
// until the frontend's own <home-assistant> element appears in it: from then on
// that registry is the one the frontend uses.
const FINAL_REGISTRY_TIMEOUT_MS = 60000;
const started = Date.now();
(function registerUntilSettled() {
  register(window.customElements);
  const settled = window.customElements.get("home-assistant");
  if (!settled && Date.now() - started < FINAL_REGISTRY_TIMEOUT_MS) {
    setTimeout(registerUntilSettled, 25);
  }
})();
