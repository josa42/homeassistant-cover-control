# Cover Control

A Home Assistant integration that shades and unshades covers from sun geometry,
and can always tell you why it did what it did.

It computes where the sun actually is relative to each window, works out how far
direct sunlight would reach into the room, and moves the cover just enough to
keep that within the limit you set. It also opens covers to let the sun heat a
cold room, retracts them in a storm, and stays out of the way when you move a
cover by hand.

## What it controls, and what it leaves alone

The integration owns a cover only while there is a reason to. Its priority order
is fixed:

| Priority | Intent | What happens |
| --- | --- | --- |
| 1 | Storm | Wind above the threshold. Retracts, closes or ignores, per cover. Outranks everything, including a manual override. |
| 2 | Window open | The cover is left alone while the window contact reports open. |
| 3 | Manual override | Someone moved it by hand. Hands off until the episode ends. |
| 4 | Cooling / heating | Shades against solar gain, or opens to let the sun warm the room. |
| 5 | Neutral | Nothing to do. The cover is not touched. |

Morning opening, night mode, ventilation positions and notifications are
deliberately **not** included. Those are schedule shaped and vary per household,
so they belong in your own automations. Because the integration only acts during
a solar episode, it does not fight them.

## Setup

1. Copy `custom_components/cover_control` into your Home Assistant `config`
   folder, or add this repository to HACS as a custom repository.
2. Restart Home Assistant.
3. Add the **Cover Control** integration. The first dialog configures the shared
   sensors and thresholds, and creates the central device.
4. On the integration page, choose **Add a cover** once per cover. Each cover
   gets its own device and its own configuration.

### Shared settings

Set once on the hub, inherited by every cover, and overridable per cover:

- Outdoor temperature (a sensor, or a climate entity's current temperature)
- Weather entity, used for the condition filter and for wind
- PV power sensor (optional)
- Wind source (optional, falls back to the weather entity)
- Shading and solar-heating temperature thresholds, outdoor and indoor
- PV brightness threshold and the list of weather conditions that allow acting
- Storm trigger and release wind speeds

Every decision records the value it used **and which level it came from**, so a
surprising threshold never means diffing two dialogs.

### Per-cover settings

- **Cover type**, pre-selected from what the cover reports it can do
- **Orientation** in degrees (0 north, 90 east, 180 south, 270 west)
- **Window height** and **sill height**
- **Allowed sun depth** into the room
- **Field of view** left and right
- Storm action, window contact, indoor temperature, seating point override

## How the geometry works

For each cover the integration computes the angle between the sun and the window
normal. Outside the field of view, nothing happens. Inside it, it computes the
profile angle, which is the sun's elevation as seen in the window's cross
section. That angle governs how deep a ray reaches into the room: a low sun
straight ahead penetrates far, while the same elevation far off to the side
barely enters at all.

From the profile angle, the sill height and the window height it solves for the
largest amount of open glass that still keeps sunlight within the allowed depth,
then converts that to a cover position.

Note that an allowed depth of **0 m** with a sill at floor level means "no direct
sun in the room at all", which necessarily closes the cover fully whenever the
sun is on the window. That is correct, not a bug, but it is rarely what people
want. A value between 0.5 m and 1.5 m usually keeps sun off the furniture while
leaving the room bright.

### Motor percent is not glass area

A roller shutter covers the glass over part of its travel; the rest only pulls
the slats together to close the light gaps. Shading therefore stops at the
seating point, because travelling below it buys no extra shading and squeezes
the slats shut. The cover type sets a sensible default, and you can override it.

To measure your own: lower the cover slowly until the light gap at the bottom
just disappears. That position is the seating point.

## Why did it do that?

Every evaluation produces one decision record. Nothing moves a cover without
producing one. The information is exposed in four layers, each costing what it
is worth:

- **`sensor.<cover>_decision`** carries the current intent as its state, with a
  small flat set of attributes: reason code, target position and tilt, the key
  sensor readings, and what blocked it. It stays small on purpose, because the
  recorder writes attributes on every state change.
- **Diagnostics** (download from the integration page) carry the full trace of
  the last 50 decisions per cover: every input, every gate with its verdict and
  detail, the geometry intermediates, and every effective setting with its
  source.
- **The `cover_control_decision` event** fires on every decision, so automations
  can react to or notify on a specific reason code.
- **Debug logging** via `custom_components.cover_control`.

Reason codes are stable identifiers, so match automations on `reason_code` and
never on the human sentence.

## Manual overrides

Home Assistant stamps a context on every service call, so the integration
records its own and knows with certainty when a movement was not its doing.

Context alone is not enough, though. Radio covers report their position back from
the device itself with a fresh context, so a non-matching context is only treated
as manual once the cover has had time to finish travelling and the reported
position still disagrees with what was asked for.

An override holds for the rest of the current episode. When the episode ends the
integration takes control back and opens the cover. The **Resume** button on each
cover, or **Resume all** on the hub, hands control back immediately.

## Entities

**Central device**: master enable switch, resume-all button, storm indicator, and
a status sensor counting controlled covers.

**Each cover**: enable switch, decision sensor, manual-override indicator, and a
resume button.

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
- PV power collapses when an inverter curtails because the battery is full, which
  looks like a cloudy sky. A gate must read false continuously for ten minutes
  before it ends an episode, which absorbs curtailment dips and passing clouds.

## Development

```bash
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python homeassistant pytest-homeassistant-custom-component ruff
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m ruff check custom_components tests
```

The geometry and the decision engine are pure functions with no Home Assistant
imports, so most of the behaviour is testable directly.

## Credits

The shading concept, the cut-off geometry and the seating-point insight come from
[TheRealSimon42's cover_automation_v2 blueprint](https://github.com/TheRealSimon42/ha-blueprints),
which this integration is a rework of. An integration can do two things a
blueprint cannot: identify its own service calls by context instead of guessing
from position deltas, and keep state without a helper entity per window.
