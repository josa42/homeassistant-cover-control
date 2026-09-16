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

<br><br>

## Entities

| Device | Entities |
| --- | --- |
| Central | Enable switch, resume-all button, storm indicator, status sensor |
| Each cover | Enable switch, decision sensor, manual-override indicator, resume button |

The decision sensor carries the current intent as its state, plus the reason
code, the target position and the readings behind it.

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
