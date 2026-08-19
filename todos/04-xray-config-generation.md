# Phase 04 — xray-core Binary & Config Generation

Goal: get a working xray-core binary (auto-download or system) and generate a
valid xray JSON config from any selected target. This is where the "mixed
inbound" and "chain via proxySettings" details must be verified and locked in.

## Tasks

### Binary management (`xray/binary.py`)

- [ ] `locate_binary(xray_options, platform, arch) -> path`:
  - if `binary_path` is an absolute path or `"system"`, use that / `shutil.which`
  - if `"auto"`, check `BIN_DIR` for a previously downloaded binary, else download
- [ ] `download_xray(version, platform, arch) -> path`:
  - map (OS, arch) → release asset name for `XTLS/Xray-core` GitHub releases
    (linux/amd64, linux/arm64, windows/amd64, windows/arm64, android/arm64 = linux/arm64)
  - download with `httpx`, verify SHA256 when available, extract zip/tar.gz
  - mark executable on POSIX; print a one-time notice + license reference
- [ ] `get_version(path)` — run `xray version` and parse.
- [ ] Treat "already downloaded & version matches" as a cache hit.

### Config generation (`xray/config_gen.py`)

- [ ] `generate(settings, target) -> dict` building the full xray config from
      `PLAN.md §5`:
  - `log.loglevel` from settings
  - one inbound: `protocol "socks"`, `listen = settings.listen`,
    `port = settings.mixed_port`, `settings.auth = "noauth"`, `udp = true`
    (**verify** single-port SOCKS+HTTP behavior of the pinned build; if not
    supported, emit two inbounds — socks + http — on `mixed_port` and
    `mixed_port+1` and record the split in the return value)
  - outbounds: one per profile referenced by the target (plus a `direct`
    freedom outbound and, for the selected target, the needed chain hops)
  - tags = profile `id` strings
  - routing: single → direct to tag; balancer → `routing.balancers` entry +
    route to balancer tag; chain → nested `proxySettings` (verify field
    placement; first hop no `proxySettings`, route to last hop)
- [ ] `write_runtime_config(config_dict) -> path` into `RUNTIME_DIR/config.json`.
- [ ] `validate_config(path)` — run `xray run -test -config <path>` and surface
      stderr on failure.
- [ ] Optional `dns` object from settings so the client can resolve while
      proxying (make it a setting, default enabled).

## Verification spike (do this first inside the phase)

- [ ] Run the pinned xray with a socks inbound and confirm an HTTP client set to
      the same port as its HTTP proxy works (SOCKS+HTTP single port).
- [ ] Run a 2-hop chain and confirm traffic egresses through the final hop
      (check the remote IP changes accordingly). Lock the exact `proxySettings`
      shape into `config_gen.py` + a test.

## Tests

- [ ] `test_config_gen.py`: golden tests that a single/balancer/chain target
      produce the expected `outbounds`/`routing` shape; tag stability; chain
      `proxySettings` nesting order.
- [ ] `test_binary.py`: asset-name mapping table for the 5 OS/arch combos
      (no network in CI).

## Definition of Done

- [ ] `xray run -test` passes on a generated config for each target type.
- [ ] SOCKS+HTTP single-port and 2-hop chain confirmed on the pinned build
      (documented in a code comment + test fixture).
- [ ] `pytest` passes.
