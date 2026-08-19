# Phase 02 — Share Links & Subscriptions

Goal: turn a subscription URL into a list of `Profile` objects across **all**
protocols, and support updating them. Parser-heavy phase.

## Tasks

### Share-link decoding (`subs/share.py`)

- [ ] `decode_link(raw) -> Profile` dispatches on scheme.
- [ ] `vmess://` — base64 (std + url-safe, padded/unpadded) → JSON; map `ps`,
      `add`, `port`, `id`, `aid`, `scy`, `net`, `type`, `host`, `path`, `tls`,
      `sni`, `alpn`, `fp` into an outbound object.
- [ ] `vless://` — `uuid@host:port?query#name`; map `type`, `security`,
      `encryption`, `flow`, `sni`, `alpn`, `fp`, `pbk`, `sid`, `spx`,
      `headerType`, `path`, `host`, `serviceName`, `mode`.
- [ ] `trojan://` — `password@host:port?query#name`; map `security`, `sni`,
      `alpn`, `fp`, `type`, `path`, `host`, `serviceName`, `mode`, `allowInsecure`.
- [ ] `ss://` — legacy base64 (`ss://base64(method:password)@host:port`) and
      SIP002 (`ss://method:password@host:port#name`), url-safe base64, plugin
      query params (`v2ray-plugin`, `obfs`).
- [ ] `ssr://` — base64-decode payload after scheme → parse
      `host:port:protocol:method:obfs:base64password/?obfsparam&protoparam&remarks&group`.
- [ ] `socks://` / `http://` — `user:pass@host:port#name` → plain proxy Profile.
- [ ] `hysteria2://` — parse `auth@host:port?query#name`; map `insecure`, `sni`,
      `obfs`, `obfs-password`, `pinSHA256`, `salamander`/`up`/`down` bandwidth.
      (`kind=hysteria2`, `engine=sing-box`.)
- [ ] `tuic://` — parse `uuid:password@host:port?query#name`; map `congestion_control`,
      `alpn`, `sni`, `allow_insecure`, `udp_relay_mode`.
      (`kind=tuic`, `engine=sing-box`.)
- [ ] `wireguard://` — parse base64 JSON (private_key, address, peers…) or
      decode a plain `wg://` form. (`kind=wireguard`.)
- [ ] Unsupported scheme → collect in `parse_errors`; never crash the import.
- [ ] `encode_link(profile) -> str` reverse (for "export" action later).

### Subscription fetching (`subs/fetcher.py`)

- [ ] `fetch(url, user_agent) -> (body, headers)` via `httpx`; timeout, redirect,
      typed errors (timeout/DNS/HTTP status).
- [ ] Support `file://` and `paste://<payload>`.
- [ ] Parse `Subscription-Userinfo` → `expires` + `traffic_used`.

### Subscription parsing (`subs/parser.py`)

- [ ] `parse_payload(body) -> list[str]`: plain newline list, base64 blob
      (std/url-safe, padded/unpadded), tolerate BOM/whitespace/blank lines.
- [ ] `import_subscription(name, url) -> (subscription, profiles, errors)`:
      fetch → parse → decode → create Profiles (`source="subscription"`,
      `subscription_id` set); dedupe by (protocol, host, port, credential);
      report per-link failures.
- [ ] `update_subscription(id)`: re-fetch, re-parse; preserve unchanged names;
      **delete** profiles that disappeared upstream (clean `profile_ids` and
      prune them from any group's `profile_ids`); update `last_updated`,
      `expires`, `traffic_used`.

## Tests

- [ ] `test_share.py`: fixture link per protocol (vmess/vless/trojan/ss/ssr/
      socks/http/hysteria2/tuic/wireguard) asserts outbound fields + resolved engine.
- [ ] `test_parser.py`: plain vs base64 payloads; malformed input doesn't raise;
      dedupe; delete-on-update behavior.
- [ ] `test_fetcher.py`: `file://` + `paste://` (no network); httpx mocked.

## Definition of Done

- [ ] A sample subscription fixture (under `tests/fixtures/`) imports N correct
      profiles across protocols with 0 unexpected errors.
- [ ] `update_subscription` deletes vanished nodes and prunes group references.
- [ ] `pytest` passes with no network dependency.
