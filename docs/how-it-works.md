# How it works

## Priority order

The integration owns a cover only while there is a reason to. Its priority
order is fixed:

| Priority | Intent | What happens |
| --- | --- | --- |
| 1 | Storm | Wind above the threshold. Retracts, closes or ignores, per cover. Outranks everything, including a manual override. |
| 2 | Window open | The cover is left alone while the window contact reports open. |
| 3 | Paused | Paused with the Pause button. Hands off until the next sunrise. |
| 4 | Manual override | Someone moved it by hand. Hands off until the episode ends. |
| 5 | Cooling / heating | Shades against solar gain, or opens to let the sun warm the room. |
| 6 | Neutral | Nothing to do. The cover is not touched. |

Morning opening, night mode, ventilation positions and notifications are
deliberately **not** included. Those are schedule shaped and vary per
household, so they belong in your own automations. Because the integration
only acts during a solar episode, it does not fight them.

<br><br>

## Settings

### Shared

Set once on the hub, inherited by every cover, and overridable per cover:

- Outdoor temperature (a sensor, or a climate entity's current temperature)
- Weather entity, used for the condition filter and for wind
- PV power sensor (optional)
- Wind source (optional, falls back to the weather entity)
- Notification target, and a dry run that applies to every cover
- Shading and solar-heating temperature thresholds, outdoor and indoor
- PV brightness threshold and the list of weather conditions that allow acting
- PV weather override threshold, above which sustained PV power is believed
  over the weather condition
- Storm trigger and release wind speeds
- **Temperature hysteresis**, how far a reading has to fall back past a
  threshold before a running episode ends
- **Orientation of the south side**, its compass bearing, from which each
  cover's window bearing is worked out. Not overridden
  per cover like the rest of this list; a window that needs its own bearing
  sets one below instead

### Per cover

- **Dry run**, which withholds every command including storm protection

- **Cover type**, pre-selected from what the cover reports it can do
- **Side of the house** the window is on: north, east, south or west
- **Orientation of the window** in degrees, optional, for a window in a bay
  or a dormer that sits on none of the four sides
- **Window height** and **sill height**
- **Allowed sun depth** into the room
- **Field of view** left and right
- Storm action, window contact, indoor temperature, seating point override

<br><br>

## The geometry

Which way a window faces comes from the side of the house it is on, turned by
however far the house is off the compass. A house is corrected once on the hub
rather than window by window, and a window that sits on none of the four sides
carries its own bearing, which wins.

For each cover the integration computes the angle between the sun and the
window normal. Outside the field of view, nothing happens. Inside it, it
computes the profile angle, which is the sun's elevation as seen in the
window's cross section. That angle governs how deep a ray reaches into the
room: a low sun straight ahead penetrates far, while the same elevation far off
to the side barely enters at all.

From the profile angle, the sill height and the window height it solves for the
largest amount of open glass that still keeps sunlight within the allowed
depth, then converts that to a cover position.

> [!IMPORTANT]
> An allowed depth of **0 m** with a sill at floor level means "no direct sun in
> the room at all", which necessarily closes the cover fully whenever the sun is
> on the window. That is correct, not a bug, but it is rarely what people want.
> A value between 0.5 m and 1.5 m usually keeps sun off the furniture while
> leaving the room bright.

### Motor percent is not glass area

A roller shutter covers the glass over part of its travel; the rest only pulls
the slats together to close the light gaps. Shading therefore stops at the
seating point, because travelling below it buys no extra shading and squeezes
the slats shut. The cover type sets a sensible default, and you can override
it.

To measure your own: lower the cover slowly until the light gap at the bottom
just disappears. That position is the seating point.

<br><br>

## The debug dashboard

The generated dashboard's debug view lays out the decision record per cover: the
human sentence, the decision, the inputs, and a **Brightness** card that says in
words why the brightness gate concluded what it did. When PV is above the
override threshold but has not held there long enough yet, that card counts down
the minutes until it takes over. The countdown is rendered from
`pv_override_at`, so it keeps ticking between the five-minute evaluations rather
than going stale.

<br><br>

## Covers without a controller

Every evaluation also asks which covers could be controlled but are not. Any it
finds are reported as one issue under **Settings** → **Repairs**.

A cover counts as a candidate when it is not already controlled, not hidden or
disabled, accepts a position, and is not a garage door, gate, door or damper. The
position requirement is not pedantry: without it the engine can only ever report
`no_position_support`, and storm protection has nothing to send either, so
offering such a cover would be offering nothing.

The issue never adds a cover by itself. A cover needs the orientation and size
of its window, and nothing in Home Assistant knows which way a window faces, so
a controller created from defaults would compute confident, wrong positions and
then drive a real cover to them. The issue names what is missing and leaves the
adding to you.

Covers you never want controlled can be dismissed from the issue. They are
remembered on the hub and never listed again, and editing the hub settings does
not bring them back.

<br><br>

## Why did it do that?

Every evaluation produces one decision record. Nothing moves a cover without
producing one. The information is exposed in four layers, each costing what it
is worth:

- **`sensor.<cover>_decision`** carries the current intent as its state, with a
  small flat set of attributes: reason code, target position and tilt, the key
  sensor readings, and what blocked it. It stays small on purpose, because the
  recorder writes attributes on every state change. Brightness is the one gate
  broken out into attributes of its own, because "not bright enough" is the
  reason people ask about most and the raw weather and PV readings do not answer
  it: `bright`, `weather_ok`, `pv_override_active` and `pv_override_at`, the
  moment sustained PV takes over from the weather. All four are `None` when an
  earlier gate decided before brightness was ever evaluated.
- **Diagnostics** (download from the integration page) carry the full trace of
  the last 50 decisions per cover: every input, every gate with its verdict and
  detail, the geometry intermediates, and every effective setting with its
  source.
- **The `cover_control_decision` event** fires on every decision, so
  automations can react to or notify on a specific reason code.
- **Debug logging** via `custom_components.cover_control`.

Reason codes are stable identifiers, so match automations on `reason_code` and
never on the human sentence.

<br><br>

## Manual overrides

Home Assistant stamps a context on every service call, so the integration
records its own and knows when a movement was not its doing.

Context alone is not enough, though. Radio covers report their position back
from the device itself with a fresh context, so a non-matching context is only
treated as manual once the cover has had time to finish travelling and the
reported position still disagrees with what was asked for.

An override holds for the rest of the current episode. When the episode ends
the integration takes control back and opens the cover. The **Resume** button on
each cover, or **Resume all** on the hub, hands control back immediately.

<br><br>

## Pause

**Pause** on a cover, or **Pause all** on the hub, leaves covers alone until the
next sunrise, for an evening when the automatic behaviour is not wanted. It uses
`sun.sun`'s next rising, so a pause pressed at noon runs to tomorrow morning and
one pressed at 23:00 runs to that same morning.

- Storm protection still acts while a cover is paused, and the pause continues
  once the wind drops.
- A pause survives a restart of Home Assistant.
- When a pause ends, by running out or by pressing **Resume**, the cover starts
  fresh. Whatever episode was running when the pause began is dropped without a
  command, so a pause pressed on a hot afternoon does not open the blinds just
  after sunrise. A new episode begins once the sun and temperature call for one.

Unlike a manual override, which ends with the episode, a pause ends on the clock.

<br><br>

## Known limits

- Covers that do not accept a position cannot be shaded. The decision says so
  rather than failing silently.
- Window contacts are binary, so a tilted window cannot be told from a wide open
  one. `Keep shading while the window is open` is opt-in per cover for that
  reason, and is a poor fit for balcony doors.
- Wind is compared against the threshold after conversion to km/h. A weather
  entity that reports no wind speed disables storm protection for that cover.
- An episode that ends after a night automation has already closed a cover will
  open it again. In practice episodes end around sunset, well before night
  automations run.
- PV power collapses when an inverter curtails because the battery is full,
  which looks like a cloudy sky. A gate must read false continuously for ten
  minutes before it ends an episode, which absorbs curtailment dips and passing
  clouds.
- Weather entities report a single condition for a whole forecast area, so
  `cloudy` can arrive while this roof is still in full sun. PV power that stays
  above the weather override threshold for twenty minutes is therefore believed
  over the condition, because the inverter is the instrument actually measuring
  the light. Set that threshold high enough that only real sun reaches it, or to
  0 to switch the override off.
