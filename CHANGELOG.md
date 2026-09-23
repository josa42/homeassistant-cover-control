# Changelog

## Unreleased

### Changed

- **The debug view answers the question in order and in German.** What it wants,
  where it is taking the cover, and then every condition as a tick or a cross
  with the reading behind it: the sun on the window, the brightness, the
  temperature, the window contact, the storm, the pause, a manual move and the
  switches. The table of attribute rows is gone, and so is the English sentence
  the engine writes, which no translation could reach.

  A cover's movements for the day sit under it as a logbook, next to the graph
  that was already there.

### Added

- **The decision sensor reports whether the temperature called for it**, and
  whether the window is open. Both were in the diagnostics only, and both are
  conditions somebody reads the debug view to check.

### Fixed

- **A temperature resting on its threshold no longer drives the covers.** A
  sensor sitting on, say, exactly 22 degrees crosses it on its own noise, and
  every crossing ended the shading episode and started it again minutes later,
  so a cover ran its whole travel twice per wobble. The new **Temperature
  hysteresis** holds a running episode until the reading has fallen back past
  the threshold by that much. It defaults to 0.5 degrees, applies only while an
  episode runs, so it never lowers the threshold that starts one, and 0
  switches it off.

## 1.7.1 - 2026-09-22

### Fixed

- **The house orientation is labelled when editing the hub.** It showed as
  `house_orientation` there, because setting the hub up and editing it are two
  forms with their own copies of the same labels and only the first had been
  given the new one. Editing the hub also explains the wind release, the PV
  threshold and the wind source now, which only the setup form did.

- **The field says which side it is asking about.** It was called the
  orientation of the house, which invites the bearing of whichever way the
  front door faces. It is the bearing of the south side, and is called that
  now.

### Changed

- **The debug view is about half as tall.** Eleven readings sat in two cards of
  labelled rows, each row costing a line of its own to carry one number. They
  are four packed lines now, grouped by what they are about: the sun on the
  window, the brightness, the readings, the episode. A cover is four cards
  instead of six.

  The two values worth a row still have one. Every other value in the record is
  a number or a yes or a no, but the reason and what blocked it are words that
  come from the integration's own translations, and a template would print the
  raw `manual_override` instead.

  One line went: when PV is neither overriding the weather nor climbing towards
  it, the brightness line now ends after the wattage instead of saying so.

## 1.7.0 - 2026-09-22

### Added

- **A cover is told which side of the house it is on, not a compass bearing.**
  Set the **Orientation of the house** once on the hub, the bearing of the side
  you call south, then give each cover **north**, **east**, **south** or
  **west**. A house that turns out to sit a few degrees off the grid is
  corrected in one place rather than window by window.

  **Orientation of the window** is still there and still wins where it is set,
  for a window in a bay or a dormer that is on none of the four sides. Covers
  configured before this all carry one, so none of them move.

### Changed

- **The debug view is shorter and reads in the order you ask the questions in.**
  The readings a decision was made from now sit above the decision itself. The
  target, the slat angle and whether the cover actually moved were four rows
  that say one thing, so they are one sentence under the explanation now, and
  what is left below it is the reasoning behind that sentence.

## 1.6.0 - 2026-09-22

### Fixed

- **The slat angle is worked out when the slats are set, not when the cover is
  sent on its way.** Whether a cover needed its slats moving was decided before
  it started travelling, and the slats swing during the run: an angle that
  matched the target beforehand is often exactly what is missing once the cover
  has arrived. Both halves of a movement are now worked out as they are sent,
  so an angle that has drifted is corrected and one that already fits does not
  start the motor for nothing. It went unnoticed while an episode was running,
  because the next evaluation worked the angle out again from scratch. Nothing
  follows the open that ends an episode, which is where it cost a cover its
  slat angle for the rest of the day.

### Added

- **The debug view shows the angle the sun strikes the window at.** It is what
  decides how far the sun reaches into the room, so the depth shown next to it
  was a number with nothing behind it: the same elevation far off to the side
  hardly enters at all. The decision sensor carries it as the `profile_angle`
  attribute.

## 1.5.2 - 2026-09-22

### Fixed

- **Covers open again after the sun leaves the window.** Opening a cover takes
  two commands, and the second only came due once the episode had already
  ended, when the cover was neutral and had nothing left to ask for. So the
  open was a single attempt, and a cover that missed it stayed shut for the
  rest of the day. What a decision asks for is now queued against the cover and
  outlives the decision that filled it.

- **A command waits for the one before it to finish.** 1.5.1 stopped position
  and tilt going out together by sending one per evaluation, which left the
  ordering to whatever happened to be evaluated next. Commands are now held in
  a queue per cover and released one at a time, each waiting until the cover
  reports it arrived, and nothing is sent into a cover whose motor is running,
  whoever started it. A command the cover has not carried out within 90 seconds
  is given up on and the destination is worked out again from where the cover
  actually is, rather than the rest of the queue being sent to a position it
  never reached.

- **Storm protection no longer queues behind a shading run.** It cancels
  whatever is in progress, which for hardware protection is the point rather
  than the risk.

## 1.5.1 - 2026-09-22

### Fixed

- **A Raffstore no longer twitches instead of shading.** The position and the
  slat angle went out as two commands back to back. A cover that is still
  travelling reads the tilt command as a new destination, abandons the run and
  settles back where it started, so it never reached the position it was sent
  to. Every one of those reports asked for a fresh evaluation, which sent the
  same pair of commands again, and the cover went up and down on the spot for
  as long as the sun was on the window. The position is now driven on its own
  and the slats are set once the cover has arrived.

- **A cover that never arrives is no longer commanded on a loop.** Reports that
  a cover makes while travelling no longer ask for a re-evaluation, and the
  same command is not sent twice inside the settle window. Either alone stops
  the twitching above; together they also cap anything else that could ever
  command a cover faster than it can move. The decision sensor says
  `awaiting_travel` while a command is out.

- **Slats are set even when the cover is already at its position.** The
  threshold that keeps small corrections from starting the motor covered the
  tilt as well, so a cover that happened to sit within 5% of its target kept
  its slats wherever they were.

## 1.5.0 - 2026-09-21

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
