# Phase 03 — Outbound Management & Groups

Goal: add/edit/remove outbounds beyond share links (manual v2ray config, plain
SOCKS/HTTP proxy), and build **groups** that chain proxies or auto-select among
them (round robin, random, latency, least-load).

## Tasks

### Manual outbounds (`outbounds/manual.py`)

- [ ] `add_v2ray_config(json_text, name)` — accept a raw xray **outbound** object
      (`{settings, streamSettings, protocol}`) pasted by the user, normalize it
      into a `Profile(kind="manual")`, validate `protocol` ∈
      {vmess,vless,trojan,shadowsocks,socks,http,wireguard}, and reject inbounds.
- [ ] `add_socks_proxy(name, host, port, username, password)` →
      `Profile(kind="socks")` with `outbound.settings.servers = [{address, port,
      users:[{user, pass}]}]` (omit user object when empty).
- [ ] `add_http_proxy(name, host, port, username, password)` →
      `Profile(kind="http")` with `outbound.settings.servers = [{address, port,
      users:[{user, pass}]}]`.
- [ ] `edit_profile(id, **fields)` and `remove_profile(id)` (removal also prunes
      the profile from any subscription's `profile_ids` and any group's
      `profile_ids`).

### Groups (`outbounds/groups.py`)

- [ ] `create_balancer_group(name, strategy, profile_ids)` validating
      `strategy` ∈ {random, roundRobin, leastPing, leastLoad}.
- [ ] `create_chain_group(name, ordered_profile_ids)` with `len >= 2`; validate
      all ids exist.
- [ ] `create_single_group(name, profile_id)` (saved favorite).
- [ ] `remove_group`, `rename_group`, `group_add/remove_profile` helpers.
- [ ] A `resolve_target(profile_or_group) -> Target` concept: given what the
      user selected, return a normalized `Target` (type + profile ids + strategy)
      that the config generator (Phase 04) consumes without re-implementing
      group logic.
- [ ] Guardrails: a group may not reference itself; a chain group cannot contain
      the same profile twice in a row; a balancer must have ≥2 profiles.

## Tests

- [ ] `test_manual.py`: socks/http/manual creation produces the exact xray
      `outbound` shape; empty credentials omitted.
- [ ] `test_groups.py`: validation errors on bad strategy/empty set/self-ref;
      removal pruning works; `resolve_target` returns expected target for each
      group type.

## Definition of Done

- [ ] Storage CRUD for profiles and groups is complete and tested.
- [ ] `resolve_target` is the single seam used by both config-gen and the TUI.
- [ ] `pytest` passes.
