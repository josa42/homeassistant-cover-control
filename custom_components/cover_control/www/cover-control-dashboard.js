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
    targetPosition: "Target position",
    targetTilt: "Target tilt",
    wouldMove: "Would move the cover",
    acted: "Moved the cover",
    dryRun: "Dry run",
    blockedBy: "Blocked by",
    episode: "Episode running",
    sunOnWindow: "Sun on the window",
    penetration: "Sun reaches into the room",
    outdoor: "Outdoor temperature",
    indoor: "Indoor temperature",
    pv: "PV power",
    weather: "Weather",
    wind: "Wind",
    inputs: "Inputs",
    why: "Why",
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
    targetPosition: "Zielposition",
    targetTilt: "Ziel-Lamellenwinkel",
    wouldMove: "Würde den Rollladen bewegen",
    acted: "Rollladen bewegt",
    dryRun: "Testlauf",
    blockedBy: "Blockiert durch",
    episode: "Episode läuft",
    sunOnWindow: "Sonne auf dem Fenster",
    penetration: "Sonneneinfall in den Raum",
    outdoor: "Außentemperatur",
    indoor: "Innentemperatur",
    pv: "PV-Leistung",
    weather: "Wetter",
    wind: "Wind",
    inputs: "Eingangswerte",
    why: "Warum",
    dryRunNotice: "**Testlauf.** Es wird nichts bewegt; das ist, was passieren würde.",
  },
};

function labels(hass) {
  const lang = (hass.locale && hass.locale.language) || "en";
  return LABELS[lang.split("-")[0]] || LABELS.en;
}

function deviceName(device) {
  return device.name_by_user || device.name || "";
}

/**
 * Split our entities into the hub device and the controlled covers.
 *
 * The hub is the device nothing points at; every cover device carries a
 * via_device_id back to it. Within a device the domain is enough to tell the
 * entities apart, because there is exactly one of each.
 */
function collect(hass) {
  const byDevice = new Map();
  for (const entry of Object.values(hass.entities || {})) {
    if (entry.platform !== DOMAIN || !entry.device_id) continue;
    if (!byDevice.has(entry.device_id)) byDevice.set(entry.device_id, []);
    byDevice.get(entry.device_id).push(entry.entity_id);
  }

  let hub = null;
  const covers = [];
  for (const [deviceId, entityIds] of byDevice) {
    const device = (hass.devices || {})[deviceId];
    if (!device) continue;
    const group = { device, name: deviceName(device), entities: {} };
    for (const entityId of entityIds) {
      group.entities[entityId.split(".")[0]] = entityId;
    }
    if (device.via_device_id && byDevice.has(device.via_device_id)) {
      covers.push(group);
    } else {
      hub = group;
    }
  }

  // The controlled cover is not one of our entities, so take it from the
  // decision sensor, which reports the entity it is driving.
  for (const cover of covers) {
    const decision = cover.entities.sensor;
    const state = decision ? hass.states[decision] : undefined;
    cover.coverEntity = state && state.attributes.cover_entity;
    cover.dryRun = Boolean(state && state.attributes.dry_run);
  }

  covers.sort((a, b) => a.name.localeCompare(b.name));
  return { hub, covers };
}

function attributeRows(entity, t) {
  const rows = [
    ["reason_code", t.reason],
    ["target_position", t.targetPosition],
    ["target_tilt", t.targetTilt],
    ["would_move", t.wouldMove],
    ["acted", t.acted],
    ["dry_run", t.dryRun],
    ["blocked_by", t.blockedBy],
    ["episode_active", t.episode],
    ["sun_on_window", t.sunOnWindow],
    ["penetration_depth", t.penetration],
  ];
  return rows.map(([attribute, name]) => ({
    type: "attribute",
    entity,
    attribute,
    name,
    ...(attribute === "penetration_depth" ? { suffix: " m" } : {}),
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

function overviewView(hub, covers, t) {
  const sections = [];

  if (hub) {
    const cards = [{ type: "heading", heading: t.control }];
    if (hub.entities.switch) {
      cards.push({ type: "tile", entity: hub.entities.switch });
    }
    if (hub.entities.sensor) {
      cards.push({ type: "tile", entity: hub.entities.sensor });
    }
    if (hub.entities.binary_sensor) {
      cards.push({ type: "tile", entity: hub.entities.binary_sensor });
    }
    if (hub.entities.button) {
      cards.push({
        type: "tile",
        entity: hub.entities.button,
        tap_action: { action: "toggle" },
      });
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
    if (cover.entities.sensor) {
      cards.push({
        type: "tile",
        entity: cover.entities.sensor,
        name: t.decision,
        state_content: ["state", "reason_code"],
        ...(cover.dryRun ? { icon: "mdi:test-tube" } : {}),
      });
    }
    if (cover.entities.binary_sensor) {
      cards.push({ type: "tile", entity: cover.entities.binary_sensor });
    }
    if (cover.entities.switch) {
      cards.push({ type: "tile", entity: cover.entities.switch });
    }
    if (cover.entities.button) {
      cards.push({
        type: "tile",
        entity: cover.entities.button,
        tap_action: { action: "toggle" },
      });
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
    const decision = cover.entities.sensor;
    if (!decision) continue;

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
          `{% if state_attr('${decision}', 'dry_run') %}`,
          t.dryRunNotice,
          "{% endif %}",
          "",
          `{{ state_attr('${decision}', 'message') }}`,
        ].join("\n"),
      },
      {
        type: "entities",
        title: t.decision,
        entities: attributeRows(decision, t),
      },
      {
        type: "entities",
        title: t.inputs,
        entities: inputRows(decision, t),
      },
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

customElements.define(
  "ll-strategy-dashboard-cover-control",
  CoverControlDashboardStrategy,
);
customElements.define(
  "ll-strategy-view-cover-control",
  CoverControlViewStrategy,
);
