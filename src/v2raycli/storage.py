"""Config persistence and CRUD for v2raycli."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

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


class ConfigStore:
    """Load/save the config file and expose CRUD helpers.

    Pass an explicit ``path`` for tests or custom locations; otherwise the
    platform config dir is used.
    """

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else config.CONFIG_PATH
        self.config = self.default()

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
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.config = Config.from_dict(raw)
        return self.config

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
        before = len(self.config.groups)
        self.config.groups = [g for g in self.config.groups if g.id != group_id]
        return len(self.config.groups) < before

    # -- routing -------------------------------------------------------------

    def add_rule(self, rule: RoutingRule) -> RoutingRule:
        self.config.routing.rules.append(rule)
        return rule

    def list_rules(self) -> list[RoutingRule]:
        return list(self.config.routing.rules)

    def remove_rule(self, rule_id: str) -> bool:
        before = len(self.config.routing.rules)
        self.config.routing.rules = [r for r in self.config.routing.rules if r.id != rule_id]
        return len(self.config.routing.rules) < before

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
