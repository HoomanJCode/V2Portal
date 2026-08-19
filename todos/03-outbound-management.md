# Phase 03 — Outbound Management, VPNs, Groups & Routing

> **Status:** ✅ Implemented (commits d4148a8 → eb1c80b).

Goal: add/edit/remove outbounds beyond share links, add OpenVPN/AnyConnect VPN
profiles, build groups (chain / auto-select), and manage split-routing rules.

## Tasks

### Manual outbounds (`outbounds/manual.py`)

- [x] `add_manual_config(json_text, name, engine)` — accept a raw **xray
      outbound** object pasted by the user, normalize into `Profile(kind="manual")`,
      resolve it to xray, validate protocol, and reject inbounds.
- [x] `add_socks_proxy(name, host, port, user, pass)` → `kind=socks`;
      validate non-empty host and port range 1–65535.
- [x] `add_http_proxy(name, host, port, user, pass)` → `kind=http`;
      validate non-empty host and port range 1–65535.
- [x] `add_wireguard(name, private_key, address, peers)` → `kind=wireguard`; validate
      private key, local addresses, peer keys/endpoints, and allowed IPs.
- [x] `add_hysteria2(...)` / `add_tuic(...)` → `kind=hysteria2/tuic`
      (`engine=sing-box`), prompting the protocol-specific fields and validating
      endpoint host/port.
- [x] `edit_profile(id, **fields)`, `remove_profile(id)` (prune from
      subscription `profile_ids` and all group `profile_ids`).

### VPN profiles (`outbounds/vpn.py`)

- [x] `add_openvpn(name, ovpn_config_path|inline_text, args)` → `Profile(kind=openvpn)`
      with `vpn = {type:"openvpn", config_path|inline, args}`.
- [x] `add_openconnect(name, server, args, auth)` → `Profile(kind=openconnect)`
      with `vpn = {type:"openconnect", server, args, auth_hint}`; require a
      non-empty server before connection.
- [x] Detect `openvpn` / `openconnect` on `PATH` (`shutil.which`); annotate
      unavailable VPNs in the TUI and surface a clear install hint when
      connecting. (detection is `detect_clients()`, refreshed live.)
- [x] VPN profiles are never valid members of a balancer/chain group (guard).

### Groups (`outbounds/groups.py`)

- [x] `create_balancer_group(name, strategy, profile_ids, engine)` —
      strategy ∈ {latency, random, roundRobin, leastLoad}; ≥2 non-VPN profiles;
      validate engine supports the strategy (leastLoad → xray only) and every
      member kind.
- [x] `create_chain_group(name, ordered_profile_ids, engine)` — ≥2 non-VPN
      profiles, all resolvable by one engine; explicit engines reject unsupported
      member kinds before config generation.
- [x] `create_single_group(name, profile_id)`.
- [x] `remove_group`, `rename_group`, add/remove members.
- [x] `resolve_target(profile_or_group) -> Target` (type, profile ids, strategy,
      resolved engine) — single seam for config-gen / runner / tester.

### Split routing (`routing/rules.py`)

- [x] `add_rule(action, match, target_id=None)`, `remove_rule`, `reorder_rules`.
- [x] `validate_rule` — matcher syntax check (domain keyword/regex, CIDR,
      geoip/geosite codes); action ∈ {proxy, direct, block}.
- [x] `normalize_rules(routing, selected_target_id)` — resolve `target_id=null`
      to the selected target, and produce the ordered rule list for the engine.

## Tests

- [x] `test_manual.py`: each manual kind produces the expected outbound shape;
      empty credentials omitted.
- [x] `test_groups.py`: strategy/engine validation; VPN exclusion; removal
      pruning; `resolve_target` per type.
- [x] `test_routing.py`: rule validation, ordering, `target_id` resolution.
- [x] `test_vpn.py`: PATH detection and profile shape (no real client spawn).

## Definition of Done

- [x] Storage CRUD complete for profiles, VPNs, groups, and routing rules.
- [x] `resolve_target` + `normalize_rules` are the only seams config-gen needs.
- [x] `pytest` passes — 55 tests.
