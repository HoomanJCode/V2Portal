"""Settings editor."""

from __future__ import annotations

from . import widgets


def _split(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


def run(store) -> None:
    settings = store.config.settings
    while True:
        action = widgets.menu(
            "Settings",
            [
                ("listen", f"Listen address: {settings.listen}"),
                ("port", f"Mixed port: {settings.mixed_port}"),
                ("auth", f"Inbound auth: {'on' if settings.inbound_auth.get('enabled') else 'off'}"),
                ("dns", f"DNS: {', '.join(settings.dns)}"),
                ("loglevel", f"Log level: {settings.log_level}"),
                ("testurl", f"Test URL: {settings.test_url}"),
                ("engine", f"Default engine: {settings.default_engine}"),
                ("traffic", f"Traffic stats: {'on' if settings.traffic_api else 'off'}"),
                ("back", "Back"),
            ],
        )
        if action is None or action == "back":
            return
        if action == "listen":
            settings.listen = widgets.input_text("Listen address", settings.listen)
        elif action == "port":
            settings.mixed_port = widgets.input_int("Mixed port", settings.mixed_port)
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
        store.save()
