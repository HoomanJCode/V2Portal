"""Settings editor."""

from __future__ import annotations

from ..engines.binary import BinaryError, update_binary
from . import widgets


def _split(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


def run(store, controller=None) -> None:
    settings = store.config.settings
    while True:
        action = widgets.menu(
            "Settings",
            [
                ("listen", f"Listen address: {settings.listen}"),
                ("port", f"Mixed port: {settings.mixed_port}"),
                ("lan", f"Allow LAN sharing: {'on' if settings.allow_lan else 'off'}"),
                ("auth", f"Inbound auth: {'on' if settings.inbound_auth.get('enabled') else 'off'}"),
                ("dns", f"DNS: {', '.join(settings.dns)}"),
                ("loglevel", f"Log level: {settings.log_level}"),
                ("testurl", f"Test URL: {settings.test_url}"),
                ("engine", f"Default engine: {settings.default_engine}"),
                ("traffic", f"Traffic stats: {'on' if settings.traffic_api else 'off'}"),
                ("updates", "Update engine binaries"),
                ("back", "Back"),
            ],
        )
        if action is None or action == "back":
            return
        if action == "listen":
            settings.listen = widgets.input_text("Listen address", settings.listen)
        elif action == "port":
            settings.mixed_port = widgets.input_int("Mixed port", settings.mixed_port)
        elif action == "lan":
            settings.allow_lan = widgets.confirm("Allow LAN sharing?")
        elif action == "auth":
            settings.inbound_auth["enabled"] = widgets.confirm("Enable inbound auth?")
            if settings.inbound_auth["enabled"]:
                settings.inbound_auth["username"] = widgets.input_text("Username")
                settings.inbound_auth["password"] = widgets.input_secret("Password")
        elif action == "dns":
            settings.dns = _split(widgets.input_text("DNS servers (comma separated)", ",".join(settings.dns)))
        elif action == "loglevel":
            settings.log_level = widgets.input_text("Log level", settings.log_level)
        elif action == "testurl":
            settings.test_url = widgets.input_text("Test URL", settings.test_url)
        elif action == "engine":
            engine = widgets.menu(
                "Default engine", [("sing-box", "sing-box"), ("xray", "xray")]
            )
            if engine:
                settings.default_engine = engine
        elif action == "traffic":
            settings.traffic_api = widgets.confirm("Enable traffic stats (sing-box Clash API)?")
            if settings.traffic_api:
                settings.traffic_api_port = widgets.input_int("Traffic API port", settings.traffic_api_port)
        elif action == "updates":
            run_updates(store, controller)
        store.save()


def run_updates(store, controller=None) -> None:
    """Explicitly update selected auto-managed engines after confirmation."""
    selection = widgets.menu(
        "Engine updates",
        [
            ("sing-box", "Update sing-box"),
            ("xray", "Update xray"),
            ("both", "Update both"),
            ("back", "Cancel"),
        ],
    )
    if not selection or selection == "back":
        return
    if not widgets.confirm("Download and replace the selected engine binary/binaries?"):
        widgets.show_message("Cancelled", "No engine binaries were changed.")
        return

    engines = ["sing-box", "xray"] if selection == "both" else [selection]
    messages: list[str] = []
    for engine in engines:
        status = getattr(controller, "status", None)
        running = bool(
            status
            and getattr(status, "state", "") == "connected"
            and getattr(status, "engine", "") == engine
        )
        try:
            info = update_binary(
                engine,
                store.config.engines.get(engine, {}),
                running=running,
            )
        except BinaryError as exc:
            messages.append(f"{engine}: failed — {exc}")
            continue
        previous = info.previous_version or "not installed"
        messages.append(f"{engine}: {previous} -> {info.version}")
    widgets.show_message("Engine updates", "\\n".join(messages))
