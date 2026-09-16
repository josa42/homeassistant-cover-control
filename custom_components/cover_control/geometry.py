"""Sun geometry and the motor-position <-> glass-area mapping.

Everything in here is a pure function of numbers so it can be tested without
Home Assistant. Angles are degrees, lengths are metres, positions are Home
Assistant cover percentages (100 = fully open, 0 = fully closed).
"""

from __future__ import annotations

import math

#: Beyond this the sun sits in the facade plane and cannot enter the window.
_GRAZING = 89.9


def azimuth_delta(sun_azimuth: float, window_azimuth: float) -> float:
    """Signed angle from the window normal to the sun, in ``[-180, 180]``.

    Negative is left of the normal seen from inside looking out, positive is
    right. For a south-facing window (180) the morning sun in the east (90)
    gives -90, i.e. the left-hand side.
    """
    return (sun_azimuth - window_azimuth + 180.0) % 360.0 - 180.0


def sun_on_window(
    elevation: float, delta: float, fov_left: float, fov_right: float
) -> bool:
    """Whether direct sun can reach the glass at all."""
    if elevation <= 0.0:
        return False
    return -abs(fov_left) <= delta <= abs(fov_right)


def profile_angle(elevation: float, delta: float) -> float:
    """Vertical shadow angle: the sun's elevation seen in the window's section.

    This is the angle that actually governs how deep a ray reaches into the
    room. A sun low in the sky but straight ahead penetrates far; the same
    elevation far off to the side barely enters at all.
    """
    if abs(delta) >= 90.0:
        return 90.0
    tan_profile = math.tan(math.radians(elevation)) / math.cos(math.radians(delta))
    return math.degrees(math.atan(tan_profile))


def penetration_depth(
    glass_fraction: float,
    sill_height: float,
    window_height: float,
    profile: float,
) -> float:
    """How far direct sun reaches into the room, in metres.

    Measured along the floor from the window plane, for the ray entering at the
    top edge of the currently open glass.
    """
    if profile <= 0.0:
        return 0.0
    if profile >= _GRAZING:
        return 0.0
    top_of_opening = sill_height + glass_fraction * window_height
    return top_of_opening / math.tan(math.radians(profile))


def required_glass_fraction(
    max_depth: float,
    sill_height: float,
    window_height: float,
    profile: float,
) -> float:
    """Largest open glass fraction that still keeps sun within ``max_depth``.

    Returns a value in ``[0, 1]``. Note that ``max_depth = 0`` with a sill at
    floor level means "no direct sun in the room at all", which necessarily
    closes the glass completely whenever the sun is on the window.
    """
    if window_height <= 0.0:
        return 1.0
    if profile >= _GRAZING:
        return 1.0
    if profile <= 0.0:
        return 0.0
    allowed_top = max_depth * math.tan(math.radians(profile))
    fraction = (allowed_top - sill_height) / window_height
    return max(0.0, min(1.0, fraction))


def glass_to_position(fraction: float, seating_point: int) -> int:
    """Convert an open-glass fraction to a cover position.

    Below ``seating_point`` the cover has already covered all the glass and
    further travel only closes the light gaps between the slats, so shading
    never commands below it.
    """
    fraction = max(0.0, min(1.0, fraction))
    span = 100 - seating_point
    return round(seating_point + fraction * span)


def position_to_glass(position: float, seating_point: int) -> float:
    """Convert a cover position back to the open-glass fraction."""
    span = 100 - seating_point
    if span <= 0:
        return 0.0
    return max(0.0, min(1.0, (position - seating_point) / span))
