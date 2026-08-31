from v2portal.engines import AUTO, SINGBOX, XRAY, engine_for_kind, get_adapter, resolve_engine


def test_engine_for_kind():
    assert engine_for_kind("ssr") == XRAY
    assert engine_for_kind("hysteria2") == SINGBOX
    assert engine_for_kind("tuic") == SINGBOX
    assert engine_for_kind("vmess") == AUTO


def test_resolve_engine_matrix():
    assert resolve_engine("vmess", "", "", "sing-box") == "sing-box"
    assert resolve_engine("ssr", "", "", "sing-box") == "xray"
    assert resolve_engine("hysteria2", "", "", "sing-box") == "sing-box"
    assert resolve_engine("vmess", "leastLoad", "", "sing-box") == "xray"
    assert resolve_engine("vmess", "", "xray", "sing-box") == "xray"


def test_adapters_registered():
    assert get_adapter("sing-box").name == "sing-box"
    assert get_adapter("xray").name == "xray"
