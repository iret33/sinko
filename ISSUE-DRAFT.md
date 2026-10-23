# Issue draft: an unclaimed box cannot be claimed through `http://family.lan/` on Pi-hole FTL 6.8 and later

*A draft for a GitHub issue, not a document of the project. Delete this file once the issue is opened.*

## What happens

A box that has no password yet (a ready-made box nobody has claimed) shows the welcome screen, where a parent chooses the
password. Opened as `http://family.lan/` (the local name `SINKO_HOSTNAME` that Sinko adds to Pi-hole's local records), it
shows the **sign-in** screen instead, and there is no password to sign in with. `http://sinko.local/` and
`http://<address>/` work.

## Why

Pi-hole FTL commit `c1b37a41` ("Refuse other websites' browser requests when no password is set", 2026-10-11, fixes
GHSA-322h-f873-hp54), first released in **FTL v6.8** (tagged 2026-10-17), added `known_host()` to `src/api/auth.c`. While
`webserver.api.pwhash` is empty, `check_client_auth()` refuses a request whose `Host` is not one of:

* an IPv4 or IPv6 address, `localhost`, `pi.hole`,
* `webserver.domain`,
* the machine's host name, alone, or followed by `.<dns.domain.name>` or `.local`.

`family.lan` is none of these (the host name is `sinko`, `dns.domain.name` is `lan` by default, so `sinko.lan` would pass).
`GET /api/auth` then answers 401 with
`{"session":{"valid":false,"totp":false,"sid":null,"validity":-1,"message":"no password set, but request from another website"}}`.
The page's `noPasswordSet()` reads that as "a password is set" and shows the sign-in. The installer and the `sinko` program
are not affected: they talk to `127.0.0.1`.

## Why Sinko does not set `webserver.domain` to `SINKO_HOSTNAME`

It was considered for `apply_pihole_settings` and rejected. Checked in FTL's source at v6.8:

1. **The page would stop opening at that name.** `redirect_root_handler()` (`src/webserver/webserver.c`, registered whenever
   `webserver.paths.webhome` is not `/`, and it is `/admin/` by default) answers `GET /` with a **308 Permanent Redirect** to
   `/admin/` when `Host` equals `webserver.domain`. `http://family.lan/` would open Pi-hole's admin page instead of Sinko's,
   for every parent, also after the box is claimed, and browsers keep a 308.
2. **It names the HTTPS certificate.** When the certificate file is missing (the first start of a ready-made box, after the
   seal removed the golden unit's), FTL makes it for `webserver.domain` (`generate_certificate(..., config.webserver.domain.v.s, ...)`).
   On a box whose certificate already exists for `pi.hole`, every start of FTL logs a `CERTIFICATE_DOMAIN_MISMATCH` warning,
   which Pi-hole's admin page shows as a diagnosis message.
3. It is also the account name in the two-factor setup (`src/api/2fa.c`).

## Options

1. **The page explains it (recommended, small).** When `GET /api/auth` answers 401 with the message
   `no password set, but request from another website`, the page knows the box has no password and was opened by a name
   Pi-hole refuses. It can say so in plain words and offer the address and the `.local` name from `/pb/box.json` (static, read
   without signing in, and since 3.2 it carries `hostname` and `ip`): "Open http://sinko.local/ to choose your password."
   English and Arabic, no technical words.
2. **Quick-start card and docs** already send parents to `http://sinko.local/` first; say that `family.lan` works only
   after the password is chosen.
3. **Ask Pi-hole** for a way to accept more names without a password (a list setting, or the names in `dns.hosts` that point
   at the box itself), or for the redirect of `/` not to apply when `webserver.serve_all` is on.
4. Not recommended: setting `dns.domain.name` so that `<host name>.<domain>` is `SINKO_HOSTNAME`. It changes Pi-hole's own
   local domain and works only when the first label of `SINKO_HOSTNAME` is the host name.

## Also worth knowing

FTL reads the host name once (`hostname()` in `src/daemon.c` caches `uname -n`). A box renamed while FTL runs keeps refusing
`<new name>.local` until FTL restarts. `firstboot.sh` gives the box the same name the seal already set, so a ready-made box
is not affected.

## How to check on hardware

`docs/hardware-test-checklist.md`, section E, "Which names open the welcome screen".
