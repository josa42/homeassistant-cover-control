"""The changelog is released from, so its shape is part of the build."""

from __future__ import annotations

import pathlib
import re

CHANGELOG = pathlib.Path("CHANGELOG.md")


def sections() -> list[tuple[str, list[str]]]:
    """Each ``## `` heading with the ``### `` headings under it."""
    found: list[tuple[str, list[str]]] = []
    for line in CHANGELOG.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            found.append((line[3:].strip(), []))
        elif line.startswith("### ") and found:
            found[-1][1].append(line[4:].strip())
    return found


def test_a_release_section_appears_once_per_version() -> None:
    names = [name for name, _ in sections()]
    assert len(names) == len(set(names)), f"a version is listed twice: {names}"


def test_no_section_repeats_a_heading() -> None:
    """Releasing renames Unreleased, and a commit landing straight after it
    writes into the released section unless it opens a new one. The tell is a
    second Added or Fixed under a version that already had one."""
    for name, headings in sections():
        assert len(headings) == len(set(headings)), (
            f"'{name}' repeats a heading: {headings}. "
            "An entry was written into a released section instead of Unreleased."
        )


def test_every_entry_sits_under_a_heading() -> None:
    text = CHANGELOG.read_text(encoding="utf-8")
    for match in re.finditer(r"^- \*\*", text, re.M):
        before = text[: match.start()]
        assert "### " in before.rpartition("\n## ")[2], (
            "an entry sits directly under a version with no Added/Changed/Fixed"
        )


def test_released_versions_carry_a_date() -> None:
    for name, _ in sections():
        if name == "Unreleased":
            continue
        assert re.fullmatch(r"\d+\.\d+\.\d+ - \d{4}-\d{2}-\d{2}", name), name
