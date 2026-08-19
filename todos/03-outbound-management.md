# Phase 03 — Outbound Management, VPNs, Groups & Routing

Goal: add/edit/remove outbounds beyond share links, add OpenVPN/AnyConnect VPN
profiles, build groups (chain / auto-select), and manage split-routing rules.

## Tasks

### Manual outbounds (`outbounds/manual.py`)

- [ ] `add_manual_config(json_text, name, engine)` — accept a raw **outbound**
      object pasted by the user, normalize into `Profile(kind="manual")`,
      validate protocol against the chosen engine, reject inbounds.
- [ ] `add_socks_proxy(name, host, port, user, pass)` → `kind=socks`.
- [ ] `add_http_proxy(name, host, port, user, pass)` → `kind=http`.
- [ ] `add_wireguard(name, private_key, address, peers)` → `kind=wireguard`.
- [ ] `add_hysteria2(...)` / `add_tuic(...)` → `kind=hysteria2/tuic`
      (`engine=sing-box`), prompting the protocol-specific fields.
- [ ] `edit_profile(id, **fields)`, `remove_profile(id)` (prune from
      subscription `profile_ids` and all group `profile_ids`).

### VPN profiles (`outbounds/vpn.py`)

- [ ] `add_openvpn(name, ovpn_config_path|inline_text, args)` → `Profile(kind=openvpn)`
      with `vpn = {type:"openvpn", config_path, args}`.
- [ ] `add_openconnect(name, server, args, auth)` → `Profile(kind=openconnect)`
      with `vpn = {type:"openconnect", server, args, auth_hint}`.
- [ ] Detect `openvpn` / `openconnect` on `PATH` (`shutil.which`); store a
      `vpn.available` flag and surface a clear install hint when missing.
- [ ] VPN profiles are never valid members of a balancer/chain group (guard).

### Groups (`outbounds/groups.py`)

- [ ] `create_balancer_group(name, strategy, profile_ids, engine)` —
      strategy ∈ {latency, random, roundRobin, leastLoad}; ≥2 non-VPN profiles;
      validate engine supports the strategy (leastLoad → xray only).
- [ ] `create_chain_group(name, ordered_profile_ids, engine)` — ≥2 non-VPN
      profiles, all resolvable by one engine.
- [ ] `create_single_group(name, profile_id)`.
- [ ] `remove_group`, `rename_group`, add/remove members.
- [ ] `resolve_target(profile_or_group) -> Target` (type, profile ids, strategy,
      resolved engine) — single seam for config-gen / runner / tester.

### Split routing (`routing/rules.py`)

- [ ] `add_rule(action, match, target_id=None)`, `remove_rule`, `reorder_rules`.
- [ ] `validate_rule` — matcher syntax check (domain keyword/regex, CIDR,
      geoip/geosite codes); action ∈ {proxy, direct, block}.
- [ ] `normalize_rules(routing, selected_target_id)` — resolve `target_id=null`
      to the selected target, and produce the ordered rule list for the engine.

## Tests

- [ ] `test_manual.py`: each manual kind produces the expected outbound shape;
      empty credentials omitted.
- [ ] `test_groups.py`: strategy/engine validation; VPN exclusion; removal
      pruning; `resolve_target` per type.
- [ ] `test_routing.py`: rule validation, ordering, `target_id` resolution.
- [ ] `test_vpn.py`: PATH detection and profile shape (no real client spawn).

## Definition of Done

- [ ] Storage CRUD complete for profiles, VPNs, groups, and routing rules.
- [ ] `resolve_target` + `normalize_rules` are the only seams config-gen needs.
- [ ] `pytest` passes.
