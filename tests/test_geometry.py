"""Tests for the sun geometry and the motor/glass mapping."""

from __future__ import annotations

import pytest

from custom_components.cover_control import geometry


@pytest.mark.parametrize(
    ("sun", "window", "expected"),
    [
        (180.0, 180.0, 0.0),
        (90.0, 180.0, -90.0),  # east sun on a south window is the morning side
        (270.0, 180.0, 90.0),  # west sun is the afternoon side
        (10.0, 350.0, 20.0),  # wraps across north
        (350.0, 10.0, -20.0),
    ],
)
def test_azimuth_delta(sun: float, window: float, expected: float) -> None:
    assert geometry.azimuth_delta(sun, window) == pytest.approx(expected)


def test_sun_below_horizon_is_never_on_the_window() -> None:
    assert not geometry.sun_on_window(-0.5, 0.0, 90.0, 90.0)


def test_field_of_view_is_asymmetric() -> None:
    """A balcony on one side only blocks that side."""
    assert geometry.sun_on_window(30.0, -60.0, 90.0, 30.0)
    assert not geometry.sun_on_window(30.0, 60.0, 90.0, 30.0)


def test_profile_angle_equals_elevation_head_on() -> None:
    assert geometry.profile_angle(45.0, 0.0) == pytest.approx(45.0)


def test_profile_angle_rises_with_obliqueness() -> None:
    """The more oblique the sun, the shallower it enters, so the cover stays higher."""
    head_on = geometry.profile_angle(30.0, 0.0)
    oblique = geometry.profile_angle(30.0, 70.0)
    assert oblique > head_on


def test_grazing_sun_cannot_enter() -> None:
    assert geometry.profile_angle(30.0, 90.0) == pytest.approx(90.0)
    assert geometry.penetration_depth(1.0, 0.0, 2.0, 90.0) == 0.0


def test_required_fraction_matches_worked_example() -> None:
    """A 2 m window, 45 degree profile, 1 m allowed depth leaves half the glass."""
    assert geometry.required_glass_fraction(1.0, 0.0, 2.0, 45.0) == pytest.approx(0.5)


def test_zero_depth_closes_completely() -> None:
    """'No sun in the room' necessarily means no open glass."""
    assert geometry.required_glass_fraction(0.0, 0.0, 2.0, 45.0) == 0.0


def test_sill_height_buys_free_depth() -> None:
    """Sun entering above a high sill lands further in, so it shades earlier."""
    low = geometry.required_glass_fraction(1.0, 0.0, 2.0, 45.0)
    high = geometry.required_glass_fraction(1.0, 0.9, 2.0, 45.0)
    assert high < low


def test_grazing_sun_needs_no_shading() -> None:
    assert geometry.required_glass_fraction(0.0, 0.0, 2.0, 90.0) == 1.0


def test_rolladen_never_commands_below_the_seating_point() -> None:
    """Below the seating point only the light gaps close, which buys no shading."""
    assert geometry.glass_to_position(0.0, 25) == 25
    assert geometry.glass_to_position(1.0, 25) == 100


def test_raffstore_uses_the_whole_travel() -> None:
    assert geometry.glass_to_position(0.0, 0) == 0
    assert geometry.glass_to_position(0.5, 0) == 50


@pytest.mark.parametrize("seating", [0, 25, 40])
@pytest.mark.parametrize("fraction", [0.0, 0.25, 0.5, 1.0])
def test_position_glass_roundtrip(seating: int, fraction: float) -> None:
    position = geometry.glass_to_position(fraction, seating)
    assert geometry.position_to_glass(position, seating) == pytest.approx(
        fraction, abs=0.01
    )


def test_penetration_depth_is_measured_from_the_top_of_the_opening() -> None:
    """Half of a 2 m window open at 45 degrees puts sun 1 m into the room."""
    assert geometry.penetration_depth(0.5, 0.0, 2.0, 45.0) == pytest.approx(1.0)


def test_fully_covered_glass_lets_no_sun_in() -> None:
    """A closed cover must report zero depth, not a ray entering at the sill.

    Regression: with a raised sill the depth was computed from the sill height
    even when no glass was open, so the debug output claimed sun was reaching
    metres into a room the cover had fully shaded.
    """
    assert geometry.penetration_depth(0.0, 0.9, 1.5, 6.77) == 0.0
    assert geometry.penetration_depth(0.0, 0.0, 2.0, 45.0) == 0.0


@pytest.mark.parametrize(
    ("fraction", "expected"),
    [
        (1.0, 1.0),      # fully open stays fully open
        (0.97, 0.75),    # down, never up
        (0.88, 0.75),    # the example this was asked for
        (0.75, 0.75),    # sitting exactly on a step stays there
        (0.26, 0.25),
        (0.1, 0.0),
        (0.0, 0.0),
    ],
)
def test_the_glass_fraction_rounds_down_to_the_step(
    fraction: float, expected: float
) -> None:
    assert geometry.step_glass_fraction(fraction, 25) == pytest.approx(expected)


def test_a_step_that_does_not_divide_the_travel_keeps_fully_open() -> None:
    """Otherwise a cover needing no shading would be driven down a step."""
    assert geometry.step_glass_fraction(1.0, 30) == 1.0
    assert geometry.step_glass_fraction(0.97, 30) == pytest.approx(0.9)


def test_a_step_of_zero_leaves_the_fraction_alone() -> None:
    assert geometry.step_glass_fraction(0.88, 0) == pytest.approx(0.88)


@pytest.mark.parametrize("step", [5, 10, 20, 25, 30, 50])
def test_stepping_never_lets_more_sun_in(step: int) -> None:
    """Rounding the wrong way would break the promise the whole thing makes."""
    for raw in range(0, 101):
        fraction = raw / 100
        assert geometry.step_glass_fraction(fraction, step) <= fraction + 1e-9


def test_the_step_is_a_share_of_the_glass_not_of_the_travel() -> None:
    """A roller shutter's light gaps sit below its seating point.

    So a quarter of the glass is a quarter of the window for both kinds, even
    though it is a different distance of travel.
    """
    stops = [
        geometry.glass_to_position(geometry.step_glass_fraction(f / 100, 25), seat)
        for seat in (0, 25)
        for f in (100, 75, 50, 25, 0)
    ]
    assert stops[:5] == [100, 75, 50, 25, 0], "venetian blind"
    assert stops[5:] == [100, 81, 62, 44, 25], "roller shutter with light gaps"
