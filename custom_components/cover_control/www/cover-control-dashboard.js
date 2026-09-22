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
    episode: "Episode running",
    sunOnWindow: "Sun on the window",
    profileAngle: "Angle of the sun on the window",
    penetration: "Sun reaches into the room",
    outdoor: "Outdoor temperature",
    indoor: "Indoor temperature",
    pv: "PV power",
    weather: "Weather",
    wind: "Wind",
    inputs: "Inputs",
    why: "Why",
    brightness: "Brightness",
    brightYes: "Bright enough to act.",
    brightNo: "Not bright enough to act.",
    brightUnknown: "Brightness was not reached; an earlier gate decided.",
    weatherAllowed: "counts as bright",
    weatherNotAllowed: "does not count as bright",
    pvOverriding: "PV is high enough to override the weather.",
    pvOverrideIn: "PV overrides the weather in",
    pvOverrideMinutes: "min, if it stays this high.",
    pvBelowOverride: "PV is below the weather override threshold.",
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
    episode: "Episode läuft",
    sunOnWindow: "Sonne auf dem Fenster",
    profileAngle: "Winkel der Sonne auf dem Fenster",
    penetration: "Sonneneinfall in den Raum",
    outdoor: "Außentemperatur",
    indoor: "Innentemperatur",
    pv: "PV-Leistung",
    weather: "Wetter",
    wind: "Wind",
    inputs: "Eingangswerte",
    why: "Warum",
    brightness: "Helligkeit",
    brightYes: "Hell genug zum Handeln.",
    brightNo: "Nicht hell genug zum Handeln.",
    brightUnknown: "Helligkeit wurde nicht geprüft; ein früheres Gate hat entschieden.",
    weatherAllowed: "gilt als hell",
    weatherNotAllowed: "gilt nicht als hell",
    pvOverriding: "PV ist hoch genug, um das Wetter zu übersteuern.",
    pvOverrideIn: "PV übersteuert das Wetter in",
    pvOverrideMinutes: "Min., wenn sie so hoch bleibt.",
    pvBelowOverride: "PV liegt unter dem Übersteuerungswert.",
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
  }

  covers.sort((a, b) => a.name.localeCompare(b.name));
  return { hub, covers };
}

/**
 * What the decision concluded, minus everything the summary above already says.
 *
 * The target and what became of it are four rows that read as one sentence, so
 * they live in the summary card and this is left as the reasoning behind it.
 */
function attributeRows(entity, t) {
  const rows = [
    ["reason_code", t.reason],
    ["blocked_by", t.blockedBy],
    ["episode_active", t.episode],
    ["sun_on_window", t.sunOnWindow],
    ["profile_angle", t.profileAngle],
    ["penetration_depth", t.penetration],
  ];
  const suffixes = { profile_angle: "\u00b0", penetration_depth: " m" };
  return rows.map(([attribute, name]) => ({
    type: "attribute",
    entity,
    attribute,
    name,
    ...(suffixes[attribute] ? { suffix: suffixes[attribute] } : {}),
  }));
}

function inputRows(entity, t) {
  return [
    ["outdoor_temp", t.outdoor, " °C"],
    ["indoor_temp", t.indoor, " °C"],
    ["pv_power", t.pv, " W"],
    ["weather", t.weather, ""],
    ["wind_speed", t.wind, " km/h"],
  ].map(([attribute, name, suffix]) => ({
    type: "attribute",
    entity,
    attribute,
    name,
    ...(suffix ? { suffix } : {}),
  }));
}

function attrOf(entity, name) {
  return `state_attr('${entity}', '${name}')`;
}

/**
 * "Not bright enough" in words, with a live countdown to the PV override.
 *
 * A markdown card rather than attribute rows because the interesting number,
 * how much longer PV has to hold, is not stored anywhere: only the moment the
 * override engages is. Templates using now() re-render every minute, so the
 * countdown stays honest between the five-minute evaluations.
 */
function brightnessCard(entity, t) {
  const attr = (name) => attrOf(entity, name);
  return {
    type: "markdown",
    title: t.brightness,
    content: [
      `{% set bright = ${attr("bright")} %}`,
      `{% set at = ${attr("pv_override_at")} %}`,
      "{% if bright is none %}",
      t.brightUnknown,
      "{% else %}",
      `**{{ ${"'" + t.brightYes + "' if bright else '" + t.brightNo + "'"} }}**`,
      "",
      `- {{ ${attr("weather")} }}:`,
      `  {{ ${"'" + t.weatherAllowed + "' if " + attr("weather_ok") + " else '" + t.weatherNotAllowed + "'"} }}`,
      `- {{ ${attr("pv_power")} }} W`,
      "{% endif %}",
      "",
      `{% if ${attr("pv_override_active")} %}`,
      t.pvOverriding,
      "{% elif at %}",
      "{% set mins = ((as_datetime(at) - now()).total_seconds() / 60) | round(0, 'ceil') | int %}",
      `${t.pvOverrideIn} {{ [mins, 0] | max }} ${t.pvOverrideMinutes}`,
      "{% else %}",
      t.pvBelowOverride,
      "{% endif %}",
    ].join("\n"),
  };
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

function overviewView(hub, covers, t) {
  const sections = [];

  if (hub) {
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

  for (const cover of covers) {
    const cards = [{ type: "heading", heading: cover.name }];
    if (cover.coverEntity) {
      cards.push({
        type: "tile",
        entity: cover.coverEntity,
        features_position: "bottom",
        features: [{ type: "cover-open-close" }, { type: "cover-position" }],
      });
    }
    const decision = pick(cover, "decision", "sensor");
    if (decision) {
      cards.push({
        type: "tile",
        entity: decision.entity,
        name: t.decision,
        state_content: ["state", "reason_code"],
        ...(cover.dryRun ? { icon: "mdi:test-tube" } : {}),
      });
    }
    const override = pick(cover, "override_active", "binary_sensor");
    if (override) cards.push({ type: "tile", ...override });
    // No domain fallback: it would repeat the override tile on a registry
    // entry that carries no translation key.
    const paused = pick(cover, "paused", null);
    if (paused) cards.push({ type: "tile", ...paused });
    const enabled = pick(cover, "enabled", "switch");
    if (enabled) cards.push({ type: "tile", ...enabled });
    for (const button of cover.buttons) {
      cards.push({ type: "tile", ...button, tap_action: { action: "toggle" } });
    }
    sections.push({ type: "grid", cards });
  }

  return {
    title: t.overview,
    path: "overview",
    type: "sections",
    max_columns: 3,
    sections,
  };
}

function debugView(covers, t) {
  const sections = [];

  for (const cover of covers) {
    const picked = pick(cover, "decision", "sensor");
    if (!picked) continue;
    const decision = picked.entity;

    const cards = [
      { type: "heading", heading: cover.name },
      {
        // The human sentence is the fastest answer to "why is it there right
        // now", so it goes first and in full rather than truncated in a row.
        type: "markdown",
        content: [
          // state_translated, not states: templates return the raw state, so
          // states() would print window_open instead of the translated intent.
          `**{{ state_translated('${decision}') }}**`,
          "",
          // Rendered live, so a cover switched into dry run says so without
          // the dashboard having to be regenerated.
          `{% if ${attrOf(decision, "dry_run")} %}`,
          t.dryRunNotice,
          "{% endif %}",
          "",
          `{{ ${attrOf(decision, "message")} }}`,
          // The target and what became of it: four rows of their own before,
          // and one sentence that happens to be the answer people came for.
          `{% set p = ${attrOf(decision, "target_position")} %}`,
          `{% set s = ${attrOf(decision, "target_tilt")} %}`,
          "{% if p is not none %}",
          "",
          `**${t.target}:** {{ p }} %`
            + `{% if s is not none %} · {{ s }} °{% endif %} — `
            + `{% if ${attrOf(decision, "acted")} %}${t.didMove}`
            + `{% elif ${attrOf(decision, "would_move")} %}${t.wouldMoveNow}`
            + `{% else %}${t.nothingToDo}{% endif %}`,
          "{% endif %}",
        ].join("\n"),
      },
      {
        type: "entities",
        title: t.inputs,
        entities: inputRows(decision, t),
      },
      {
        type: "entities",
        title: t.decision,
        entities: attributeRows(decision, t),
      },
      brightnessCard(decision, t),
      {
        type: "history-graph",
        hours_to_show: 24,
        entities: [
          ...(cover.coverEntity ? [{ entity: cover.coverEntity }] : []),
          { entity: decision },
        ],
      },
    ];
    sections.push({ type: "grid", cards });
  }

  return {
    title: t.debug,
    path: "debug",
    type: "sections",
    max_columns: 2,
    sections,
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

  const views = [overviewView(hub, covers, t)];
  if (covers.length) views.push(debugView(covers, t));
  return views;
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
