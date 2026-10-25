#!/usr/bin/env bash
# tools/factory-qa.sh and tools/prepare-golden-master.sh on a fake root. A box as it comes out of the golden unit's image at its
# first start: Sinko installed by the real installer, the first start done, and a made-up Orange Pi Zero 3 around it (its lights,
# temperature sensors, network port and /proc files, all under the fake root). Pi-hole is the mock API; a small DNS server
# answers the way Pi-hole does (it stops TikTok for a device exactly while Sinko's TikTok group is on and the device is in it);
# a web server serves the page. Nothing here touches the real system or its lights: every path is under the fake root, and every
# command that would act (systemctl, systemd-run, passwd, ...) is a stub.
# shellcheck disable=SC2016  # a $ in single quotes is literal on purpose here: a password hash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tests/lib_stubs.sh disable=SC1091
. "$HERE/lib_stubs.sh"
PORT="${PORT:-18085}"
WEBPORT="${WEBPORT:-18086}"
DNSPORT="${DNSPORT:-18087}"
fake_system_init
QA="$ROOT/opt/sinko/tools/factory-qa.sh"
PREPARE="$ROOT/opt/sinko/tools/prepare-golden-master.sh"
FLAG="$ROOT/var/lib/sinko/factory-qa"
REPORT="$ROOT/root/FAILED_QA_REPORT.txt"
cat >"$WORK/os-release" <<'EOF'
PRETTY_NAME="Armbian 25.8 trixie"
ID=debian
EOF
export SINKO_OS_RELEASE="$WORK/os-release"
export SINKO_QA_FAST=1 SINKO_QA_WAIT=2 SINKO_QA_SETTLE=2 SINKO_QA_SELFCHECK_WAIT=0 SINKO_QA_RESTART_PAUSE=0 SINKO_QA_SOS_ROUNDS=1
export SINKO_QA_RUN_DIR="$WORK/qa-run" SINKO_QA_WEB_URL="http://127.0.0.1:$WEBPORT" SINKO_QA_DNS="127.0.0.1:$DNSPORT"
export SINKO_QA_LED_LOG="$WORK/leds.log" SINKO_SQL_BACKEND=python SINKO_GRAVITY_DB="$ROOT/etc/pihole/gravity.db"

# ------------------------------------------------------------------ stubs this test needs on top of lib_stubs.sh
# uname -m: the board's architecture ($WORK/arch to pretend another one).
cat >"$STUBS/uname" <<EOF
#!/usr/bin/env bash
if [[ "\$1" == -m ]]; then cat "\$WORK/arch" 2>/dev/null || echo aarch64; exit 0; fi
exec "$(command -v uname)" "\$@"
EOF
# timedatectl: the lib stub, plus whether the clock was set from a time server ($WORK/ntp-unsynced: not yet).
mv "$STUBS/timedatectl" "$STUBS/timedatectl.lib"
cat >"$STUBS/timedatectl" <<'EOF'
#!/usr/bin/env bash
if [[ " $* " == *" NTPSynchronized "* ]]; then if [[ -e "$WORK/ntp-unsynced" ]]; then echo no; else echo yes; fi; exit 0; fi
exec "$WORK/stubs/timedatectl.lib" "$@"
EOF
# systemctl: the lib stub, plus Armbian's light service, which writes the lights' state into its file when it is stopped.
mv "$STUBS/systemctl" "$STUBS/systemctl.lib"
cat >"$STUBS/systemctl" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == stop && " $* " == *" armbian-led-state.service "* ]]; then echo "saved at shutdown: every light on" >"$ROOT/etc/armbian-leds.conf"; fi
# A reload after the test's own unit file is gone: the test runs as that unit, and systemd then forgets its TimeoutStartSec=infinity
# (the default of 90 s kills it before the power-off, as it did on the real board). Noted here, checked by the good-box scenario.
if [[ "$1" == daemon-reload && ! -e "$ROOT/etc/systemd/system/sinko-factory-qa.service" ]]; then : >"$WORK/reload-without-unit"; fi
exec "$WORK/stubs/systemctl.lib" "$@"
EOF
# systemd-run: only says what it was asked to start ($WORK/systemd-run-fails: it cannot).
cat >"$STUBS/systemd-run" <<'EOF'
#!/usr/bin/env bash
echo "systemd-run $*" >>"$WORK/calls.log"
[[ ! -e "$WORK/systemd-run-fails" ]]
EOF
# ip: the lib stub, for a port of another name than eth0 ($WORK/iface, such as end0).
mv "$STUBS/ip" "$STUBS/ip.lib"
cat >"$STUBS/ip" <<'EOF'
#!/usr/bin/env bash
dev="$(cat "$WORK/iface" 2>/dev/null || echo eth0)"
"$WORK/stubs/ip.lib" "${@//$dev/eth0}" | sed "s/eth0/$dev/g"
EOF
# findmnt -n -o MAJ:MIN /: the root filesystem is on the first partition of the card (mmcblk0p1, 179:1).
cat >"$STUBS/findmnt" <<'EOF'
#!/usr/bin/env bash
[[ " $* " == *" MAJ:MIN "* ]] && echo "179:1"
EOF
# tailscale: written by a scenario that wants it ($WORK/tailscale-state is what `tailscale status --json` reports).
make_tailscale() {  # BackendState
  echo "$1" >"$WORK/tailscale-state"
  cat >"$STUBS/tailscale" <<'EOF'
#!/usr/bin/env bash
[[ "$1 $2" == "status --json" ]] || exit 0
[[ -s "$WORK/tailscale-state" ]] || { echo "failed to connect to local tailscaled" >&2; exit 1; }
printf '{"BackendState": "%s", "Self": {}}\n' "$(cat "$WORK/tailscale-state")"
EOF
  chmod +x "$STUBS/tailscale"
}
chmod +x "$STUBS"/*

# ------------------------------------------------------------------ Pi-hole's DNS, as far as this test needs it
cat >"$WORK/dns.py" <<'EOF'
"""Answers A questions the way Pi-hole would: pi.hole and the local names in dns.hosts locally, TikTok's names stopped (0.0.0.0)
for a device while that device is in Sinko's TikTok group and the group is on (read from the mock API at every question), other
names "from upstream". Switches: $WORK/dns-down (no answer), dns-never-blocks, upstream-down (SERVFAIL for names from upstream)."""
import json, os, re, socket, struct, sys, urllib.request
port, api, work, lists = int(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
tiktok = {l.strip()[2:-1] for l in open(os.path.join(lists, "tiktok.txt")) if l.strip().startswith("||") and l.strip().endswith("^")}

def get(path):
    req = urllib.request.Request(api + path)
    try:
        return json.load(urllib.request.urlopen(req, timeout=5))
    except urllib.error.HTTPError:
        sid = json.load(urllib.request.urlopen(urllib.request.Request(api + "/api/auth", data=json.dumps(
            {"password": open(os.path.join(work, "cli_pw")).read().strip()}).encode(), method="POST",
            headers={"Content-Type": "application/json"}), timeout=5))["session"]["sid"]
        return json.load(urllib.request.urlopen(urllib.request.Request(api + path, headers={"sid": sid}), timeout=5))

def tiktok_stopped_for(client):
    if os.path.exists(os.path.join(work, "dns-never-blocks")):
        return False
    group = [g for g in get("/api/groups")["groups"] if g["name"] == "pb-svc-tiktok"]
    if not group or not group[0]["enabled"]:
        return False
    return any(c["client"] == client and group[0]["id"] in c["groups"] for c in get("/api/clients")["clients"])

def local_names():
    try:
        hosts = json.load(open(os.path.join(work, "ftl.json"))).get("dns.hosts", "")
    except (OSError, ValueError):
        return {}
    return {name: ip for ip, name in re.findall(r"(\d+\.\d+\.\d+\.\d+)\s+([^\s,\]]+)", hosts)}

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("127.0.0.1", port))
while True:
    data, (client, cport) = sock.recvfrom(4096)
    if os.path.exists(os.path.join(work, "dns-down")):
        continue
    pos, labels = 12, []
    while data[pos]:
        labels.append(data[pos + 1:pos + 1 + data[pos]].decode())
        pos += 1 + data[pos]
    question = data[12:pos + 5]
    name = ".".join(labels).lower()
    rcode, ips = 0, []
    names = local_names()
    if name == "pi.hole":
        ips = ["127.0.0.1"]
    elif name in names:
        ips = [names[name]]
    elif name in tiktok or any(name.endswith("." + d) for d in tiktok):
        if tiktok_stopped_for(client):
            ips = ["0.0.0.0"]
        elif os.path.exists(os.path.join(work, "upstream-down")):
            rcode = 2
        else:
            ips = ["93.184.215.14"]
    elif name == "github.com":
        if os.path.exists(os.path.join(work, "upstream-down")):
            rcode = 2
        else:
            ips = ["140.82.121.4"]
    else:
        rcode = 3
    answer = b"".join(b"\xc0\x0c" + struct.pack(">HHIH", 1, 1, 2, 4) + socket.inet_aton(ip) for ip in ips)
    head = struct.pack(">HHHHHH", struct.unpack(">H", data[:2])[0], 0x8180 | rcode, 1, len(ips), 0, 0)
    sock.sendto(head + question + answer, (client, cport))
EOF
python3 "$WORK/dns.py" "$DNSPORT" "http://127.0.0.1:$PORT" "$WORK" "$REPO/lists" >"$WORK/dns.log" 2>&1 &
DNS_PID=$!
qa_cleanup() {
  kill "$DNS_PID" 2>/dev/null || true
  fake_system_cleanup
}
trap qa_cleanup EXIT

# ------------------------------------------------------------------ the box
# The board, as a real Orange Pi Zero 3 with Armbian Trixie shows it: two lights from the device tree (green:power on, red:status
# beating), four temperature sensors, the network port end0 (and Wi-Fi, which is not it), and what /proc says about the SoC, its
# cores, the memory and the card. A keyboard's light, which the real board does not have, must be left alone.
make_board() {
  local led
  mkdir -p "$ROOT/sys/bus/platform/drivers/leds-gpio" "$ROOT/sys/devices/platform/leds"
  ln -sfn ../../../bus/platform/drivers/leds-gpio "$ROOT/sys/devices/platform/leds/driver"
  for led in green:power red:status; do
    mkdir -p "$ROOT/sys/class/leds/$led"
    ln -sfn ../../../devices/platform/leds "$ROOT/sys/class/leds/$led/device"
    echo 1 >"$ROOT/sys/class/leds/$led/max_brightness"
  done
  echo "[none] kbd-capslock timer heartbeat default-on mmc0" >"$ROOT/sys/class/leds/green:power/trigger"
  echo 1 >"$ROOT/sys/class/leds/green:power/brightness"
  echo "none kbd-capslock timer [heartbeat] default-on mmc0" >"$ROOT/sys/class/leds/red:status/trigger"
  echo 0 >"$ROOT/sys/class/leds/red:status/brightness"
  mkdir -p "$ROOT/sys/class/leds/input0::capslock"
  echo "[kbd-capslock] none" >"$ROOT/sys/class/leds/input0::capslock/trigger"
  echo 0 >"$ROOT/sys/class/leds/input0::capslock/brightness"; echo 1 >"$ROOT/sys/class/leds/input0::capslock/max_brightness"
  local zone=0 kind
  for kind in gpu-thermal:51821 ve-thermal:50768 cpu-thermal:51254 ddr-thermal:51983; do
    mkdir -p "$ROOT/sys/class/thermal/thermal_zone$zone"
    echo "${kind%%:*}" >"$ROOT/sys/class/thermal/thermal_zone$zone/type"; echo "${kind#*:}" >"$ROOT/sys/class/thermal/thermal_zone$zone/temp"
    zone=$(( zone + 1 ))
  done
  mkdir -p "$ROOT/sys/class/net/end0/device" "$ROOT/sys/class/net/wlan0/device" "$ROOT/sys/class/net/wlan0/wireless" "$ROOT/sys/class/net/lo"
  echo 1 >"$ROOT/sys/class/net/end0/carrier"; echo 1000 >"$ROOT/sys/class/net/end0/speed"; echo 1 >"$ROOT/sys/class/net/end0/type"
  echo 0 >"$ROOT/sys/class/net/wlan0/carrier"; echo 1 >"$ROOT/sys/class/net/wlan0/type"; echo 772 >"$ROOT/sys/class/net/lo/type"
  mkdir -p "$ROOT/proc/device-tree"
  printf 'xunlong,orangepi-zero3\0allwinner,sun50i-h618\0' >"$ROOT/proc/device-tree/compatible"
  printf 'OrangePi Zero3\0' >"$ROOT/proc/device-tree/model"
  : >"$ROOT/proc/cpuinfo"
  local i
  for i in 0 1 2 3; do printf 'processor\t: %s\nCPU implementer\t: 0x41\nCPU part\t: 0xd03\n\n' "$i" >>"$ROOT/proc/cpuinfo"; done
  printf 'MemTotal:         993240 kB\nMemFree:          600000 kB\n' >"$ROOT/proc/meminfo"
  printf 'rootfs / rootfs rw 0 0\n/dev/mmcblk0p1 / ext4 rw,noatime,errors=remount-ro,commit=600 0 0\ntmpfs /run tmpfs rw 0 0\n' >"$ROOT/proc/mounts"
  echo 4000000 >"$WORK/df-free-kb"
  # The card (for the copy commands): a 32 GB one, 31914983424 bytes, its first partition holds the system.
  local card="$ROOT/sys/devices/platform/soc/4020000.mmc/mmc_host/mmc0/mmc0:aaaa/block/mmcblk0"
  mkdir -p "$card/mmcblk0p1" "$ROOT/sys/dev/block"
  echo 62333952 >"$card/size"; echo 1 >"$card/mmcblk0p1/partition"; echo 8192 >"$card/mmcblk0p1/start"
  ln -sfn ../../devices/platform/soc/4020000.mmc/mmc_host/mmc0/mmc0:aaaa/block/mmcblk0/mmcblk0p1 "$ROOT/sys/dev/block/179:1"
}

# Pi-hole's database, as far as the checks read it: Sinko's groups, its TikTok list and that list's entries.
make_gravity_db() {
  python3 - "$ROOT/etc/pihole/gravity.db" "$REPO/lists/tiktok.txt" <<'EOF'
import sqlite3, sys
db = sqlite3.connect(sys.argv[1])
db.executescript("""
CREATE TABLE "group" (id INTEGER PRIMARY KEY AUTOINCREMENT, enabled BOOLEAN NOT NULL DEFAULT 1, name TEXT UNIQUE NOT NULL, description TEXT);
CREATE TABLE adlist (id INTEGER PRIMARY KEY AUTOINCREMENT, address TEXT UNIQUE NOT NULL, enabled BOOLEAN NOT NULL DEFAULT 1, comment TEXT);
CREATE TABLE gravity (domain TEXT NOT NULL, adlist_id INTEGER NOT NULL REFERENCES adlist (id));
""")
for name in ("Default", "pb-kids", "pb-guard", "pb-offline", "pb-paused", "pb-state", "pb-svc-tiktok", "pb-svc-youtube"):
    db.execute('INSERT INTO "group" (name, enabled) VALUES (?, ?)', (name, name in ("Default", "pb-kids", "pb-guard", "pb-paused")))
db.execute("INSERT INTO adlist (address, comment) VALUES ('https://example.org/tiktok.txt', 'pb:tiktok')")
db.execute("INSERT INTO adlist (address, comment) VALUES ('https://example.org/youtube.txt', 'pb:youtube')")
for line in open(sys.argv[2]):
    if line.startswith("||"):
        db.execute("INSERT INTO gravity (domain, adlist_id) VALUES (?, 1)", (line.strip(),))
db.commit()
EOF
}

# A box at the first start of a card flashed from the golden unit's image: no password (the welcome screen), the factory test's
# flag, and its first-start service has just run (the real tools/firstboot.sh): its own SSH keys, name, box id and address.
# Built once (the real installer takes a while) and kept in $WORK/box.tar; make_box gives every scenario a fresh copy.
build_box() {
  fresh_start
  echo end0 >"$WORK/iface"
  mkdir -p "$ROOT/etc/ssh/sshd_config.d" "$ROOT/root" "$ROOT/var/lib/dbus" "$ROOT/var/lib/systemd"
  printf 'Include /etc/ssh/sshd_config.d/*.conf\nPermitRootLogin yes\nPasswordAuthentication yes\n' >"$ROOT/etc/ssh/sshd_config"
  printf 'root:x:0:0:root:/root:/bin/bash\ndaemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin\n' >"$ROOT/etc/passwd"
  printf 'root:!$6$golden$locked:19000:0:99999:7:::\ndaemon:*:19000:0:99999:7:::\n' >"$ROOT/etc/shadow"
  SINKO_HOSTNAME=family.lan bash "$REPO/install.sh" >"$WORK/box-install.out" 2>&1 || { cat "$WORK/box-install.out"; fail "the box could not be installed"; }
  mock_set_password ""
  echo golden-opi >"$ROOT/etc/hostname"
  echo 0123456789abcdef0123456789abcdef >"$ROOT/etc/machine-id"
  ( umask 077; printf 'hostname=sinko\n' >"$ROOT/var/lib/sinko/firstboot" )
  printf -- '-----BEGIN EC PRIVATE KEY-----\nk\n-----END EC PRIVATE KEY-----\n-----BEGIN CERTIFICATE-----\nc\n-----END CERTIFICATE-----\n' >"$ROOT/etc/pihole/tls.pem"
  SINKO_FIRSTBOOT_WAIT=0 SINKO_FIRSTBOOT_TLS_WAIT=0 bash "$ROOT/opt/sinko/tools/firstboot.sh" >"$WORK/firstboot.out" 2>&1 \
    || { cat "$WORK/firstboot.out"; fail "test setup: the box's first start failed"; }
  [[ ! -e "$ROOT/var/lib/sinko/firstboot" && -e "$ROOT/etc/ssh/ssh_host_ed25519_key" ]] || fail "test setup: the first start did not finish"
  ( umask 077; printf 'hostname=sinko\ntailscale=0\nkeep_ssh=0\nmade=2026-10-25\n' >"$FLAG" )
  touch "$WORK/units/sinko-factory-qa.service.enabled"
  pihole-FTL --config database.DBinterval 60
  make_board
  make_gravity_db
  tar -C "$WORK" -cf "$WORK/box.tar" root units ftl.json
}
make_box() {
  rm -rf "$ROOT" "$WORK/units" "$WORK/run" "$WORK/qa-run"
  tar -C "$WORK" -xf "$WORK/box.tar"
  rm -f "$WORK/ntp-unsynced" "$WORK/dns-down" "$WORK/dns-never-blocks" "$WORK/upstream-down" "$WORK/leds.log" "$WORK/arch" \
        "$WORK/systemd-run-fails" "$WORK/tailscale-state" "$STUBS/tailscale" "$WORK/ftl-stop-fails"
  echo end0 >"$WORK/iface"
  echo 4000000 >"$WORK/df-free-kb"
  mock_auth true                                       # the seal of a scenario before switched the mock's sign-in off
  mock_set_password ""                                 # ... and a scenario may have set a password
  : >"$WORK/calls.log"
}
run_qa() {  # name [option]: runs the test, its output in $WORK/<name>.out, its status in QA_RC
  QA_RC=0
  bash "$QA" "${@:2}" >"$WORK/$1.out" 2>&1 || QA_RC=$?
}
has() { grep -qF -- "$2" "$WORK/$1.out" || { cat "$WORK/$1.out"; fail "$1: the output does not say: $2"; }; }
hasnt() { if grep -qF -- "$2" "$WORK/$1.out"; then cat "$WORK/$1.out"; fail "$1: the output says: $2"; fi; }
led_section() { sed -n "/^== $1\$/,/^== /p" "$WORK/leds.log" | sed '1d;/^== /d'; }      # what the lights did in one pattern
api_clients() { mock_api GET /api/clients | json_get '[c["client"] for c in d["clients"]]'; }
tiktok_on() { mock_api GET /api/groups | json_get '[g["enabled"] for g in d["groups"] if g["name"] == "pb-svc-tiktok"][0]'; }
world_digest() { ( cd "$ROOT" && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 -r sha256sum | sha256sum ); }

build_box
serve_dir "$ROOT/var/www/html" "$WEBPORT"

echo "--- without the flag it does nothing at all (every start of a customer's box)"
make_box
rm "$FLAG"
before="$(world_digest)"
run_qa noflag
(( QA_RC == 0 )) || { cat "$WORK/noflag.out"; fail "the test failed on a box without the flag"; }
has noflag "nothing to do"
[[ "$(world_digest)" == "$before" ]] || fail "the test changed something without the flag"
[[ ! -e "$WORK/leds.log" && ! -e "$WORK/qa-run" ]] || fail "the test touched the lights or kept notes without the flag"
grep -qE 'systemctl (poweroff|stop|disable)|systemd-run|passwd' "$WORK/calls.log" && fail "the test acted without the flag"

echo "--- a good box: every check passes, the box is sealed for its customer, the lights dance, then it switches off"
make_box
echo "golden unit's light setting" >"$ROOT/etc/armbian-leds.conf"
touch "$WORK/units/armbian-led-state.service.active"
run_qa pass
(( QA_RC == 0 )) || { cat "$WORK/pass.out"; fail "a good box did not pass"; }
hasnt pass "  FAIL  "
for shown in "lights    2 found on the board: green:power red:status" "64-bit ARM (aarch64)" "Allwinner H616-family SoC (OrangePi Zero3)" \
             "4 Cortex-A53 cores" "SoC at 51 °C" "969 MB" "mounted read-write" "3906 MB free on the card" "read back unchanged" \
             "end0 has a link" "end0 at 1000 Mbit/s" "end0 has the address 192.168.1.50" "default route through 192.168.1.1" \
             "set from a time server" "pihole-FTL is running" "database.DBinterval is 60 seconds" "gravity.db is whole" \
             "Sinko's groups are in gravity.db" "TikTok's block list is in gravity.db" "Pi-hole answers on port $DNSPORT" \
             "family.lan points at this box (192.168.1.50)" "github.com: NOERROR 140.82.121.4" "with TikTok allowed, tiktok.com resolves" \
             "TikTok blocked: pb-svc-tiktok is switched on" "TikTok is blocked for that device: tiktok.com gives NOERROR 0.0.0.0" \
             "only TikTok is stopped" "TikTok allowed again: tiktok.com resolves" "the parent page is served" "/pb/box.json names this box" \
             "sinko selfcheck: every check ok" "the sinko command works" "no password is set" "the first start finished" \
             "not installed (it is not part of Sinko)" "sealed: no password" "PASSED and sealed: switching off"; do
  has pass "$shown"
done
hasnt pass "input0::capslock"
hasnt pass "running it once more"
# The made-up device and the TikTok switch were put back (and the seal then made Sinko's objects again from nothing).
api_clients | grep -q "127.0.0.2" && fail "the made-up device of the blocking test is still in Pi-hole"
[[ "$(tiktok_on)" == False ]] || fail "TikTok was left blocked"
# Sealed for the customer, by the seal itself: what the customer's first start makes again is gone, its flag is armed.
grep -q "^passwd -R $ROOT -l root" "$WORK/calls.log" || fail "the seal did not lock root"
grep -qs '^hostname=sinko$' "$ROOT/var/lib/sinko/firstboot" || fail "the customer's first start is not armed"
compgen -G "$ROOT/etc/ssh/ssh_host_*" >/dev/null && fail "this start's SSH host keys are still there"
[[ ! -s "$ROOT/etc/machine-id" ]] || fail "this start's machine id is still there"
[[ ! -e "$ROOT/var/www/html/pb/box.json" && ! -e "$ROOT/var/lib/sinko/box-id" ]] || fail "this start's box id is still there"
# The factory test is gone for good, and nothing of it is left on the card.
[[ ! -e "$FLAG" ]] || fail "the flag is still there: the test would run again at the customer's"
[[ ! -e "$ROOT/etc/systemd/system/sinko-factory-qa.service" ]] || fail "the unit file is still there"
grep -q "systemctl disable sinko-factory-qa.service" "$WORK/calls.log" || fail "the unit was not disabled"
[[ ! -e "$WORK/reload-without-unit" ]] || fail "systemd was reloaded after the unit file was removed, from inside that unit: its TimeoutStartSec=infinity is gone then, and the default of 90 s kills a slow run before the power-off"
[[ ! -e "$REPORT" && ! -e "$ROOT/var/www/html/pb/factory-qa.txt" && ! -e "$WORK/qa-run" ]] || fail "a report or the test's notes were left"
[[ ! -e "$ROOT/var/lib/sinko/.factory-qa-write" ]] || fail "the card's write test left its file"
grep -q "systemctl poweroff" "$WORK/calls.log" || fail "the box did not switch itself off"
grep -n "systemctl poweroff" "$WORK/calls.log" | tail -n1 | cut -d: -f1 >"$WORK/off-line"
(( $(grep -n "^passwd -R $ROOT -l root" "$WORK/calls.log" | cut -d: -f1) < $(cat "$WORK/off-line") )) || fail "the box switched off before it was sealed"
grep -q "systemd-run" "$WORK/calls.log" && fail "SOS was started on a box that passed"
# The lights: testing, then the dance (100 steps of a chase over both lights, then five flashes of both), then every light on.
dance="$(led_section dance)"
[[ "$(grep -c '^pause 0.08$' <<<"$dance")" == 100 ]] || fail "the chase is not 100 steps of 80 ms"
[[ "$(grep -c '^pause 0.25$' <<<"$dance")" == 10 ]] || fail "the dance does not end with five flashes"
[[ "$(grep -c '^green:power brightness 1$' <<<"$dance")" -ge 55 && "$(grep -c '^red:status brightness 1$' <<<"$dance")" -ge 55 ]] \
  || fail "the chase does not go over both lights"
grep -q '^== testing$' "$WORK/leds.log" || fail "the lights did not show the test running"
for led in green:power red:status; do
  [[ "$(cat "$ROOT/sys/class/leds/$led/brightness")" == 1 ]] || fail "$led is not on while the box switches off"
done
[[ "$(cat "$ROOT/sys/class/leds/input0::capslock/trigger")" == "[kbd-capslock] none" ]] || fail "the keyboard's light was touched"
# Armbian keeps the setting the box started with, not "every light on".
grep -q "systemctl stop armbian-led-state.service" "$WORK/calls.log" || fail "Armbian's light service was not stopped before the power-off"
[[ "$(cat "$ROOT/etc/armbian-leds.conf")" == "golden unit's light setting" ]] || fail "Armbian would start the customer's box with every light on"

echo "--- a box that had no Armbian light file: none is left behind"
make_box
touch "$WORK/units/armbian-led-state.service.active"
run_qa nofile
(( QA_RC == 0 )) || { cat "$WORK/nofile.out"; fail "the box did not pass"; }
[[ ! -e "$ROOT/etc/armbian-leds.conf" ]] || fail "a light file with every light on was left for Armbian"

echo "--- no Ethernet link: the report says why, the flag stays, SOS on the lights, nothing is sealed, nothing switches off"
make_box
echo 0 >"$ROOT/sys/class/net/end0/carrier"
run_qa nolink
(( QA_RC == 1 )) || { cat "$WORK/nolink.out"; fail "a box without a link did not fail (status $QA_RC)"; }
has nolink "FAIL  network   end0 has no link: is the Ethernet cable plugged in"
[[ -f "$REPORT" && "$(stat -c %a "$REPORT")" == 600 ]] || fail "no report in /root, or it can be read by everybody"
grep -A1 "^What failed:" "$REPORT" | grep -q "network   end0 has no link" || { cat "$REPORT"; fail "the report does not say what failed"; }
grep -q "PASS  memory" "$REPORT" || fail "the report does not list every check"
grep -q "runs again at every start" "$REPORT" || fail "the report does not say what to do"
cmp -s "$REPORT" "$ROOT/var/www/html/pb/factory-qa.txt" || fail "the report cannot be read on the bench network"
[[ "$(stat -c %a "$ROOT/var/www/html/pb/factory-qa.txt")" == 644 ]] || fail "the web copy of the report cannot be served"
[[ -f "$FLAG" && -f "$ROOT/etc/systemd/system/sinko-factory-qa.service" && -e "$WORK/units/sinko-factory-qa.service.enabled" ]] \
  || fail "the flag or the unit was removed from a box that failed: it would not test again"
grep -q "^systemd-run --quiet --collect --unit=sinko-factory-qa-sos.service .* $QA --sos$" "$WORK/calls.log" \
  || { cat "$WORK/calls.log"; fail "the SOS was not started as a unit of its own"; }
grep -qE "passwd -R .* -l root|systemctl poweroff|systemctl disable sinko-factory-qa" "$WORK/calls.log" && fail "a box that failed was sealed or switched off"
[[ -e "$ROOT/etc/ssh/ssh_host_ed25519_key" ]] || fail "a box that failed lost its keys (it was sealed)"
api_clients | grep -q "127.0.0.2" && fail "the made-up device was left in Pi-hole"
echo "    the SOS unit: S O S on both lights at once (dot 0.2 s, dash 0.6 s, letters 3 dots apart, words 7)"
: >"$WORK/leds.log"
run_qa sos --sos
sos="$(led_section sos)"
expected="$(for sym in . . . - - - . . .; do
  echo "green:power brightness 1"; echo "red:status brightness 1"
  if [[ "$sym" == . ]]; then echo "pause 0.2"; else echo "pause 0.6"; fi
  echo "green:power brightness 0"; echo "red:status brightness 0"; echo "pause 0.2"
done)"
got="$(grep -v -e ' trigger ' -e '^pause 0.4$' -e '^pause 0.8$' <<<"$sos")"
[[ "$got" == "$expected" ]] || { diff <(echo "$expected") <(echo "$got") || true; fail "the lights do not show SOS"; }
[[ "$(grep -c '^pause 0.4$' <<<"$sos")" == 3 && "$(tail -n1 <<<"$sos")" == "pause 0.8" ]] || fail "the gaps between letters and words are wrong"

echo "--- when systemd-run cannot start the SOS unit, the test shows it itself"
make_box
echo 0 >"$ROOT/sys/class/net/end0/carrier"
touch "$WORK/systemd-run-fails"
run_qa sosself
(( QA_RC == 1 )) || fail "the test did not fail"
has sosself "shown from here"
grep -q '^== sos$' "$WORK/leds.log" || fail "no SOS was shown"

echo "--- every hardware fault the test knows, at once: each one is named"
make_box
echo armv7l >"$WORK/arch"
printf 'xunlong,orangepi-zero2\0allwinner,sun50i-h6\0' >"$ROOT/proc/device-tree/compatible"
sed -i '/^processor\t: 3/,$d' "$ROOT/proc/cpuinfo"
echo 81250 >"$ROOT/sys/class/thermal/thermal_zone2/temp"           # cpu-thermal
printf 'MemTotal:        1503000 kB\n' >"$ROOT/proc/meminfo"
printf '/dev/mmcblk0p1 / ext4 ro,noatime 0 0\n' >"$ROOT/proc/mounts"
echo 500000 >"$WORK/df-free-kb"
echo 10 >"$ROOT/sys/class/net/end0/speed"
touch "$WORK/ntp-unsynced"
pihole-FTL --config database.DBinterval 1
run_qa hardware
(( QA_RC == 1 )) || { cat "$WORK/hardware.out"; fail "a faulty box did not fail"; }
for shown in "the system is armv7l, not aarch64" "names no Allwinner H616 or H618 (xunlong,orangepi-zero2 allwinner,sun50i-h6): not an" "3 cores running, 3 of them Cortex-A53" \
             "SoC at 81 °C: 75 °C or more" "1.5 GB Orange Pi Zero 3" "not mounted read-write (ro,noatime)" "488 MB free on the card: less than 1024 MB" \
             "end0 at only 10 Mbit/s" "not set from a time server" "database.DBinterval is '1', not 60"; do
  has hardware "$shown"
done
[[ "$(grep -c '^  FAIL' "$WORK/hardware.out")" == 10 ]] || { cat "$WORK/hardware.out"; fail "not exactly the ten faults were found"; }
has hardware "after 2 s still not up: the clock"

echo "--- a board with less memory, and one whose temperature cannot be read"
make_box
printf 'MemTotal:         880000 kB\n' >"$ROOT/proc/meminfo"
rm -rf "$ROOT/sys/class/thermal"
run_qa memory
has memory "FAIL  memory    859 MB: less than 900 MB"
has memory "no temperature sensor could be read"

echo "--- Pi-hole that does not block: the blocking test fails, and says what it saw"
make_box
touch "$WORK/dns-never-blocks"
run_qa noblock
(( QA_RC == 1 )) || fail "a box that does not block passed"
has noblock "TikTok is switched on but tiktok.com still resolves for the device (NOERROR 93.184.215.14)"
api_clients | grep -q "127.0.0.2" && fail "the made-up device was left in Pi-hole after a failed blocking test"
[[ "$(tiktok_on)" == False ]] || fail "TikTok was left blocked after a failed blocking test"

echo "--- no internet: the names from upstream fail, and the blocking test cannot show anything"
make_box
touch "$WORK/upstream-down"
run_qa offline
has offline "github.com does not resolve (SERVFAIL (no address))"
has offline "tiktok.com does not resolve even with TikTok allowed"

echo "--- Pi-hole does not answer DNS at all"
make_box
touch "$WORK/dns-down"
SINKO_QA_SETTLE=0 run_qa nodns
has nodns "Pi-hole does not answer on 127.0.0.1 port $DNSPORT"
has nodns "FAIL  blocking  not tested: Pi-hole does not answer DNS questions"
has nodns "the parent page is served"

echo "--- Pi-hole's database is damaged, or the TikTok list was never downloaded"
make_box
printf 'not a database at all' >"$ROOT/etc/pihole/gravity.db"
run_qa baddb
has baddb "Pi-hole's database $ROOT/etc/pihole/gravity.db cannot be read"
make_box
python3 -c "import sqlite3, sys; db = sqlite3.connect(sys.argv[1]); db.execute('DELETE FROM gravity'); db.commit()" "$ROOT/etc/pihole/gravity.db"
run_qa nolist
has nolist "TikTok's block list has no entries in gravity.db"

echo "--- a box with a password, an unfinished first start and a page of another version"
make_box
mock_set_password "seller-password"
printf 'hostname=sinko\nkeys=done\nids=done\ntries=1\n' >"$ROOT/var/lib/sinko/firstboot"
sed -i 's/<meta name="sinko-version" content="[^"]*">/<meta name="sinko-version" content="0.0.1">/' "$ROOT/var/www/html/index.html"
run_qa unsealed
has unsealed "a password is set: the customer could not claim this box"
has unsealed "the first start has not finished"
has unsealed "running it once more"
grep -q "systemctl start sinko-firstboot.service" "$WORK/calls.log" || fail "the unfinished first start was not run once more"
has unsealed "the parent page is not served at http://127.0.0.1:$WEBPORT/ as Sinko"

echo "--- Tailscale: not logged in is ready for the customer; logged in fails; missing when the golden unit had it fails"
make_box
make_tailscale NeedsLogin
mkdir -p "$ROOT/var/lib/tailscale"; echo "golden machine key" >"$ROOT/var/lib/tailscale/tailscaled.state"; echo id >"$ROOT/var/lib/tailscale/tailscaled.log.conf"
run_qa tsready
(( QA_RC == 0 )) || { cat "$WORK/tsready.out"; fail "a box with Tailscale ready for its customer did not pass"; }
has tsready "installed, not logged in: READY FOR FIRST-TIME USER AUTH"
has tsready "Tailscale's identity removed"
[[ ! -e "$ROOT/var/lib/tailscale/tailscaled.state" && ! -e "$ROOT/var/lib/tailscale/tailscaled.log.conf" ]] || fail "every box would share the golden unit's Tailscale identity"
grep -q "systemctl stop tailscaled.service" "$WORK/calls.log" || fail "tailscaled was not stopped before its identity was removed"
make_box
make_tailscale Running
run_qa tsin
(( QA_RC == 1 )) || fail "a box logged in to Tailscale passed"
has tsin "logged in (Running)"
make_box
sed -i 's/^tailscale=0$/tailscale=1/' "$FLAG"
run_qa tsgone
has tsgone "FAIL  tailscale not installed, but the golden unit had it"

echo "--- a seal that stops is a failure, with the seal's own words in the report"
make_box
touch "$WORK/ftl-stop-fails"
run_qa sealfail
(( QA_RC == 1 )) || { cat "$WORK/sealfail.out"; fail "a box whose seal stopped passed"; }
has sealfail "FAIL  seal      tools/seal.sh stopped"
grep -q "^--- tools/seal.sh" "$REPORT" || fail "the report does not carry the seal's output"
[[ -f "$FLAG" ]] || fail "the flag was removed although the box is not sealed"
grep -q "systemctl poweroff" "$WORK/calls.log" && fail "a box whose seal stopped switched itself off"

echo "--- a test unit's flag keeps SSH open through the seal"
make_box
sed -i 's/^keep_ssh=0$/keep_ssh=1/' "$FLAG"
run_qa keepssh
(( QA_RC == 0 )) || { cat "$WORK/keepssh.out"; fail "the test unit did not pass"; }
has keepssh "--keep-ssh-access"
grep -q "^passwd -R $ROOT -l root" "$WORK/calls.log" && fail "root was locked on a test unit"

echo "--- a board on which no light is found: the test fails, and says it cannot show its result"
make_box
rm -rf "$ROOT/sys/class/leds/green:power" "$ROOT/sys/class/leds/red:status"
run_qa nolights
(( QA_RC == 1 )) || fail "a box without lights passed"
has nolights "no light was found on the board"
has nolights "there is no light to show SOS on"

echo "--- the lights are found by their driver (gpio-leds), by their names when there is none, or by SINKO_QA_LEDS; eth0 is a port too"
make_box
rm "$ROOT/sys/devices/platform/leds/driver"
mkdir -p "$ROOT/sys/bus/platform/drivers/stmmac"
ln -sfn ../../../bus/platform/drivers/stmmac "$ROOT/sys/devices/platform/leds/driver"
run_qa phyleds --check
has phyleds "no light was found on the board"
rm "$ROOT/sys/class/leds/green:power/device" "$ROOT/sys/class/leds/red:status/device"
run_qa bynames --check
has bynames "lights    2 found on the board: green:power red:status"
SINKO_QA_LEDS="red:status" run_qa named --check
has named "lights    1 found on the board: red:status"
mv "$ROOT/sys/class/net/end0" "$ROOT/sys/class/net/eth0"
echo eth0 >"$WORK/iface"
run_qa eth0 --check
has eth0 "eth0 has a link"
has eth0 "eth0 has the address 192.168.1.50"

echo "--- --check: the tests only, on a golden unit (with its password): nothing is sealed, switched off or left behind"
make_box
rm "$FLAG"
mock_set_password "seller-password"
before="$(world_digest)"
run_qa check --check
(( QA_RC == 0 )) || { cat "$WORK/check.out"; fail "a good golden unit does not pass --check"; }
has check "INFO  sinko     a password is set (the seal removes it)"
has check "Every check passed."
hasnt check "first start"
[[ "$(world_digest)" == "$before" ]] || fail "--check changed files"
grep -qE "passwd|systemctl (poweroff|disable|stop)|systemd-run" "$WORK/calls.log" && fail "--check acted on the box"
[[ ! -e "$WORK/leds.log" ]] || fail "--check touched the lights"

echo "--- --leds: shows the three patterns, then puts the lights back as they were"
make_box
run_qa leds --leds
(( QA_RC == 0 )) || { cat "$WORK/leds.out"; fail "--leds failed"; }
has leds "Lights: green:power red:status"
for p in testing dance restore; do grep -q "^== $p$" "$WORK/leds.log" || fail "--leds did not show: $p"; done
[[ "$(grep -c '^pause 0.6$' "$WORK/leds.log")" == 6 ]] || fail "--leds did not show two rounds of SOS"
grep -q "^red:status trigger heartbeat$" <(sed -n '/^== restore$/,$p' "$WORK/leds.log") || fail "the red light did not get its heartbeat back"
[[ "$(cat "$ROOT/sys/class/leds/red:status/trigger")" == heartbeat && "$(cat "$ROOT/sys/class/leds/green:power/brightness")" == 1 ]] \
  || fail "the lights are not as they were"

echo "--- prepare-golden-master.sh: refuses a unit that fails the checks, and changes nothing"
make_box
rm "$FLAG"
echo 0 >"$ROOT/sys/class/net/end0/carrier"
before="$(world_digest)"
if bash "$PREPARE" --yes >"$WORK/prep-refuse.out" 2>&1; then fail "a unit that fails the checks was prepared"; fi
grep -q "does not pass the factory test's checks" "$WORK/prep-refuse.out" || { cat "$WORK/prep-refuse.out"; fail "no message about the checks"; }
[[ ! -e "$FLAG" && -e "$ROOT/etc/ssh/ssh_host_ed25519_key" ]] || fail "a refused unit was armed or sealed"
grep -q "^passwd -R $ROOT -l root" "$WORK/calls.log" && fail "a refused unit was sealed"
if bash "$PREPARE" --hostname "two words" >"$WORK/prep-name.out" 2>&1; then fail "a bad host name was accepted"; fi
grep -q "not a usable host name" "$WORK/prep-name.out" || fail "no message about the host name"

echo "--- prepare-golden-master.sh --dry-run: the checks, the seal's plan and the copy commands; nothing changes"
make_box
rm "$FLAG"
mock_set_password "seller-password"
bash "$PREPARE" --dry-run >"$WORK/prep-dry.out" 2>&1 || { cat "$WORK/prep-dry.out"; fail "the dry run failed"; }
for shown in "Every check passed." "Dry run: nothing was changed." "It would write $FLAG (hostname=sinko, tailscale=0" \
             "sudo dd if=/dev/sdX of=sinko-$(cat "$REPO/VERSION")-orangepizero3.img bs=4M status=progress conv=fsync" \
             "31.9 GB (31914983424 bytes" "lsblk -b -d -o NAME,SIZE,MODEL,TRAN" "xz -T0 -9" "sha256sum" "/dev/rdiskN" \
             "This card holds 31.9 GB: the image is that big"; do
  grep -qF -- "$shown" "$WORK/prep-dry.out" || { cat "$WORK/prep-dry.out"; fail "the dry run does not show: $shown"; }
done
[[ ! -e "$FLAG" && -e "$ROOT/etc/ssh/ssh_host_ed25519_key" ]] || fail "the dry run armed or sealed the unit"
grep -qE "^passwd -R .* -l root|systemctl enable sinko-factory-qa" "$WORK/calls.log" && fail "the dry run acted"

echo "--- prepare-golden-master.sh: checks, seals, arms the factory test and prints how to copy the card"
make_box
rm "$FLAG"
rm -f "$WORK/units/sinko-factory-qa.service.enabled"
mock_set_password "seller-password"
make_tailscale NeedsLogin
bash "$PREPARE" --yes --hostname Family-Box --no-zerofill >"$WORK/prep.out" 2>&1 || { cat "$WORK/prep.out"; fail "the golden unit could not be prepared"; }
grep -q "^passwd -R $ROOT -l root" "$WORK/calls.log" || fail "the golden unit was not sealed"
[[ -f "$FLAG" && "$(stat -c %a "$FLAG")" == 600 ]] || fail "no flag, or anybody can read it"
for line in "hostname=family-box" "tailscale=1" "keep_ssh=0" "made=$(date +%Y-%m-%d)"; do
  grep -qx "$line" "$FLAG" || { cat "$FLAG"; fail "the flag does not say $line"; }
done
[[ -e "$WORK/units/sinko-factory-qa.service.enabled" ]] || fail "the factory test's unit was not enabled"
grep -q '^hostname=family-box$' "$ROOT/var/lib/sinko/firstboot" || fail "the seal did not get the host name"
for shown in "armed: $FLAG and sinko-factory-qa.service" "unset HISTFILE; poweroff" "sudo dd if=/dev/sdX of=sinko-" \
             "xzcat sinko-" "Keep this image for the factory" "WARNING: --no-zerofill"; do
  grep -qF -- "$shown" "$WORK/prep.out" || { cat "$WORK/prep.out"; fail "the end of the preparation does not say: $shown"; }
done
echo "    ... and the next start of a card made from it is a factory test against what the flag says"
touch "$WORK/units/pihole-FTL.service.active" "$WORK/units/sinko.service.active"     # the card starts: Pi-hole, the scheduler ...
printf -- '-----BEGIN EC PRIVATE KEY-----\nk\n-----END EC PRIVATE KEY-----\n-----BEGIN CERTIFICATE-----\nc\n-----END CERTIFICATE-----\n' >"$ROOT/etc/pihole/tls.pem"
SINKO_FIRSTBOOT_WAIT=0 SINKO_FIRSTBOOT_TLS_WAIT=0 bash "$ROOT/opt/sinko/tools/firstboot.sh" >"$WORK/firstboot.out" 2>&1 \
  || { cat "$WORK/firstboot.out"; fail "the first start of the prepared image failed"; }                  # ... and its first start
[[ ! -e "$ROOT/var/lib/sinko/firstboot" && "$(cat "$ROOT/etc/hostname")" == family-box ]] || fail "test setup: the first start did not finish"
run_qa fromgolden
(( QA_RC == 0 )) || { cat "$WORK/fromgolden.out"; fail "a box from the prepared image did not pass"; }
grep -q "seal.sh --yes --no-zerofill --hostname family-box" "$WORK/fromgolden.out" || fail "the box was not sealed with the golden unit's host name"

echo "factory test: all scenarios passed"
