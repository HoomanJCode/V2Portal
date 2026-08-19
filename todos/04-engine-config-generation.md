# Phase 04 — Engine Adapters, Binaries & Config Generation

> **Status:** ✅ Implemented (commits 961a539 → 3b443d3).
> The **verification spike** (running real sing-box/xray binaries) is deferred —
> no engine binaries are available in the offline dev environment.

Goal: a working **engine adapter layer** (sing-box + xray), auto-download of
both binaries, and valid config generation for any target with split routing.
This is where mixed-inbound, chain (`detour` / `proxySettings`), and balancer
strategy details must be verified and locked in.

## Tasks

### Engine adapter (`engines/base.py`)

- [x] `EngineAdapter` ABC: `name`, `supported_kinds`, `supported_strategies`,
      `generate(settings, routing, target) -> dict`, `run_args`,
      `validate_args`, `binary_filename(platform, arch)`.
- [x] `resolve_engine(kind, strategy, explicit_engine) -> EngineName` —
      (lives in `engines/__init__.py`, added in Phase 03): explicit wins;
      ssr→xray; hysteria2/tuic→sing-box; leastLoad→xray; else default.
- [x] `get_adapter(name) -> EngineAdapter` registry (class-decorator registration).

### Binary management (`engines/binary.py`)

- [x] `locate_binary(engine, options) -> path`: absolute/system/`auto` (cache hit
      in `BIN_DIR`, else download).
- [x] `download_binary(engine, version, platform, arch) -> path`: OS/arch →
      release asset for `SagerNet/sing-box` and `XTLS/Xray-core`; extract
      zip/tar.gz; chmod +x. (Asset naming is best-effort — verify against the
      release listing.)
- [x] `get_version(engine, path)` (runs `<binary> version`).
- [x] Cache hit when version matches (locate returns cached binary).

### sing-box generator (`engines/singbox.py`)

- [x] `generate(...)`: `log`, `dns`, one `mixed` inbound (socks5+http single
      port, `listen`, optional `users` when auth enabled), outbounds per profile
      + `direct`/`block` fallbacks.
- [x] Single → route to outbound; `urltest`/`selector` for balancer; `detour`
      for chains (route to last hop).
- [x] Split routing → native rules (`domain_suffix/keyword/regex`, `ip_cidr`,
      `geoip`/`geosite`); fallback = selected target.

### xray generator (`engines/xray.py`)

- [x] `generate(...)`: `log`, `inbounds` (`socks` with optional auth), outbounds,
      `routing` (rules + `balancers`), `dns`.
- [x] Balancer → `routing.balancers` entry with `strategy.type`; chain →
      outbound base `proxySettings.tag` (route to last hop).

### Runtime config + validation

- [x] `write_runtime_config(engine, config_dict) -> path` into `RUNTIME_DIR`.
- [x] `validate_config(engine, path)` — sing-box `check` / xray `run -test`.

## Verification spike (needs real binaries — deferred)

- [ ] sing-box `mixed` inbound: confirm socks5+http on one port (both clients).
- [ ] sing-box selector `strategy` values (`random`, `round_robin`) + `urltest`.
- [ ] xray socks inbound HTTP CONNECT; balancer strategy strings; `proxySettings`
      chaining; sing-box `detour` chaining (confirm egress via last hop).
- [ ] Lock verified shapes into `config_gen` tests + code comments.

## Tests

- [x] `test_config_gen.py`: golden tests — single/balancer/chain per engine
      produce expected `outbounds`/`routing`/`inbounds`; tag stability; chain
      order; split-routing rule emission for both engines.
- [x] `test_binary.py`: asset-name mapping for both engines; locate
      (absolute/system/cached) and `get_version` (no network in CI).
- [x] `test_engine.py`: `resolve_engine` matrix + registry.

## Definition of Done

- [ ] Both engines' `check`/`-test` pass on generated configs — **deferred**
      (no binaries offline); run the spike before Phase 05 manual testing.
- [ ] SOCKS+HTTP single port and 2-hop chain confirmed on the pinned builds —
      **deferred**; document + add fixtures when verified.
- [x] `pytest` passes — 70 tests.
