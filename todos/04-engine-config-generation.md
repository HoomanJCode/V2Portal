# Phase 04 — Engine Adapters, Binaries & Config Generation

> **Status:** ✅ Implemented (commits 961a539 → 3b443d3).
> ✅ Verification spike run against sing-box 1.13.19 + xray 26.3.27 (see below).

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
      port, effective `listen`/`allow_lan` binding, optional `users` when auth enabled), outbounds per profile
      + `direct`/`block` fallbacks.
- [x] Single → route to outbound; `urltest`/`selector` for balancer; `detour`
      for chains (route to last hop).
- [x] Split routing → native rules (`domain_suffix/keyword/regex`, `ip_cidr`,
      `geoip`/`geosite`); fallback = selected target.

### xray generator (`engines/xray.py`)

- [x] `generate(...)`: `log`, `inbounds` (`socks` + adjacent HTTP CONNECT
      inbound with optional auth), outbounds, `routing` (rules + `balancers`), `dns`.
- [x] Balancer → `routing.balancers` entry with `strategy.type`; chain →
      outbound base `proxySettings.tag` (route to last hop).

### Runtime config + validation

- [x] `write_runtime_config(engine, config_dict) -> path` into `RUNTIME_DIR`.
- [x] `validate_config(engine, path)` — sing-box `check` / xray `run -test`.
- [x] Reject malformed persisted manual outbounds before xray config generation.
- [x] Reject malformed persisted VMess/VLESS and server-based shapes before sing-box generation.

## Verification spike (run against sing-box 1.13.19 + xray 26.3.27)

- [x] sing-box `mixed` inbound: socks5 + HTTP (plain + CONNECT) on one port —
      live curl through both.
- [x] sing-box `urltest` balancer (latency) + `detour` chain pass `check`.
- [x] xray socks + adjacent HTTP CONNECT inbounds; `proxySettings` chaining;
      balancer strategies pass `run -test` (all four strategies).
- [x] Locked verified shapes into `config_gen` tests + code comments.

### Fixes the spike surfaced

- sing-box >= 1.12 needs the typed DNS server format + `default_domain_resolver`.
- xray `leastPing`/`leastLoad` balancers require the `observatory` section.
- sing-box on Termux needs the `android` asset (linux builds are glibc/musl).
- `download_binary` resolves `latest` via the GitHub API; sing-box asset names
  drop the `v` prefix.
- sing-box >= 1.13 removed the WireGuard **outbound** — it's an **endpoint**
  now. The adapter emits `endpoints[]` (address/private_key/peers with
  `address`+`port`) and its tag is a first-class route target: `route.final`,
  selector/urltest groups, rules and `detour` (both directions) all reference
  it directly. Verified live: single/chain/balancer configs all pass `check`
  and the engine starts.

## Tests

- [x] `test_config_gen.py`: golden tests — single/balancer/chain per engine
      produce expected `outbounds`/`routing`/`inbounds`; tag stability; chain
      order; split-routing rule emission for both engines.
- [x] `test_binary.py`: asset-name mapping for both engines; locate
      (absolute/system/cached) and `get_version` (no network in CI).
- [x] `test_engine.py`: `resolve_engine` matrix + registry.

## Definition of Done

- [x] Both engines' `check`/`-test` pass on generated configs (verified live).
- [x] SOCKS+HTTP single port confirmed on sing-box 1.13.19 (live E2E); 2-hop
      chain egress confirmed live (dead-first-hop negative control).
- [x] `pytest` passes — 112 tests.
