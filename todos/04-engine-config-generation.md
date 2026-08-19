# Phase 04 — Engine Adapters, Binaries & Config Generation

Goal: a working **engine adapter layer** (sing-box + xray), auto-download of
both binaries, and valid config generation for any target with split routing.
This is where mixed-inbound, chain (`detour` / `proxySettings`), and balancer
strategy details must be verified and locked in.

## Tasks

### Engine adapter (`engines/base.py`)

- [ ] `EngineAdapter` ABC: `name`, `supported_kinds: set`, `supported_strategies:
      set`, `generate(settings, routing, target) -> dict`, `run_args`,
      `validate_args`, `binary_filename(platform, arch)`.
- [ ] `resolve_engine(kind, strategy, explicit_engine) -> EngineName`:
      - explicit `xray`/`sing-box` wins
      - `ssr` → xray; `hysteria2`/`tuic` → sing-box; else `default_engine`
      - `leastLoad` → xray (sing-box fallback to roundRobin with a warning)
- [ ] `get_adapter(name) -> EngineAdapter` registry.

### Binary management (`engines/binary.py`)

- [ ] `locate_binary(engine, options) -> path`: absolute/system/`auto` (cache hit
      in `BIN_DIR`, else download).
- [ ] `download_binary(engine, version, platform, arch) -> path`: map OS/arch →
      release asset for `SagerNet/sing-box` and `XTLS/Xray-core`; verify SHA256
      when available; extract zip/tar.gz; chmod +x on POSIX.
- [ ] `get_version(engine, path)` (sing-box: `version`; xray: `version`).
- [ ] Cache hit when version matches.

### sing-box generator (`engines/singbox.py`)

- [ ] `generate(...)`: `log`, `dns` (from settings), one `mixed` inbound
      (socks5+http single port, `listen`, optional `users` when auth enabled),
      outbounds per profile + `direct`/`block` fallbacks.
- [ ] Single target → route to outbound; `selector`/`urltest` for balancer
      (strategy per `PLAN.md §3`); `detour` for chains (route to last hop).
- [ ] Split routing → emit native rules from `normalize_rules` (domain/keyword/
      regex, ip_cidr, geoip/geosite); fallback = selected target.

### xray generator (`engines/xray.py`)

- [ ] `generate(...)`: `log`, `inbounds` (`socks` with optional auth; verify
      HTTP CONNECT on same port, else emit socks + http on `mixed_port` /
      `mixed_port+1`), `outbounds`, `routing` (rules + `balancers`), `dns`.
- [ ] Balancer → `routing.balancers` entry with `strategy.type` per `PLAN.md §3`;
      chain → outbound base `proxySettings.tag` (route to last hop).

### Runtime config + validation

- [ ] `write_runtime_config(engine, config_dict) -> path` into `RUNTIME_DIR`.
- [ ] `validate_config(engine, path)` — sing-box `check` / xray `run -test`;
      surface stderr.

## Verification spike (do first inside the phase)

- [ ] sing-box `mixed` inbound: confirm socks5+http on one port (both clients).
- [ ] sing-box selector `strategy` values (`random`, `round_robin`) + `urltest`.
- [ ] xray socks inbound HTTP CONNECT; balancer strategy strings; `proxySettings`
      chaining; sing-box `detour` chaining (confirm egress via last hop).
- [ ] Lock verified shapes into `config_gen` tests + code comments.

## Tests

- [ ] `test_config_gen.py`: golden tests — single/balancer/chain per engine
      produce expected `outbounds`/`routing`/`inbounds`; tag stability; chain
      order; split-routing rule emission for both engines.
- [ ] `test_binary.py`: asset-name/URL mapping tables for both engines × OS/arch
      (no network in CI).
- [ ] `test_engine.py`: `resolve_engine` matrix (kind/strategy/explicit).

## Definition of Done

- [ ] Both engines' `check`/`-test` pass on generated configs for each target
      type and for a split-routing config.
- [ ] SOCKS+HTTP single port and 2-hop chain confirmed on the pinned builds
      (documented + test fixtures).
- [ ] `pytest` passes.
