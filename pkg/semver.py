"""Semantic-version parsing, ordering, and range matching for YubaPKG."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import total_ordering


_VERSION = re.compile(
    r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?\Z"
)


@total_ordering
@dataclass(frozen=True)
class Version:
    major: int
    minor: int
    patch: int
    prerelease: tuple[int | str, ...] = ()
    build: str = ""

    @classmethod
    def parse(cls, value: str) -> Version:
        if not isinstance(value, str):
            raise ValueError(f"Invalid semantic version: {value!r}")
        match = _VERSION.fullmatch(value)
        if match is None:
            raise ValueError(
                f"Invalid semantic version '{value}'; expected MAJOR.MINOR.PATCH."
            )
        prerelease = match.group(4)
        identifiers: tuple[int | str, ...] = ()
        if prerelease:
            parts: list[int | str] = []
            for item in prerelease.split("."):
                if item.isdigit():
                    if len(item) > 1 and item.startswith("0"):
                        raise ValueError(
                            f"Invalid semantic version '{value}': "
                            "numeric prerelease identifiers cannot have leading zeroes."
                        )
                    parts.append(int(item))
                else:
                    parts.append(item)
            identifiers = tuple(parts)
        return cls(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            identifiers,
            match.group(5) or "",
        )

    def __str__(self) -> str:
        value = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            value += "-" + ".".join(map(str, self.prerelease))
        if self.build:
            value += "+" + self.build
        return value

    def _precedence(self) -> tuple[object, ...]:
        if not self.prerelease:
            return self.major, self.minor, self.patch, 1, ()
        return self.major, self.minor, self.patch, 0, self.prerelease

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return (
            self.major,
            self.minor,
            self.patch,
            self.prerelease,
        ) == (
            other.major,
            other.minor,
            other.patch,
            other.prerelease,
        )

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        core = (self.major, self.minor, self.patch)
        other_core = (other.major, other.minor, other.patch)
        if core != other_core:
            return core < other_core
        if not self.prerelease:
            return False if not other.prerelease else False
        if not other.prerelease:
            return True
        for left, right in zip(self.prerelease, other.prerelease):
            if left == right:
                continue
            if isinstance(left, int) and isinstance(right, str):
                return True
            if isinstance(left, str) and isinstance(right, int):
                return False
            return left < right
        return len(self.prerelease) < len(other.prerelease)

    def __hash__(self) -> int:
        return hash((self.major, self.minor, self.patch, self.prerelease))


def _wildcard_bounds(token: str) -> tuple[Version | None, Version | None] | None:
    parts = token.split(".")
    if len(parts) not in (1, 2, 3) or not any(
        part.casefold() in ("x", "*") for part in parts
    ):
        return None
    wildcard_index = next(
        index for index, part in enumerate(parts)
        if part.casefold() in ("x", "*")
    )
    if any(part.casefold() not in ("x", "*") for part in parts[wildcard_index:]):
        raise ValueError(f"Invalid version wildcard '{token}'.")
    prefix = parts[:wildcard_index]
    if not prefix:
        return None, None
    if any(not part.isdigit() or (len(part) > 1 and part.startswith("0")) for part in prefix):
        raise ValueError(f"Invalid version wildcard '{token}'.")
    values = [int(part) for part in prefix]
    lower = Version(*(values + [0] * (3 - len(values))))
    if len(values) == 1:
        upper = Version(values[0] + 1, 0, 0)
    elif len(values) == 2:
        upper = Version(values[0], values[1] + 1, 0)
    else:
        return lower, Version(lower.major, lower.minor, lower.patch + 1)
    return lower, upper


def _satisfies_comparator(version: Version, token: str) -> bool:
    if token == "*":
        return True
    wildcard = _wildcard_bounds(token)
    if wildcard is not None:
        lower, upper = wildcard
        return (
            (lower is None or version >= lower)
            and (upper is None or version < upper)
        )

    match = re.fullmatch(r"(>=|<=|>|<|=|\^|~)?(.+)", token)
    if match is None:
        raise ValueError(f"Invalid version requirement '{token}'.")
    operator, raw_version = match.group(1) or "=", match.group(2)
    target = Version.parse(raw_version)
    if operator == "=":
        return version == target
    if operator == ">":
        return version > target
    if operator == ">=":
        return version >= target
    if operator == "<":
        return version < target
    if operator == "<=":
        return version <= target
    if operator == "~":
        upper = Version(target.major, target.minor + 1, 0)
        return version >= target and version < upper
    if target.major:
        upper = Version(target.major + 1, 0, 0)
    elif target.minor:
        upper = Version(0, target.minor + 1, 0)
    else:
        upper = Version(0, 0, target.patch + 1)
    return version >= target and version < upper


def satisfies(version: str | Version, requirement: str) -> bool:
    """Return whether a full semantic version satisfies an AND-only range."""
    candidate = version if isinstance(version, Version) else Version.parse(version)
    if not isinstance(requirement, str) or not requirement.strip():
        raise ValueError("Version requirement must not be empty.")
    tokens = re.split(r"[\s,]+", requirement.strip())
    if any(not token for token in tokens):
        raise ValueError(f"Invalid version requirement '{requirement}'.")
    validate_requirement(requirement)
    allows_prerelease = False
    for token in tokens:
        match = re.fullmatch(r"(?:>=|<=|>|<|=|\^|~)?(.+)", token)
        if match is None or _wildcard_bounds(token) is not None:
            continue
        target = Version.parse(match.group(1))
        if (
            target.prerelease
            and (candidate.major, candidate.minor, candidate.patch)
            == (target.major, target.minor, target.patch)
        ):
            allows_prerelease = True
            break
    if candidate.prerelease and not allows_prerelease:
        return False
    return all(_satisfies_comparator(candidate, token) for token in tokens)


def validate_requirement(requirement: str) -> None:
    if not isinstance(requirement, str) or not requirement.strip():
        raise ValueError("Version requirement must not be empty.")
    tokens = re.split(r"[\s,]+", requirement.strip())
    if any(not token for token in tokens):
        raise ValueError(f"Invalid version requirement '{requirement}'.")
    for token in tokens:
        if token in ("*", "x", "X"):
            continue
        wildcard = _wildcard_bounds(token)
        if wildcard is not None:
            continue
        match = re.fullmatch(r"(>=|<=|>|<|=|\^|~)?(.+)", token)
        if match is None:
            raise ValueError(f"Invalid version requirement '{token}'.")
        Version.parse(match.group(2))
