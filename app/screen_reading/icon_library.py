from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


CATALOG_VERSION = "fluent_system_icons_catalog_v1"
FLUENT_FAMILY = "microsoft_fluent_system_icons"
FLUENT_REPOSITORY = "https://github.com/microsoft/fluentui-system-icons"
FLUENT_SVG_PACKAGE = "@fluentui/svg-icons"


@dataclass(frozen=True)
class FluentIconEntry:
    name: str
    aliases: tuple[str, ...]
    style: str = "regular"
    size: int = 24

    @property
    def icon_id(self) -> str:
        return f"{self.name}_{self.size}_{self.style}"


DEFAULT_FLUENT_ICON_CATALOG: tuple[FluentIconEntry, ...] = (
    FluentIconEntry("arrow_left", ("back", "browser back", "go back", "left arrow", "arrow left")),
    FluentIconEntry("arrow_right", ("forward", "browser forward", "go forward", "right arrow", "arrow right")),
    FluentIconEntry("arrow_clockwise", ("refresh", "reload", "browser refresh", "arrow clockwise")),
    FluentIconEntry("dismiss", ("close", "dismiss", "cancel", "window close")),
    FluentIconEntry("search", ("search", "find", "magnifier", "magnifying glass")),
    FluentIconEntry("settings", ("settings", "setting", "gear", "cog")),
    FluentIconEntry("home", ("home", "homepage", "browser home")),
    FluentIconEntry("navigation", ("menu", "hamburger", "navigation menu")),
    FluentIconEntry("more_horizontal", ("more", "overflow", "ellipsis", "more horizontal")),
    FluentIconEntry("chevron_left", ("chevron left", "previous", "collapse left")),
    FluentIconEntry("chevron_right", ("chevron right", "next", "expand right")),
    FluentIconEntry("add", ("add", "plus", "new")),
    FluentIconEntry("subtract", ("remove", "minus", "subtract")),
)


class MicrosoftFluentIconLibrary:
    """Small local catalog matcher for Microsoft Fluent System Icons.

    This intentionally performs catalog/semantic confirmation only. It does not
    claim a shape-template match, so visual-only candidates remain blocked from
    execution until a stronger provider or verifier confirms them.
    """

    provider_id = FLUENT_FAMILY
    status = "connected"
    version = CATALOG_VERSION

    def __init__(self, catalog: tuple[FluentIconEntry, ...] = DEFAULT_FLUENT_ICON_CATALOG) -> None:
        self.catalog = catalog

    def describe_slot(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "provider": self.provider_id,
            "catalog_version": self.version,
            "source_repository": FLUENT_REPOSITORY,
            "package_reference": FLUENT_SVG_PACKAGE,
            "intended_use": "Catalog-level confirmation for no-text icons such as browser_back, refresh, close, search, settings, and menu.",
            "expected_fields": ["icon_id", "family", "bbox", "score", "template_or_model_version"],
            "merge_keys": ["bbox_overlap", "icon_id", "nearby_context"],
        }

    def match(self, element: dict[str, Any]) -> dict[str, Any] | None:
        context = _element_context(element)
        if not context:
            return None

        best: tuple[float, FluentIconEntry, str] | None = None
        for entry in self.catalog:
            for alias in entry.aliases:
                score = _alias_score(context, alias)
                if score <= 0:
                    continue
                if best is None or score > best[0]:
                    best = (score, entry, alias)

        if best is None:
            return None

        score, entry, alias = best
        role = _normalize(str(element.get("role_guess") or element.get("type") or ""))
        if any(token in role.split() for token in ["icon", "toolbar"]):
            score += 0.08
        if element.get("evidence_level") == "visual_region_only":
            score += 0.03
        score = min(score, 0.98)
        if score < 0.68:
            return None

        return {
            "provider": self.provider_id,
            "provider_status": self.status,
            "icon_id": entry.icon_id,
            "family": FLUENT_FAMILY,
            "catalog_name": entry.name,
            "style": entry.style,
            "size": entry.size,
            "score": round(score, 4),
            "match_basis": [f"alias:{alias}", f"catalog:{self.version}"],
            "template_or_model_version": self.version,
            "source": {
                "repository": FLUENT_REPOSITORY,
                "package": FLUENT_SVG_PACKAGE,
                "name_format": "[name]_[size]_[style]",
            },
        }


def _element_context(element: dict[str, Any]) -> str:
    values = [
        element.get("type"),
        element.get("role_guess"),
        element.get("label"),
        element.get("description"),
        element.get("memory_key"),
    ]
    evidence = element.get("evidence")
    if isinstance(evidence, dict):
        fusion = evidence.get("fusion")
        if isinstance(fusion, dict):
            values.extend(fusion.values())
    return _normalize(" ".join(str(value or "") for value in values))


def _alias_score(context: str, alias: str) -> float:
    alias_norm = _normalize(alias)
    if not alias_norm:
        return 0.0
    alias_tokens = alias_norm.split()
    context_tokens = set(context.split())
    if alias_norm in context:
        return 0.86 if len(alias_tokens) > 1 else 0.74
    if alias_tokens and all(token in context_tokens for token in alias_tokens):
        return 0.7
    return 0.0


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.lower())).strip()
