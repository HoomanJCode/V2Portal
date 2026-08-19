# Phase 02 — Share Links & Subscriptions

Goal: turn a subscription URL into a list of `Profile` objects, and support
updating them. This is the most parser-heavy phase.

## Tasks

### Share-link decoding (`subs/share.py`)

- [ ] `decode_link(raw: str) -> Profile` dispatches on the URI scheme.
- [ ] `vmess://` — base64-decode (standard + url-safe, with/without padding) →
      JSON; map fields (`ps`→name, `add`→host, `port`, `id`, `aid`, `scy`,
      `net`, `type`, `host`, `path`, `tls`, `sni`, `alpn`, `fp`) into an xray
      `outbound` `{settings, streamSettings}` object.
- [ ] `vless://` — parse `uuid@host:port?query#name`; map `type`, `security`,
      `encryption`, `flow`, `sni`, `alpn`, `fp`, `pbk`, `sid`, `spx`, `headerType`,
      `path`, `host`, `serviceName`, `mode`.
- [ ] `trojan://` — parse `password@host:port?query#name`; map `security`,
      `sni`, `alpn`, `fp`, `type`, `path`, `host`, `serviceName`, `mode`, `allowInsecure`.
- [ ] `ss://` — support both legacy base64 form (`ss://base64(method:password)@host:port`)
      and SIP002 (`ss://method:password@host:port#name`), plus url-safe base64 and
      plugin (`v2ray-plugin` / `obfs`) query params.
- [ ] `ssr://` — base64-decode the payload after the scheme, then parse
      `host:port:protocol:method:obfs:base64password/?obfsparam=..&protoparam=..&remarks=..&group=..`.
- [ ] `socks://` and `http://` — parse `user:pass@host:port#name` into a plain
      proxy `Profile` (`kind=socks`/`http`).
- [ ] Any unsupported scheme → collect into a `parse_errors` list (don't crash
      the whole import).
- [ ] `encode_link(profile) -> str` (reverse) so imported profiles can be
      re-exported/shared (nice-to-have; used later by the TUI "export" action).

### Subscription fetching (`subs/fetcher.py`)

- [ ] `fetch(url, user_agent=None) -> (body_text, headers)` using `httpx` with a
      sane timeout, redirects, and graceful error mapping (timeout, DNS, HTTP
      status) into typed errors.
- [ ] Support `file://` URLs and a `paste://<payload>` pseudo-scheme for
      offline/manual entry.
- [ ] Parse `Subscription-Userinfo` header → `expires` + `traffic_used`.

### Subscription parsing (`subs/parser.py`)

- [ ] `parse_payload(body_text) -> list[str]` handling:
  - plain newline-separated share links
  - base64-encoded blob (standard + url-safe, with/without padding) that
    decodes to newline-separated links
  - mixed: tolerate stray whitespace, BOM, and blank lines
- [ ] `import_subscription(name, url) -> (subscription, profiles, errors)`:
  - fetch → parse → decode each link → create `Profile` objects with
    `source="subscription"` and `subscription_id` set
  - dedupe by a stable key (host+port+protocol+uuid), skip dupes
  - set `last_updated`; report per-link failures without losing the rest
- [ ] `update_subscription(id)`:
  - re-fetch and re-parse; **preserve** the subscription's existing profiles'
    names when the share-link `ps` is unchanged; add new nodes, drop missing ones
    (or mark them `enabled=false` — pick drop-by-default, log a diff)
  - update `last_updated`, `expires`, `traffic_used`

## Tests

- [ ] `test_share.py`: a fixture link per protocol (vmess/vless/trojan/ss/ssr/
      socks/http) asserts the resulting `outbound` object's key fields.
- [ ] `test_parser.py`: plain vs base64 (padded/url-safe/unpadded) payloads;
      malformed payload doesn't raise; dedupe behavior.
- [ ] `test_fetcher.py`: `file://` fetch and `paste://` (no network in CI);
      `httpx` mocked for HTTP paths.

## Definition of Done

- [ ] A realistic sample subscription (committed under `tests/fixtures/`) imports
      into N correct profiles with 0 unexpected errors.
- [ ] `update_subscription` round-trips without duplicating or orphaning profiles.
- [ ] `pytest` passes with no network dependency.
