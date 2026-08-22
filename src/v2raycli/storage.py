"""Config persistence and CRUD for v2raycli."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Callable

from . import config
from .errors import V2RayCLIError
from .models import (
    Config,
    Group,
    Profile,
    RoutingConfig,
    RoutingRule,
    Settings,
    Subscription,
)


class ConfigLoadError(V2RayCLIError, ValueError):
    """Raised when the on-disk config cannot be decoded or validated."""


def _require_dict(value, label: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _require_list(value, label: str) -> list:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return value


def _validate_text_list(value, label: str) -> None:
    for index, item in enumerate(_require_list(value, label)):
        if not isinstance(item, str):
            raise ValueError(f"{label}[{index}] must be text")


def _validate_persisted_shape(raw: dict) -> None:
    """Reject wrong-shaped nested values before dataclass construction."""
    settings = _require_dict(raw.get("settings", {}), "config settings")
    for key in ("listen", "log_level", "test_url", "default_engine"):
        if key in settings and not isinstance(settings[key], str):
            raise ValueError(f"settings.{key} must be text")
    for key in ("mixed_port", "socks_port", "http_port", "backup_keep", "traffic_api_port"):
        if key in settings and (
            isinstance(settings[key], bool) or not isinstance(settings[key], int)
        ):
            raise ValueError(f"settings.{key} must be an integer")
    for key in ("allow_lan", "traffic_api"):
        if key in settings and not isinstance(settings[key], bool):
            raise ValueError(f"settings.{key} must be boolean")
    if "inbound_auth" in settings:
        auth = _require_dict(settings["inbound_auth"], "settings.inbound_auth")
        if "enabled" in auth and not isinstance(auth["enabled"], bool):
            raise ValueError("settings.inbound_auth.enabled must be boolean")
        for key in ("username", "password"):
            if key in auth and not isinstance(auth[key], str):
                raise ValueError(f"settings.inbound_auth.{key} must be text")
    if "dns" in settings:
        _validate_text_list(settings["dns"], "settings.dns")

    routing = _require_dict(raw.get("routing", {}), "config routing")
    if "mode" in routing and not isinstance(routing["mode"], str):
        raise ValueError("routing.mode must be text")
    rules = _require_list(routing.get("rules", []), "config routing rules")
    for index, rule in enumerate(rules):
        rule = _require_dict(rule, f"config routing rules[{index}]")
        if "action" in rule and not isinstance(rule["action"], str):
            raise ValueError(f"config routing rules[{index}].action must be text")
        if "target_id" in rule and rule["target_id"] is not None and not isinstance(
            rule["target_id"], str
        ):
            raise ValueError(f"config routing rules[{index}].target_id must be text or null")
        if "enabled" in rule and not isinstance(rule["enabled"], bool):
            raise ValueError(f"config routing rules[{index}].enabled must be boolean")
        if "match" in rule:
            match = _require_dict(rule["match"], f"config routing rules[{index}].match")
            for key, values in match.items():
                _validate_text_list(values, f"config routing rules[{index}].match.{key}")

    engines = _require_dict(raw.get("engines", {}), "config engines")
    for name, options in engines.items():
        if not isinstance(name, str):
            raise ValueError("config engine names must be text")
        options = _require_dict(options, f"config engines.{name}")
        for key in ("binary_path", "version"):
            if key in options and not isinstance(options[key], str):
                raise ValueError(f"config engines.{name}.{key} must be text")

    profiles = _require_list(raw.get("profiles", []), "config profiles")
    for index, profile in enumerate(profiles):
        profile = _require_dict(profile, f"config profiles[{index}]")
        for key in ("id", "name", "kind", "engine", "source", "created_at", "updated_at"):
            if key in profile and not isinstance(profile[key], str):
                raise ValueError(f"config profiles[{index}].{key} must be text")
        for key in ("subscription_id",):
            if key in profile and profile[key] is not None and not isinstance(profile[key], str):
                raise ValueError(f"config profiles[{index}].{key} must be text or null")
        if "outbound" in profile:
            _require_dict(profile["outbound"], f"config profiles[{index}].outbound")
        if "vpn" in profile and profile["vpn"] is not None:
            _require_dict(profile["vpn"], f"config profiles[{index}].vpn")
        if "enabled" in profile and not isinstance(profile["enabled"], bool):
            raise ValueError(f"config profiles[{index}].enabled must be boolean")
        for key in ("traffic_up", "traffic_down"):
            if key in profile and (
                isinstance(profile[key], bool) or not isinstance(profile[key], int)
            ):
                raise ValueError(f"config profiles[{index}].{key} must be an integer")

    subscriptions = _require_list(raw.get("subscriptions", []), "config subscriptions")
    for index, subscription in enumerate(subscriptions):
        subscription = _require_dict(subscription, f"config subscriptions[{index}]")
        for key in ("id", "name", "url"):
            if key in subscription and not isinstance(subscription[key], str):
                raise ValueError(f"config subscriptions[{index}].{key} must be text")
        for key in ("user_agent", "last_updated", "expires"):
            if key in subscription and subscription[key] is not None and not isinstance(
                subscription[key], str
            ):
                raise ValueError(f"config subscriptions[{index}].{key} must be text or null")
        if "profile_ids" in subscription:
            _validate_text_list(subscription["profile_ids"], f"config subscriptions[{index}].profile_ids")
        for key in ("traffic_used", "auto_update_days"):
            if key in subscription and (
                isinstance(subscription[key], bool) or not isinstance(subscription[key], int)
            ):
                raise ValueError(f"config subscriptions[{index}].{key} must be an integer")
        if "enabled" in subscription and not isinstance(subscription["enabled"], bool):
            raise ValueError(f"config subscriptions[{index}].enabled must be boolean")

    groups = _require_list(raw.get("groups", []), "config groups")
    for index, group in enumerate(groups):
        group = _require_dict(group, f"config groups[{index}]")
        for key in ("id", "name", "type", "strategy", "engine"):
            if key in group and not isinstance(group[key], str):
                raise ValueError(f"config groups[{index}].{key} must be text")
        if "profile_ids" in group:
            _validate_text_list(group["profile_ids"], f"config groups[{index}].profile_ids")
        if "enabled" in group and not isinstance(group["enabled"], bool):
            raise ValueError(f"config groups[{index}].enabled must be boolean")
        for key in ("traffic_up", "traffic_down"):
            if key in group and (
                isinstance(group[key], bool) or not isinstance(group[key], int)
            ):
                raise ValueError(f"config groups[{index}].{key} must be an integer")

    servers = _require_list(raw.get("servers", []), "config servers")
    for index, server in enumerate(servers):
        server = _require_dict(server, f"config servers[{index}]")
        for key in ("id", "name", "protocol", "outbound_id", "outbound_type", "listen"):
            if key in server and not isinstance(server[key], str):
                raise ValueError(f"config servers[{index}].{key} must be text")
        if "port" in server and (
            isinstance(server["port"], bool) or not isinstance(server["port"], int)
        ):
            raise ValueError(f"config servers[{index}].port must be an integer")
        if "enabled" in server and not isinstance(server["enabled"], bool):
            raise ValueError(f"config servers[{index}].enabled must be boolean")
        for key in ("traffic_up", "traffic_down"):
            if key in server and (
                isinstance(server[key], bool) or not isinstance(server[key], int)
            ):
                raise ValueError(f"config servers[{index}].{key} must be an integer")
        if "auth" in server:
            auth = _require_dict(server["auth"], f"config servers[{index}].auth")
            if "enabled" in auth and not isinstance(auth["enabled"], bool):
                raise ValueError(f"config servers[{index}].auth.enabled must be boolean")
            for key in ("username", "password"):
                if key in auth and not isinstance(auth[key], str):
                    raise ValueError(f"config servers[{index}].auth.{key} must be text")


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
            schema_version = raw.get("schema_version", config.SCHEMA_VERSION)
            if (
                isinstance(schema_version, bool)
                or not isinstance(schema_version, int)
                or schema_version != config.SCHEMA_VERSION
            ):
                raise ValueError(f"unsupported schema_version: {schema_version}")
            _validate_persisted_shape(raw)
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
        except OSError as exc:
            raise ValueError(f"failed to save config: {exc}") from exc
        finally:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

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
        self.config.routing.rules = [
            r for r in self.config.routing.rules if r.target_id != profile_id
        ]
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
        self.config.routing.rules = [
            r for r in self.config.routing.rules if r.target_id != group_id
        ]
        return True

    # -- servers -------------------------------------------------------------

    def add_server(self, server: Server) -> Server:
        self.config.servers.append(server)
        return server

    def get_server(self, server_id: str) -> Server | None:
        return next((s for s in self.config.servers if s.id == server_id), None)

    def list_servers(self) -> list[Server]:
        return list(self.config.servers)

    def remove_server(self, server_id: str) -> bool:
        server = self.get_server(server_id)
        if server is None:
            return False
        self.notify_destructive("remove-server")
        self.config.servers.remove(server)
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
