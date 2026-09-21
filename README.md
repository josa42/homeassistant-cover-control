# Cover Control for Home Assistant

[![GitHub Release](https://img.shields.io/github/v/release/josa42/homeassistant-cover-control?style=flat-square)](https://github.com/josa42/homeassistant-cover-control/releases)
[![License](https://img.shields.io/github/license/josa42/homeassistant-cover-control?style=flat-square)](LICENSE)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=flat-square)](https://hacs.xyz/)

A Home Assistant integration that shades and unshades covers from sun geometry,
and can always tell you why it did what it did.

It works out where the sun is relative to each window, how far direct sunlight
would reach into the room, and moves the cover just enough to keep that within
the limit you set. It also opens covers to let the sun warm a cold room,
retracts them in a storm, and stays out of the way when you move one by hand.

<br><br>

## Installation

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=josa42&repository=homeassistant-cover-control&category=integration)

### Requirements

- Home Assistant **2026.9.0** or newer
- At least one cover that accepts a position

<br><br>

## Configuration

1. Go to **Settings** → **Devices & Services**
2. Click **+ Add Integration** and search for "Cover Control"
3. Set the shared sensors and thresholds. This creates the central device.
4. On the integration page, choose **Add a cover** once per cover. Each cover
   gets its own device, and is asked for its orientation and size.

Shared settings live on the hub and every cover inherits them. Any of them can
be overridden per cover, and each decision records both the value it used and
which level it came from.

Covers you have not set up are noticed on their own. If a cover could be
controlled but has no controller yet, Cover Control raises an issue under
**Settings** → **Repairs** naming it. It cannot add the cover for you, because
no part of Home Assistant knows which way a window faces, so the issue points
back at **Add a cover**. Covers you never want controlled can be dismissed from
the issue, and are not offered again.

<br><br>

## Dry run and notifications

**Dry run** evaluates everything as normal and reports what it would do, without
sending a single command. The decision sensor, the dashboard and the
notifications all keep working, so you can watch it for a few sunny days before
letting it near a real cover.

Set it per cover, or on the hub to cover everything at once. The two are OR-ed,
so a hub-wide dry run cannot be cancelled by a per-cover setting.

> [!WARNING]
> Dry run withholds **every** command, including storm protection. A cover left
> in dry run is not protected from wind.

Decisions in dry run report `would_move: true` with `acted: false`, which is
what the dashboard reads to show what would have happened.

**Notifications** go to one notify service, configured on the hub, for example
`notify.mobile_app_phone` or `notify.persistent_notification`. Each evaluation
sends at most one notification, listing every cover that changed.

A change is a cover actually being moved to a new position, or the intent or
its reason changing: an episode started or ended, storm protection kicked in,
a window opened, a cover was moved by hand. These never notify on their own:

- the target drifting without moving the cover: below the motor-protection
  threshold, or in dry run, where the cover never catches up
- the same command being sent again while a cover is still travelling
- a cover briefly going unavailable, as every cover does during a restart
- a short debounce that recovers
- the first evaluation after startup, unless it moves a cover

Dry-run lines are prefixed `[Dry run]`.

<br><br>

## Entities

| Device | Entities |
| --- | --- |
| Central | Enable switch, pause-all and resume-all buttons, storm indicator, status sensor |
| Each cover | Enable switch, decision sensor, manual-override and paused indicators, pause and resume buttons |

**Pause** leaves a cover alone until the next sunrise, and **Resume** hands it
back straight away. Buttons are only available when pressing them does
something.

The decision sensor carries the current intent as its state, plus the reason
code, the target position and the readings behind it.

<br><br>

## Dashboard

The integration ships a dashboard strategy that builds the whole dashboard from
the entity registry, so covers you add later appear on their own.

Create a new dashboard, open its raw configuration editor and put in:

```yaml
strategy:
  type: custom:cover-control
```

You get an overview view with the controls, and a debug view laying out the
decision behind every cover: the reason sentence, the target, what blocked it,
and the readings it used. To place just one of them inside a dashboard you
already have, use it as a view strategy instead:

```yaml
views:
  - strategy:
      type: custom:cover-control
      view: debug
```

<br><br>

## Documentation

[How it works](docs/how-it-works.md) covers the priority order, the shading
geometry, the seating point, how manual overrides are detected, and the known
limits.

<br><br>

## Development

```bash
make install     # create venv and install test dependencies
make test        # run the test suite
make lint        # run ruff

make dev-up      # start Home Assistant at http://localhost:8123
make dev-restart # restart after code changes
make dev-down    # stop it again
```

`make dev-up` mounts `custom_components/` straight into the container, so the
integration is live in a throwaway Home Assistant without touching your real
instance.

The geometry and the decision engine are pure functions with no Home Assistant
imports, so most of the behaviour is testable directly.

### Releasing

```bash
./scripts/release.sh 0.2.0
```

Runs the tests and the linter first, then bumps the manifest version, commits,
tags and pushes. The release workflow builds the zip from the tag. A failure
before the push leaves the working tree untouched.

<br><br>

## Credits

The shading concept, the cut-off geometry and the seating-point insight come
from [TheRealSimon42's cover_automation_v2 blueprint](https://github.com/TheRealSimon42/ha-blueprints),
which this integration is a rework of.
