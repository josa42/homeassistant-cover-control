# Changelog

## Unreleased

### Added

- **The debug dashboard says why it is not bright enough.** A Brightness card
  per cover spells out which half of the gate failed, the weather condition and
  the PV reading behind it, and counts down the minutes until sustained PV takes
  over from the weather. The decision sensor carries the same facts as the
  `bright`, `weather_ok`, `pv_override_active` and `pv_override_at` attributes,
  so automations and templates can read them too.

- **Covers without a controller are found for you.** An issue under Settings >
  Repairs names any cover that could be controlled but is not set up yet, so a
  newly paired cover does not sit there doing nothing until you notice. It skips
  covers that cannot take a position, along with garage doors, gates, doors and
  dampers, and it never adds a cover by itself: that needs the orientation and
  size of the window. Covers you never want controlled can be dismissed from the
  issue and are not offered again.

### Changed

- **Releasing verifies the dashboard strategy version bump.** It was already
  bumped, but nothing checked that it worked. A silent failure there ships a
  release whose dashboard keeps serving the strategy browsers cached before the
  upgrade, which looks like the new dashboard code simply not working.

## 1.4.0 - 2026-09-20

### Added

- **Sustained PV power now outranks the weather condition.** A weather entity
  reports one condition for a whole forecast area, so it can say `cloudy` while
  the roof is in full sun and the covers stay open. PV power that holds above the
  new **PV power outranks the weather condition above** threshold for twenty
  minutes now counts as bright on its own. The threshold defaults to 2500 W and
  0 switches the override off. The `bright` gate in diagnostics says when the
  weather was overridden and since when.

## 1.3.0 - 2026-09-17

### Added

- **Pause covers until the next sunrise.** A Pause button on each cover, and
  Pause all on the hub, leave covers alone until the sun rises again, for an
  evening when the automatic behaviour is not wanted. Storm protection still
  acts while paused, and a pause survives a restart. When it ends, by running
  out or by pressing Resume, the cover starts fresh without moving, so a pause
  pressed on a hot afternoon does not open the blinds after sunrise. A paused
  indicator per cover and a paused count on the status sensor show what is
  paused and until when.

### Changed

- **Resume is only available when there is something to resume.** It used to
  be pressable with no override or pause to end.

### Fixed

- **Reconfiguring a cover ends with a readable message.** It showed
  `reconfigure_successful` instead of "Die Neukonfiguration war erfolgreich".

## 1.2.0 - 2026-09-16

### Added

- **The overview breaks the status count down.** The status sensor only showed
  a number. The dashboard now lists what it counts: covers configured, shading,
  solar heating, manually overridden and under storm protection, and whether
  control is switched on.

### Fixed

- **Dashboard tiles show what they are.** Tile names repeated the cover's name,
  so the resume button read "Arbeitszimmer Raff…" and the part saying what it
  does was cut off. The cover's name is already the heading above, so tiles now
  show only their own name, such as "Fortsetzen".
- **The dashboard strategy loads reliably.** Most page loads failed with
  "Timeout waiting for strategy element ll-strategy-dashboard-cover-control to
  be registered", and reloading only sometimes helped. While it starts, the
  Home Assistant frontend replaces its registry of custom elements with a new,
  empty one. Once the strategy file was cached it ran before that swap, so it
  registered itself in the registry that was then thrown away. It now keeps
  registering until the frontend's own registry is in place.

## 0.1.1 - 2026-09-16

### Changed

- **One notification per evaluation, and only for real changes.** Every cover
  used to notify on its own, so two covers changing together meant two
  messages. Restarts notified about every cover as it briefly went unavailable
  and came back. In dry run the target drifted a little on every tick while the
  cover never moved, which meant a message every five minutes per cover. Changes
  are now combined into one message. A change is a new intent or reason, or a
  cover actually sent to a new position. Re-sending the same command while a
  cover is still travelling, a short debounce that recovers, and the first
  evaluation after startup no longer notify on their own.

### Fixed

- **The dashboard no longer shows raw codes.** The debug view printed the
  decision as `window_open` instead of "Fenster offen", because its heading used
  the untranslated state. Weather conditions, attribute names in the more-info
  dialog, the unit of the status sensor and the weather options during setup
  were untranslated as well. Weather conditions use Home Assistant's own
  wording, so they match the rest of the interface.

## 0.1.0 - 2026-09-16

The first release. Cover Control shades and unshades covers from sun geometry,
and every decision it makes can be traced back to the readings and rules behind
it.

### Added

- **Shading from sun geometry.** For each cover the integration works out how
  far direct sun would reach into the room, from the window's orientation,
  height, sill height and field of view, and lowers the cover just enough to
  keep it within the depth you allow.
- **Solar heating.** On cold days covers open to let the sun warm the room.
- **Storm protection.** Above a wind threshold each cover retracts, closes or is
  left alone, depending on what is safe for that cover. It outranks everything
  else.
- **Window contacts.** A cover is left alone while its window is open, unless
  you opt in to shading with the window open.
- **Manual overrides.** Moving a cover by hand hands it over until the current
  episode ends, or until you press Resume.
- **Cover types.** Raffstore, Rolladen and other covers map motor position to
  glass area differently. The type is pre-selected from what the cover reports
  it can do, and a Rolladen never shades below its seating point, where only the
  light gaps close.
- **Every decision is explained.** A decision sensor per cover reports the intent
  and a reason code, the diagnostics download carries the full trace of recent
  decisions, and a `cover_control_decision` event fires on every evaluation.
- **Dry run.** Covers are evaluated and reported as normal, but no command is
  sent, so behaviour can be watched safely before handing over control. It can
  be set per cover or for every cover at once. Dry run also withholds storm
  protection.
- **Notifications** to a notify service of your choice.
- **A dashboard strategy** that builds an overview and a debug view from your
  configured covers, so covers added later appear without editing a dashboard.
- English and German translations, and a brand icon for HACS and Home
  Assistant.
