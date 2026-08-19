"""Config persistence and CRUD for v2raycli."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Callable

from . import config
from .models import (
    Config,
    Group,
    Profile,
    RoutingConfig,
    RoutingRule,
    Settings,
    Subscription,
)


class ConfigLoadError(ValueError):
    """Raised when the on-disk config cannot be decoded or validated."""


class ConfigStore:
    """Load/save the config file and expose CRUD helpers.

    Pass an explicit ``path`` for tests or custom locations; otherwise the
    platform config dir is used.
    """

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else config.CONFIG_PATH
        self.config = self.default()
        self.pre_write_hooks: list[Callable] = []

    @staticmethod
    def default() -> Config:
        return Config(
            schema_version=config.SCHEMA_VERSION,
            settings=Settings(),
            routing=RoutingConfig(),
            engines={k: dict(v) for k, v in config.DEFAULT_ENGINES.items()},
            profiles=[],
            subscriptions=[],
            groups=[],
        )

    # -- persistence ---------------------------------------------------------

    def load(self) -> Config:
        if not self.path.exists():
            self.config = self.default()
            self.save()
            return self.config
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("config root must be a JSON object")
            for key in ("settings", "routing", "engines"):
                if key in raw and not isinstance(raw[key], dict):
                    raise ValueError(f"config field {key!r} must be an object")
            for key in ("profiles", "subscriptions", "groups"):
                if key in raw and not isinstance(raw[key], list):
                    raise ValueError(f"config field {key!r} must be a list")
            self.config = Config.from_dict(raw)
        except (OSError, ValueError, TypeError, AttributeError, KeyError) as exc:
            raise ConfigLoadError(f"could not load config {self.path}: {exc}") from exc
        return self.config

    def register_pre_write_hook(self, hook: Callable) -> None:
        """Register ``hook(store, reason)`` to run before destructive mutations."""
        self.pre_write_hooks.append(hook)

    def notify_destructive(self, reason: str) -> None:
        """Fire pre-write hooks (e.g. an automatic config backup)."""
        for hook in self.pre_write_hooks:
            hook(self, reason)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = self.config.to_dict()
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix="config-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    # -- profiles ------------------------------------------------------------

    def add_profile(self, profile: Profile) -> Profile:
        self.config.profiles.append(profile)
        return profile

    def get_profile(self, profile_id: str) -> Profile | None:
        return next((p for p in self.config.profiles if p.id == profile_id), None)

    def list_profiles(self) -> list[Profile]:
        return list(self.config.profiles)

    def remove_profile(self, profile_id: str) -> bool:
        profile = self.get_profile(profile_id)
        if profile is None:
            return False
        self.notify_destructive("remove-profile")
        self.config.profiles.remove(profile)
        for sub in self.config.subscriptions:
            if profile_id in sub.profile_ids:
                sub.profile_ids.remove(profile_id)
        for group in self.config.groups:
            if profile_id in group.profile_ids:
                group.profile_ids.remove(profile_id)
        return True

    # -- subscriptions -------------------------------------------------------

    def add_subscription(self, sub: Subscription) -> Subscription:
        self.config.subscriptions.append(sub)
        return sub

    def get_subscription(self, sub_id: str) -> Subscription | None:
        return next((s for s in self.config.subscriptions if s.id == sub_id), None)

    def list_subscriptions(self) -> list[Subscription]:
        return list(self.config.subscriptions)

    def remove_subscription(self, sub_id: str) -> bool:
        if self.get_subscription(sub_id) is None:
            return False
        self.notify_destructive("remove-subscription")
        self.config.subscriptions = [s for s in self.config.subscriptions if s.id != sub_id]
        for profile in self.config.profiles:
            if profile.subscription_id == sub_id:
                profile.subscription_id = None
        return True

    # -- groups --------------------------------------------------------------

    def add_group(self, group: Group) -> Group:
        self.config.groups.append(group)
        return group

    def get_group(self, group_id: str) -> Group | None:
        return next((g for g in self.config.groups if g.id == group_id), None)

    def list_groups(self) -> list[Group]:
        return list(self.config.groups)

    def remove_group(self, group_id: str) -> bool:
        group = self.get_group(group_id)
        if group is None:
            return False
        self.notify_destructive("remove-group")
        self.config.groups.remove(group)
        return True

    # -- routing -------------------------------------------------------------

    def add_rule(self, rule: RoutingRule) -> RoutingRule:
        self.config.routing.rules.append(rule)
        return rule

    def list_rules(self) -> list[RoutingRule]:
        return list(self.config.routing.rules)

    def remove_rule(self, rule_id: str) -> bool:
        rule = next((r for r in self.config.routing.rules if r.id == rule_id), None)
        if rule is None:
            return False
        self.notify_destructive("remove-rule")
        self.config.routing.rules.remove(rule)
        return True

    # -- settings & engines --------------------------------------------------

    def update_settings(self, **kwargs) -> Settings:
        for key, value in kwargs.items():
            if hasattr(self.config.settings, key):
                setattr(self.config.settings, key, value)
        return self.config.settings

    def update_engine(self, name: str, **kwargs) -> dict:
        engine = self.config.engines.setdefault(name, {})
        engine.update(kwargs)
        return engine
