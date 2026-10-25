#!/usr/bin/env bash
# The factory test of a ready-made Sinko box. Every card is flashed from the golden unit's image (made with
# tools/prepare-golden-master.sh); the first time a card starts, this tests the board and the whole Sinko stack on it, and a box
# that passes seals itself for its customer and switches itself off. A technician plugs in Ethernet, then power, and only
# watches the board's lights:
#
#   one light after the other, a slow double beat    testing (a few minutes, the seal at the end included)
#   a fast chase, then every light flashes 5 times    passed: the box is sealed. Every light then stays on while it shuts down;
#                                                     when every light is off, unplug it: it is ready to be boxed
#   every light together: S O S, over and over        failed. What failed is in /root/FAILED_QA_REPORT.txt on the card and,
#                                                     while Pi-hole runs, at http://<the box's address>/pb/factory-qa.txt
#
# A box that failed keeps its flag, so the test runs again at every start until it passes (plug the cable in, then switch it off
# and on). Nothing runs without the flag (/var/lib/sinko/factory-qa, which prepare-golden-master.sh writes on the golden unit),
# and a box that passed removes the flag, disables sinko-factory-qa.service and deletes its unit file: a customer's box never
# runs this.
#
#   sudo /opt/sinko/tools/factory-qa.sh --check   only the tests, on any box, nothing else (prepare-golden-master.sh runs this on
#                                                 the golden unit before it seals it)
#   sudo /opt/sinko/tools/factory-qa.sh --leds    shows the three patterns on this board's lights, then puts the lights back
#
# What is tested, and why each limit is what it is: docs/factory-qa.md.
set -uo pipefail

R="${SINKO_ROOT:-}"                                  # test hook: act on a fake root
STATE_DIR="${SINKO_STATE_DIR:-$R/var/lib/sinko}"
FLAG="$STATE_DIR/factory-qa"
APP_DIR="$R/opt/sinko"
BIN="$APP_DIR/bin/sinko"
SEAL="$APP_DIR/tools/seal.sh"
SELF="$(readlink -f "${BASH_SOURCE[0]}")"
REPORT="$R/root/FAILED_QA_REPORT.txt"
UNIT=sinko-factory-qa.service
UNIT_FILE="$R/etc/systemd/system/$UNIT"
SOS_UNIT=sinko-factory-qa-sos.service
LED_DIR="$R/sys/class/leds"
NET_DIR="$R/sys/class/net"
THERMAL_DIR="$R/sys/class/thermal"
PROC="$R/proc"
ARMBIAN_LEDS="$R/etc/armbian-leds.conf"
RUN_DIR="${SINKO_QA_RUN_DIR:-/run/sinko-factory-qa}"  # in memory: what the test keeps for itself never reaches the card
FAST="${SINKO_QA_FAST:-0}"                           # test hook: the light patterns without their pauses
LED_LOG="${SINKO_QA_LED_LOG:-}"                      # test hook: every write to a light, and every pause, in order

# The limits. docs/factory-qa.md says why each is what it is, and tests/test_docs.py holds the guide to these numbers.
WAIT="${SINKO_QA_WAIT:-60}"   # seconds for Pi-hole, the network, the page, the scheduler and the clock to come up
MAX_TEMP_C=75                 # the SoC, on the bench, while it is tested
MIN_RAM_MB=900                # a 1 GB board shows a little less than 1024 MB: the kernel and the firmware keep some
MIN_FREE_MB=1024              # free on the card (a first installation asks for more than 1 GB too)
MIN_LINK_MBIT=100             # the Zero 3's port does 1000; a 10 Mbit/s link means a damaged port, cable or switch
DBINTERVAL=60                 # Pi-hole v6's database.DBinterval, in seconds: its default
SELFCHECK_WAIT="${SINKO_QA_SELFCHECK_WAIT:-90}"   # what an update gives the same check
QA_CLIENT=127.0.0.2           # the made-up device of the blocking test: a loopback address no device at home can have

MODE=factory
case "${1:-}" in
  "") ;;
  --check) MODE=check ;;
  --leds) MODE=leds ;;
  --sos) MODE=sos ;;                                 # the endless SOS, as a unit of its own (started by a failed test)
  -h|--help) sed -n '2,/^set -uo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
  *) echo "factory-qa: unknown option $1 (--check, --leds or --help)" >&2; exit 2 ;;
esac

log() { echo "factory-qa: $*"; }
die() { echo "factory-qa: $*" >&2; exit 2; }

[[ "$(id -u)" -eq 0 ]] || die "run as root"
if [[ "$MODE" == factory && ! -f "$FLAG" ]]; then
  log "nothing to do: this box has passed its factory test (or was never armed for one)"
  exit 0
fi

flag_value() {  # key: what prepare-golden-master.sh wrote about the golden unit
  sed -n "s/^$1=//p" "$FLAG" 2>/dev/null | head -n1
}

# ------------------------------------------------------------------ results
RESULTS=()                                           # "PASS|area|text", in the order the checks were made
FAILS=0
DETAILS=""                                           # longer output for the report (the self-check's, the seal's)
record() {  # status area text
  RESULTS+=("$1|$2|$3")
  if [[ "$1" == FAIL ]]; then FAILS=$(( FAILS + 1 )); fi
  printf '  %-4s  %-9s %s\n' "$1" "$2" "$3"
}
pass() { record PASS "$1" "$2"; }
fail() { record FAIL "$1" "$2"; }
info() { record INFO "$1" "$2"; }
add_details() { DETAILS+=$'\n'"--- $1"$'\n'"$2"$'\n'; }

# ------------------------------------------------------------------ the lights
# The board's own lights: gpio-leds (or pwm-leds) from the device tree. On the Orange Pi Zero 3 with Armbian these are
# green:power (on) and red:status (a heartbeat), both leds-gpio; other kernels name them differently. Not a keyboard's lights,
# not a card reader's, not an Ethernet port's (newer kernels show those as lights too). SINKO_QA_LEDS names them instead,
# separated by spaces, for a board whose lights this does not recognise.
LEDS=()
declare -A LED_TRIGGER=() LED_BRIGHT=()
led_is_board_light() {  # name
  local link drv
  link="$LED_DIR/$1/device/driver"
  if [[ -e "$link" ]]; then
    drv="$(basename "$(readlink -f "$link")")"
    case "$drv" in leds-gpio|leds_gpio|leds-pwm|leds_pwm|pwm-leds) return 0 ;; *) return 1 ;; esac
  fi
  # No driver to ask: a device tree's name has a colour in it (red:status); a keyboard's (input3::capslock) and a card
  # reader's (mmc0::) have none.
  case "$1" in input*|mmc*) return 1 ;; esac
  [[ "$1" =~ (red|green|blue|white|yellow|orange|amber) ]]
}
led_detect() {
  LEDS=()
  local d name
  if [[ -n "${SINKO_QA_LEDS:-}" ]]; then
    for name in $SINKO_QA_LEDS; do
      if [[ -e "$LED_DIR/$name/brightness" ]]; then LEDS+=("$name"); fi
    done
    return 0
  fi
  for d in "$LED_DIR"/*; do
    [[ -e "$d/brightness" ]] || continue
    name="${d##*/}"
    if led_is_board_light "$name"; then LEDS+=("$name"); fi
  done
  return 0
}
led_write() {  # name file value
  printf '%s\n' "$3" >"$LED_DIR/$1/$2" 2>/dev/null || true
  if [[ -n "$LED_LOG" ]]; then echo "$1 $2 $3" >>"$LED_LOG"; fi
}
led_mark() { if [[ -n "$LED_LOG" ]]; then echo "== $1" >>"$LED_LOG"; fi; }
led_save() {  # what each light does now (its trigger, or its brightness when it has none), to put it back afterwards
  local n t
  for n in "${LEDS[@]}"; do
    t="$(sed -n 's/.*\[\([^]]*\)\].*/\1/p' "$LED_DIR/$n/trigger" 2>/dev/null | head -n1)"
    LED_TRIGGER[$n]="${t:-none}"
    LED_BRIGHT[$n]="$(cat "$LED_DIR/$n/brightness" 2>/dev/null || echo 0)"
  done
}
# shellcheck disable=SC2329  # also called by the traps below
led_restore() {
  local n
  led_mark restore
  for n in "${LEDS[@]}"; do
    led_write "$n" trigger "${LED_TRIGGER[$n]:-none}"
    if [[ "${LED_TRIGGER[$n]:-none}" == none ]]; then led_write "$n" brightness "${LED_BRIGHT[$n]:-0}"; fi
  done
}
led_manual() { local n; for n in "${LEDS[@]}"; do led_write "$n" trigger none; done; }   # the kernel lets go of them
led_on() {
  local max
  max="$(cat "$LED_DIR/$1/max_brightness" 2>/dev/null || echo 1)"
  [[ "$max" =~ ^[0-9]+$ && "$max" -gt 0 ]] || max=1
  led_write "$1" brightness "$max"
}
led_off() { led_write "$1" brightness 0; }
led_all() {  # 1 = every light on, 0 = every light off
  local n
  for n in "${LEDS[@]}"; do
    if (( $1 )); then led_on "$n"; else led_off "$n"; fi
  done
}
pause() {
  if [[ -n "$LED_LOG" ]]; then echo "pause $1" >>"$LED_LOG"; fi
  if (( FAST )); then sleep 0.01; else sleep "$1"; fi
}

# Testing: a slow double beat on one light after the other, until it is stopped.
led_testing() {
  local n
  if (( ${#LEDS[@]} == 0 )); then return 0; fi
  led_mark testing
  led_manual
  while :; do
    for n in "${LEDS[@]}"; do
      led_all 0
      led_on "$n"; pause 0.15; led_off "$n"; pause 0.15
      led_on "$n"; pause 0.15; led_off "$n"; pause 0.75
    done
  done
}
# Passed: 8 seconds of a fast chase (one light after the other, 80 ms each), then every light flashes 5 times together.
led_victory_dance() {
  local s
  if (( ${#LEDS[@]} == 0 )); then return 0; fi
  led_mark dance
  led_manual
  for (( s = 0; s < 100; s++ )); do
    led_all 0
    led_on "${LEDS[s % ${#LEDS[@]}]}"
    pause 0.08
  done
  for (( s = 0; s < 5; s++ )); do
    led_all 1; pause 0.25
    led_all 0; pause 0.25
  done
}
# Failed: S O S in Morse on every light together (a dot is 0.2 s, a dash three dots; three dots between letters, seven
# between two SOS), for as long as the box has power. SINKO_QA_SOS_ROUNDS (a test hook) stops it after that many.
led_sos_once() {
  local letter i
  for letter in ... --- ...; do
    for (( i = 0; i < ${#letter}; i++ )); do
      led_all 1
      if [[ "${letter:i:1}" == . ]]; then pause 0.2; else pause 0.6; fi
      led_all 0; pause 0.2
    done
    pause 0.4
  done
  pause 0.8
}
led_sos_forever() {
  local rounds="${SINKO_QA_SOS_ROUNDS:-0}" r=0
  if (( ${#LEDS[@]} == 0 )); then return 0; fi
  led_mark sos
  led_manual
  while :; do
    led_sos_once
    r=$(( r + 1 ))
    if (( rounds > 0 && r >= rounds )); then return 0; fi
  done
}

# ------------------------------------------------------------------ the network port
default_dev() { ip -4 route show default 2>/dev/null | awk '{for (i=1;i<NF;i++) if ($i=="dev") {print $(i+1); exit}}'; }
# The wired port: the one the default route uses, else eth0, else end0 (the name Armbian gives the Zero 3's port with a
# recent systemd), else the first wired port there is. Not Wi-Fi: a box works on its cable.
pick_iface() {
  local dev d
  dev="$(default_dev)"
  if [[ -n "$dev" && -e "$NET_DIR/$dev" && ! -e "$NET_DIR/$dev/wireless" ]]; then printf '%s' "$dev"; return 0; fi
  for dev in eth0 end0; do
    if [[ -e "$NET_DIR/$dev" ]]; then printf '%s' "$dev"; return 0; fi
  done
  for d in "$NET_DIR"/*; do
    dev="${d##*/}"
    [[ "$dev" != lo && -e "$d/device" && ! -e "$d/wireless" ]] || continue
    if [[ "$(cat "$d/type" 2>/dev/null)" == 1 ]]; then printf '%s' "$dev"; return 0; fi
  done
  return 1
}
iface_ipv4() {  # dev
  local addr
  addr="$(ip -4 -o addr show dev "$1" scope global 2>/dev/null | awk 'NR==1 {print $4}')"
  addr="${addr%/*}"
  if [[ "$addr" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then printf '%s' "$addr"; fi
}

# Where Pi-hole serves the page (and its API): the box program decides it from Pi-hole's webserver.port, as for everything else.
web_base() {
  if [[ -n "${SINKO_QA_WEB_URL:-}" ]]; then printf '%s' "${SINKO_QA_WEB_URL%/}"; return 0; fi
  python3 - "$BIN" <<'PYEOF' 2>/dev/null || printf 'http://127.0.0.1:80'
import importlib.machinery, importlib.util, sys
sys.dont_write_bytecode = True
loader = importlib.machinery.SourceFileLoader("sinko_box", sys.argv[1])
box = importlib.util.module_from_spec(importlib.util.spec_from_loader("sinko_box", loader))
loader.exec_module(box)
print(box.discover_base_url(), end="")
PYEOF
}

# ------------------------------------------------------------------ waiting for the box to come up
not_ready() {  # what has not come up yet, or nothing
  local missing=() u dev
  systemctl is-active --quiet pihole-FTL.service || missing+=("Pi-hole")
  for u in NetworkManager.service systemd-networkd.service; do
    if systemctl is-enabled --quiet "$u" 2>/dev/null && ! systemctl is-active --quiet "$u"; then missing+=("${u%.service}"); fi
  done
  if ! dev="$(pick_iface)" || [[ -z "$(iface_ipv4 "$dev")" ]]; then missing+=("an address on the wired network"); fi
  [[ "$(curl -s -k -o /dev/null -w '%{http_code}' --max-time 3 "$WEB_BASE/" 2>/dev/null)" == 200 ]] || missing+=("the parent page")
  systemctl is-active --quiet sinko.service || missing+=("the scheduler")
  [[ "$(timedatectl show -p NTPSynchronized --value 2>/dev/null)" == yes ]] || missing+=("the clock")
  if (( ${#missing[@]} )); then printf '%s, ' "${missing[@]}" | sed 's/, $//'; fi
}
wait_until_ready() {
  local waited=0 missing
  while :; do
    missing="$(not_ready)"
    if [[ -z "$missing" ]]; then log "everything is up (after ${waited} s)"; return 0; fi
    if (( waited >= WAIT )); then
      log "after ${WAIT} s still not up: $missing (the tests below say more)"
      return 1
    fi
    sleep 2; waited=$(( waited + 2 ))
  done
}

# The box's first start (tools/firstboot.sh) gives the network 30 seconds, and a switch that holds a new link back for longer
# (spanning tree, on a managed switch) makes it end without the box's address, to be set at the next start. Now that the network
# is up, it runs once more (its flag remembers what it did already, so only the address is left).
finish_first_start() {
  [[ -e "$STATE_DIR/firstboot" ]] || return 0
  log "the box's first start ended before the network was up: running it once more"
  systemctl start sinko-firstboot.service >/dev/null 2>&1 || true
}

# ------------------------------------------------------------------ the tests
check_lights() {
  if (( ${#LEDS[@]} )); then pass lights "${#LEDS[@]} found on the board: ${LEDS[*]}"
  else fail lights "no light was found on the board (/sys/class/leds), so this test cannot show its result"; fi
}

check_board() {
  local arch compat model cpus a53
  arch="$(uname -m)"
  if [[ "$arch" == aarch64 ]]; then pass board "64-bit ARM (aarch64)"
  else fail board "the system is $arch, not aarch64: this is not the Orange Pi Zero 3 image"; fi
  compat="$(tr '\0' ' ' <"$PROC/device-tree/compatible" 2>/dev/null || true)"
  compat="${compat%"${compat##*[! ]}"}"                # without the space the last NUL became
  model="$(tr -d '\0' <"$PROC/device-tree/model" 2>/dev/null || true)"
  # The Orange Pi Zero 3 has an H618, the newer member of the H616 family (the Zero 2 has the H616 itself): both are accepted.
  if [[ "$compat" == *allwinner,sun50i-h616* || "$compat" == *allwinner,sun50i-h618* ]]; then
    pass board "Allwinner H616-family SoC (${model:-the board has no model name})"
  else
    fail board "the device tree names no Allwinner H616 or H618 (${compat:-nothing}): not an Orange Pi Zero 3, or the wrong image"
  fi
  cpus="$(grep -c '^processor' "$PROC/cpuinfo" 2>/dev/null || true)"
  a53="$(grep -ciE '^CPU part[[:space:]]*:[[:space:]]*0xd03[[:space:]]*$' "$PROC/cpuinfo" 2>/dev/null || true)"
  if [[ "$cpus" == 4 && "$a53" == 4 ]]; then pass board "4 Cortex-A53 cores"
  else fail board "${cpus:-0} cores running, ${a53:-0} of them Cortex-A53: the Zero 3 has 4 (one that did not start is a board fault)"; fi
}

check_temperature() {
  local z t kind hottest="" soc=""
  for z in "$THERMAL_DIR"/thermal_zone*; do
    t="$(cat "$z/temp" 2>/dev/null)" || continue
    [[ "$t" =~ ^-?[0-9]+$ ]] || continue
    kind="$(cat "$z/type" 2>/dev/null)"
    if [[ -z "$hottest" ]] || (( t > hottest )); then hottest="$t"; fi
    if [[ "$kind" =~ cpu|soc ]] && { [[ -z "$soc" ]] || (( t > soc )); }; then soc="$t"; fi
  done
  t="${soc:-$hottest}"                               # the SoC's own sensor when there is one, else the hottest
  if [[ -z "$t" ]]; then fail temp "no temperature sensor could be read ($THERMAL_DIR)"; return; fi
  if (( t < MAX_TEMP_C * 1000 )); then pass temp "SoC at $(( t / 1000 )) °C (below ${MAX_TEMP_C} °C)"
  else fail temp "SoC at $(( t / 1000 )) °C: ${MAX_TEMP_C} °C or more on the bench means its heat does not get away (heatsink, fan)"; fi
}

check_memory() {
  local kb mb
  kb="$(awk '/^MemTotal:/ {print $2; exit}' "$PROC/meminfo" 2>/dev/null)"
  if [[ ! "$kb" =~ ^[0-9]+$ ]]; then fail memory "the memory size cannot be read ($PROC/meminfo)"; return; fi
  mb=$(( kb / 1024 ))
  if (( mb < MIN_RAM_MB )); then
    fail memory "$mb MB: less than $MIN_RAM_MB MB"
  elif (( mb >= 1280 && mb < 1792 )); then
    # docs/selling.md: not the 1.5 GB board, current kernels crash on it. A 1 GB board shows under 1024 MB, a 2 GB one over 1900.
    fail memory "$mb MB: this is the 1.5 GB Orange Pi Zero 3, which current kernels crash on (use a 1, 2 or 4 GB board)"
  else
    pass memory "$mb MB"
  fi
}

check_storage() {
  local opts avail out
  opts="$(awk '$2 == "/" {o = $4} END {print o}' "$PROC/mounts" 2>/dev/null)"
  if [[ ",$opts," == *,rw,* ]]; then pass storage "the system is mounted read-write"
  else fail storage "the system is not mounted read-write (${opts:-it was not found in $PROC/mounts}): the card is failing"; fi
  avail="$(df -Pk "$R/" 2>/dev/null | awk 'NR==2 {print $4}')"
  if [[ ! "$avail" =~ ^[0-9]+$ ]]; then
    fail storage "the free space on the card cannot be read"
  elif (( avail / 1024 < MIN_FREE_MB )); then
    fail storage "$(( avail / 1024 )) MB free on the card: less than $MIN_FREE_MB MB"
  else
    pass storage "$(( avail / 1024 )) MB free on the card"
  fi
  # 4 MB written, forced onto the card, dropped from memory and read back: a card that loses writes, or a fake one, is caught.
  if out="$(python3 - "$STATE_DIR/.factory-qa-write" <<'PYEOF' 2>&1
import os, sys, time
path = sys.argv[1]
data = os.urandom(4 << 20)
try:
    start = time.monotonic()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)
    took = max(time.monotonic() - start, 0.001)
    fd = os.open(path, os.O_RDONLY)
    try:
        if hasattr(os, "posix_fadvise"):
            os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)        # read it from the card, not from memory
        back = bytearray()
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            back += chunk
    finally:
        os.close(fd)
except OSError as err:
    print("writing to the card failed: %s" % err)
    sys.exit(1)
finally:
    try:
        os.unlink(path)
    except OSError:
        pass
if bytes(back) != data:
    print("4 MB written to the card came back different: the card is failing or is not what it says")
    sys.exit(1)
print("4 MB written to the card and read back unchanged (%.1f MB/s)" % (4 / took))
PYEOF
)"; then pass storage "$out"; else fail storage "$out"; fi
}

check_network() {
  local carrier speed gateway
  IFACE="" IPV4=""
  if ! IFACE="$(pick_iface)"; then fail network "no wired network port was found ($NET_DIR)"; return; fi
  carrier="$(cat "$NET_DIR/$IFACE/carrier" 2>/dev/null || echo 0)"
  if [[ "$carrier" == 1 ]]; then pass network "$IFACE has a link"
  else fail network "$IFACE has no link: is the Ethernet cable plugged in, and the switch on?"; fi
  speed="$(cat "$NET_DIR/$IFACE/speed" 2>/dev/null || true)"
  if [[ "$speed" =~ ^[0-9]+$ ]] && (( speed > 0 )); then
    if (( speed >= MIN_LINK_MBIT )); then pass network "$IFACE at $speed Mbit/s"
    else fail network "$IFACE at only $speed Mbit/s: the port, the cable or the switch is damaged (the Zero 3 does 1000)"; fi
  fi
  IPV4="$(iface_ipv4 "$IFACE")"
  if [[ -n "$IPV4" ]]; then pass network "$IFACE has the address $IPV4 from the router"
  else fail network "$IFACE has no IPv4 address: the router's DHCP did not answer"; fi
  gateway="$(ip -4 route show default 2>/dev/null | awk '{for (i=1;i<NF;i++) if ($i=="via") {print $(i+1); exit}}')"
  if [[ -n "$gateway" ]]; then pass network "default route through $gateway"
  else fail network "no default route: the box cannot reach the internet"; fi
}

check_clock() {
  if [[ "$(timedatectl show -p NTPSynchronized --value 2>/dev/null)" == yes ]]; then pass clock "set from a time server"
  else fail clock "not set from a time server: the board has no clock battery, and bedtime needs the time (the bench network must allow NTP)"; fi
}

check_pihole_service() {
  local v
  if systemctl is-active --quiet pihole-FTL.service; then pass pihole "pihole-FTL is running"
  else fail pihole "pihole-FTL is not running"; fi
  # Pi-hole v6 keeps this in pihole.toml (database.DBinterval, seconds). pihole-FTL.conf and its DBINTERVAL (in minutes) were
  # Pi-hole v5's: v6 moves that file away when it upgrades.
  v="$(pihole-FTL --config database.DBinterval 2>/dev/null | head -n1 | tr -d '[:space:]"')"
  if [[ "$v" =~ ^[0-9]+(\.0+)?$ ]] && (( ${v%%.*} == DBINTERVAL )); then
    pass pihole "database.DBinterval is $DBINTERVAL seconds (pihole.toml)"
  else
    fail pihole "database.DBinterval is '${v:-unreadable}', not $DBINTERVAL (pihole.toml): Pi-hole's settings are not the golden unit's"
  fi
}

# Pi-hole's database, its DNS answers, a real block and unblock of TikTok, and the page: one Python program, with the box
# program's own Pi-hole client (bin/sinko, loaded as a module: its sign-in, its group and list names, its database reader).
# It prints one line per check, "PASS|FAIL|INFO<tab>area<tab>text", and DONE at the end.
pihole_checks() {
  local st area text done=0
  while IFS=$'\t' read -r st area text; do
    case "$st" in
      PASS) pass "$area" "$text" ;;
      FAIL) fail "$area" "$text" ;;
      INFO) info "$area" "$text" ;;
      DONE) done=1 ;;
    esac
  done < <(python3 - "$BIN" "$MODE" "$IPV4" "$WEB_BASE" "$QA_CLIENT" 2>"$RUN_DIR/pihole-checks.err" <<'PYEOF'
import importlib.machinery, importlib.util, json, os, random, re, socket, ssl, struct, sys, time, urllib.error, urllib.request

bin_path, mode, box_ip, web_base, qa_client = sys.argv[1:6]
dns_host, _, dns_port = os.environ.get("SINKO_QA_DNS", "127.0.0.1:53").rpartition(":")
dns_port = int(dns_port)
SETTLE = float(os.environ.get("SINKO_QA_SETTLE", "30"))   # seconds a block or an unblock may take to show in the answers
RESTART_PAUSE = float(os.environ.get("SINKO_QA_RESTART_PAUSE", "2"))   # Pi-hole's restart has begun before it is asked again
UPSTREAM = "github.com"                                   # updates and block lists come from GitHub: it must resolve
RCODES = {0: "NOERROR", 1: "FORMERR", 2: "SERVFAIL", 3: "NXDOMAIN", 4: "NOTIMP", 5: "REFUSED"}


def say(status, area, text):
    print("%s\t%s\t%s" % (status, area, " ".join(str(text).split())), flush=True)


def load_box():
    sys.dont_write_bytecode = True                        # no __pycache__ next to the program on the card
    loader = importlib.machinery.SourceFileLoader("sinko_box", bin_path)
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("sinko_box", loader))
    loader.exec_module(mod)
    return mod


# -- a plain DNS question, the way a phone asks Pi-hole: UDP to port 53, type A, from the address given
def skip_name(data, pos):
    while True:
        length = data[pos]
        if length == 0:
            return pos + 1
        if length & 0xC0 == 0xC0:
            return pos + 2
        pos += 1 + length


def dns_a(name, source="127.0.0.1", timeout=2.0, tries=3):
    """(rcode, [IPv4 addresses]) of Pi-hole's answer; (None, []) when nothing answers."""
    qid = random.randrange(1, 65536)
    packet = struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0)
    for label in name.rstrip(".").split("."):
        packet += bytes([len(label)]) + label.encode("ascii")
    packet += b"\0" + struct.pack(">HH", 1, 1)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind((source, 0))
        sock.settimeout(timeout)
        for _ in range(tries):
            sock.sendto(packet, (dns_host, dns_port))
            try:
                while True:
                    data = sock.recv(4096)
                    if len(data) >= 12 and struct.unpack(">H", data[:2])[0] == qid:
                        return parse_answer(data)
            except socket.timeout:
                continue
    return None, []


def parse_answer(data):
    try:
        _, flags, questions, answers, _, _ = struct.unpack(">HHHHHH", data[:12])
        pos = 12
        for _ in range(questions):
            pos = skip_name(data, pos) + 4
        found = []
        for _ in range(answers):
            pos = skip_name(data, pos)
            rtype, _, _, length = struct.unpack(">HHIH", data[pos:pos + 10])
            pos += 10
            if rtype == 1 and length == 4:
                found.append(socket.inet_ntoa(data[pos:pos + 4]))
            pos += length
        return RCODES.get(flags & 0xF, str(flags & 0xF)), found
    except (IndexError, struct.error):
        return "FORMERR", []


def stopped(rcode, ips):
    """The answer Pi-hole gives for a blocked name, in any of its blocking modes: NXDOMAIN, nothing (NODATA), 0.0.0.0
    (NULL, the default) or the box's own address (IP)."""
    if rcode == "NXDOMAIN":
        return True
    return rcode == "NOERROR" and all(ip == "0.0.0.0" or ip == box_ip or ip.startswith("127.") for ip in ips)


def resolved(rcode, ips):
    return rcode == "NOERROR" and any(ip != "0.0.0.0" and ip != box_ip and not ip.startswith("127.") for ip in ips)


def shown(rcode, ips):
    return "no answer" if rcode is None else "%s %s" % (rcode, " ".join(ips) or "(no address)")


def settle(name, want, source):
    """Ask until the answer is the wanted one (stopped / resolved) or SETTLE seconds have passed: Pi-hole reloads its lists
    after a change, and is restarted to forget what it remembered."""
    deadline = time.monotonic() + SETTLE
    while True:
        rcode, ips = dns_a(name, source)
        good = stopped(rcode, ips) if want == "stopped" else resolved(rcode, ips)
        if good or time.monotonic() >= deadline:
            return good, shown(rcode, ips)
        time.sleep(1)


def wait_for_dns(seconds=60):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if dns_a("pi.hole", timeout=1, tries=1)[0] is not None:
            return True
        time.sleep(1)
    return False


def gravity_checks(box):
    db = box.db_path("SINKO_GRAVITY_DB", "files.gravity", box.GRAVITY_DB)
    if not os.path.isfile(db) or os.path.getsize(db) == 0:
        say("FAIL", "pihole", "Pi-hole's database %s is missing or empty" % db)
        return
    try:
        verdict = [str(next(iter(r.values()), "")) for r in box.sql_rows(db, "PRAGMA quick_check")]
    except box.SqlError as err:
        say("FAIL", "pihole", "Pi-hole's database %s cannot be read: %s" % (db, box.short_text(err, 120)))
        return
    if verdict != ["ok"]:
        say("FAIL", "pihole", "Pi-hole's database %s is damaged: %s" % (db, box.short_text("; ".join(verdict), 120)))
        return
    say("PASS", "pihole", "gravity.db is whole (%s)" % db)
    names = {r.get("name") for r in box.sql_rows(db, 'SELECT name FROM "group"')}
    wanted = [box.G_KIDS, box.G_STATE, box.svc_group("tiktok")]
    missing = [n for n in wanted if n not in names]
    if missing:
        say("FAIL", "pihole", "Sinko's groups are not in gravity.db (missing: %s)" % ", ".join(missing))
    else:
        say("PASS", "pihole", "Sinko's groups are in gravity.db (%s and the others)" % ", ".join(wanted))
    count = box.sql_rows(db, "SELECT COUNT(*) AS n FROM gravity WHERE adlist_id IN (SELECT id FROM adlist WHERE comment = %s)"
                         % box.sql_str(box.LIST_COMMENT_PREFIX + "tiktok"))
    n = int(count[0]["n"]) if count else 0
    if n > 0:
        say("PASS", "pihole", "TikTok's block list is in gravity.db (%d entries)" % n)
    else:
        say("FAIL", "pihole", "TikTok's block list has no entries in gravity.db: the lists were never downloaded (pihole -g)")


def dns_checks(box):
    rcode, ips = dns_a("pi.hole")
    if rcode is None:
        say("FAIL", "dns", "Pi-hole does not answer on %s port %d" % (dns_host, dns_port))
        return False
    if rcode == "NOERROR" and ips:
        say("PASS", "dns", "Pi-hole answers on port %d (pi.hole: %s)" % (dns_port, " ".join(ips)))
    else:
        say("FAIL", "dns", "Pi-hole answers pi.hole with %s" % shown(rcode, ips))
    local = box.read_config().get("SINKO_HOSTNAME", "")
    if local:
        rcode, ips = dns_a(local)
        if box_ip and box_ip in ips:
            say("PASS", "dns", "the page's local name %s points at this box (%s)" % (local, box_ip))
        else:
            say("FAIL", "dns", "the local name %s gives %s, not this box's address %s (the first start sets it)"
                % (local, shown(rcode, ips), box_ip or "(none)"))
    good, answer = settle(UPSTREAM, "resolved", "127.0.0.1")
    if good:
        say("PASS", "dns", "names on the internet resolve through the upstream DNS service (%s: %s)" % (UPSTREAM, answer))
    else:
        say("FAIL", "dns", "%s does not resolve (%s): the box cannot reach its upstream DNS service, and updates and block "
            "lists need it" % (UPSTREAM, answer))
    return True


def retry(call, seconds=60):
    """An API call while Pi-hole may be restarting (the DNS cache is cleared by a restart): tried again for a while."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            return call()
        except Exception:
            if time.monotonic() >= deadline:
                raise
            time.sleep(2)


def blocking_check(box):
    """A real block, the way the page does it: the made-up device joins Sinko's TikTok group, the group is switched on (TikTok
    is blocked), then off again. Every answer comes from Pi-hole on port 53, asked from the device's own address."""
    entries = box.sample_domains("tiktok", 1)
    if not entries:
        say("FAIL", "blocking", "the box has no TikTok list (%s)" % box.LISTS_DIR)
        return
    name, group = box.bare_domain(entries[0]), box.svc_group("tiktok")
    api = box.Api()
    api.wait_ready(60)
    api.login()
    original = None
    client_added = False

    def switch(enabled):
        retry(lambda: api.put_group(group, original["comment"], enabled))
        api.flush_dns()                                   # what the page does after every change: Pi-hole forgets old answers
        time.sleep(RESTART_PAUSE)
        wait_for_dns()
        api.wait_ready(60)
        row = retry(lambda: api.group_map()).get(group) or {}
        return row.get("enabled") is enabled

    try:
        groups = retry(lambda: api.group_map())
        original = groups.get(group)
        if not original:
            say("FAIL", "blocking", "Sinko's group %s is not in Pi-hole" % group)
            return
        if any(c["client"] == qa_client for c in retry(lambda: api.clients())):   # left by a test that was cut off
            retry(lambda: api.request("DELETE", "/api/clients/" + box.Api.q(qa_client)))
        retry(lambda: api.request("POST", "/api/clients", {"client": qa_client, "groups": [original["id"]],
                                                            "comment": "sinko factory test (removed when it ends)"}))
        client_added = True
        if not switch(False):
            say("FAIL", "blocking", "Pi-hole did not keep TikTok allowed when it was asked to")
            return
        good, answer = settle(name, "resolved", qa_client)
        if not good:
            say("FAIL", "blocking", "%s does not resolve even with TikTok allowed (%s): the test cannot show what blocking does "
                "(does the upstream DNS service block it?)" % (name, answer))
            return
        say("PASS", "blocking", "with TikTok allowed, %s resolves for a device (%s)" % (name, answer))
        if switch(True):
            say("PASS", "blocking", "TikTok blocked: %s is switched on in Pi-hole's database (read back through its API)" % group)
        else:
            say("FAIL", "blocking", "Pi-hole did not keep %s switched on" % group)
        good, answer = settle(name, "stopped", qa_client)
        if good:
            say("PASS", "blocking", "TikTok is blocked for that device: %s gives %s" % (name, answer))
        else:
            say("FAIL", "blocking", "TikTok is switched on but %s still resolves for the device (%s)" % (name, answer))
        good, answer = settle(UPSTREAM, "resolved", qa_client)
        if good:
            say("PASS", "blocking", "only TikTok is stopped: %s still resolves for that device" % UPSTREAM)
        else:
            say("FAIL", "blocking", "with TikTok blocked, %s does not resolve for the device either (%s)" % (UPSTREAM, answer))
        if not switch(False):
            say("FAIL", "blocking", "Pi-hole did not switch %s off again" % group)
        good, answer = settle(name, "resolved", qa_client)
        if good:
            say("PASS", "blocking", "TikTok allowed again: %s resolves (%s)" % (name, answer))
        else:
            say("FAIL", "blocking", "TikTok was switched off again but %s is still stopped for the device (%s)" % (name, answer))
    finally:
        # The box goes back to what it was: the group as it was found, no made-up device. (On a box that passes, the seal
        # then starts Sinko's objects again from nothing anyway.)
        try:
            if original is not None:
                now = retry(lambda: api.group_map()).get(group) or {}
                if now.get("enabled") is not original["enabled"]:
                    retry(lambda: api.put_group(group, original["comment"], original["enabled"]))
            if client_added:
                retry(lambda: api.request("DELETE", "/api/clients/" + box.Api.q(qa_client)))
            api.flush_dns()
        except Exception as err:                          # noqa: BLE001
            say("FAIL", "blocking", "the test device or the TikTok switch could not be put back: %s" % box.short_text(err, 120))
        try:
            api.logout()
        except Exception:                                 # noqa: BLE001
            pass


def fetch(url):
    """(HTTP status, body); (None, b"") when nothing answers."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False                            # Pi-hole's own certificate, on this very box
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(url, timeout=10, context=ctx) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, b""
    except (urllib.error.URLError, OSError):
        return None, b""


def page_checks(box):
    status, body = fetch(web_base + "/")
    stamp = '<meta name="sinko-version" content="%s">' % box.VERSION
    if status == 200 and stamp.encode() in body:
        say("PASS", "page", "the parent page is served at %s/ (Sinko %s)" % (web_base, box.VERSION))
    else:
        say("FAIL", "page", "the parent page is not served at %s/ as Sinko %s (HTTP %s)" % (web_base, box.VERSION, status))
    status, body = fetch(web_base + "/pb/box.json")
    try:
        info = json.loads(body.decode("utf-8")) if status == 200 else None
    except ValueError:
        info = None
    if not isinstance(info, dict):
        say("FAIL", "page", "/pb/box.json is not served (HTTP %s): the app could not find this box" % status)
        return
    problems = []
    if info.get("version") != box.VERSION:
        problems.append("version %r" % info.get("version"))
    if not re.fullmatch(r"[0-9a-f]{32}", str(info.get("boxId") or "")):
        problems.append("no box id")
    if box_ip and info.get("ip") != box_ip:
        problems.append("address %r, not %s" % (info.get("ip"), box_ip))
    if problems:
        say("FAIL", "page", "/pb/box.json is wrong: %s" % ", ".join(problems))
    else:
        say("PASS", "page", "/pb/box.json names this box (Sinko %s, its own box id, %s)" % (box.VERSION, box_ip))


box = load_box()
answers = True
for area, check in (("pihole", gravity_checks), ("dns", dns_checks), ("blocking", blocking_check), ("page", page_checks)):
    if check is blocking_check and not answers:
        say("FAIL", "blocking", "not tested: Pi-hole does not answer DNS questions")
        continue
    try:
        if check(box) is False:
            answers = False
    except Exception as err:                              # noqa: BLE001 - a check that cannot run fails, with its reason
        say("FAIL", area, "could not be tested: %s" % box.short_text(err, 160))
print("DONE", flush=True)
PYEOF
)
  if (( ! done )); then
    fail pihole "the checks of Pi-hole, DNS, blocking and the page stopped: $(tail -n 1 "$RUN_DIR/pihole-checks.err" 2>/dev/null)"
    add_details "the Pi-hole checks" "$(tail -n 20 "$RUN_DIR/pihole-checks.err" 2>/dev/null)"
  fi
}

check_sinko() {
  local out rc=0 link="$R/usr/local/bin/sinko"
  out="$("$BIN" selfcheck --wait "$SELFCHECK_WAIT" 2>&1)" || rc=$?
  if (( rc == 0 )); then
    pass sinko "sinko selfcheck: every check ok"
  else
    fail sinko "sinko selfcheck: $(grep -m1 'FAIL' <<<"$out" | sed 's/^ *FAIL *//')"
    add_details "sinko selfcheck" "$out"
  fi
  if [[ -L "$link" && "$(readlink -f "$link")" == "$(readlink -f "$BIN")" ]] && "$link" --help >/dev/null 2>&1; then
    pass sinko "the sinko command works (/usr/local/bin/sinko)"
  else
    fail sinko "/usr/local/bin/sinko is not a working link to $BIN"
  fi
  rc=0
  "$BIN" password-state >/dev/null 2>&1 || rc=$?
  if (( rc == 3 )); then
    pass sinko "no password is set: the customer gets the welcome screen and chooses one"
  elif (( rc == 0 )) && [[ "$MODE" == check ]]; then
    info sinko "a password is set (the seal removes it)"
  elif (( rc == 0 )); then
    fail sinko "a password is set: the customer could not claim this box (the image was not sealed)"
  else
    fail sinko "Pi-hole cannot say whether a password is set (sinko password-state ended with $rc)"
  fi
  if [[ "$MODE" == factory ]]; then
    if [[ -e "$STATE_DIR/firstboot" ]]; then
      fail sinko "the first start has not finished (sinko-firstboot keeps its flag while the address or Pi-hole's HTTPS key is missing)"
    else
      pass sinko "the first start finished: this box made its own keys, name, id and address"
    fi
  fi
}

# Tailscale is not part of Sinko. When the golden unit had it, every box must have it too, and none may be logged in: a box
# that is would share one Tailscale identity with every other box from the image, and its tailnet would reach into the
# customer's home network.
check_tailscale() {
  local had state
  had="$(flag_value tailscale)"
  if ! command -v tailscale >/dev/null; then
    if [[ "$had" == 1 ]]; then fail tailscale "not installed, but the golden unit had it"
    else info tailscale "not installed (it is not part of Sinko)"; fi
    return
  fi
  state="$(tailscale status --json 2>/dev/null | python3 -c 'import json, sys; print(json.load(sys.stdin).get("BackendState", ""))' 2>/dev/null)"
  case "$state" in
    NeedsLogin|NoState) pass tailscale "installed, not logged in: READY FOR FIRST-TIME USER AUTH" ;;
    "") fail tailscale "installed, but tailscaled does not answer (systemctl status tailscaled)" ;;
    *) fail tailscale "logged in ($state): every box from this image would share it, and its tailnet would reach into the customer's home. Log the golden unit out (tailscale logout) and make the image again" ;;
  esac
}

run_tests() {
  check_lights
  check_board
  check_temperature
  check_memory
  check_storage
  check_network
  check_clock
  check_pihole_service
  pihole_checks
  check_sinko
  check_tailscale
}

# ------------------------------------------------------------------ the two endings of a factory test
TESTING_PID=""
VERDICT=""
stop_testing_lights() {
  if [[ -n "$TESTING_PID" ]]; then
    kill "$TESTING_PID" 2>/dev/null
    wait "$TESTING_PID" 2>/dev/null
    TESTING_PID=""
  fi
}

webroot() {
  local w
  w="$(pihole-FTL --config webserver.paths.webroot 2>/dev/null | head -n1 | tr -d '"')"
  [[ "$w" == /* && "$w" != *..* ]] || w="$R/var/www/html"
  printf '%s' "$w"
}

write_report() {
  local r st area text web
  install -d -m 700 "$(dirname "$REPORT")"
  {
    echo "Sinko factory test: FAILED"
    echo
    echo "When:     $(date '+%Y-%m-%d %H:%M:%S %Z')"
    echo "Sinko:    $(cat "$APP_DIR/VERSION" 2>/dev/null || echo unknown)$( [[ -n "$(flag_value made)" ]] && echo " (image made on $(flag_value made))")"
    echo "Board:    $(tr -d '\0' <"$PROC/device-tree/model" 2>/dev/null || echo unknown)"
    echo "Network:  ${IPV4:-no address} on ${IFACE:-no port}"
    echo
    echo "What failed:"
    for r in "${RESULTS[@]}"; do
      IFS='|' read -r st area text <<<"$r"
      if [[ "$st" == FAIL ]]; then printf '  %-9s %s\n' "$area" "$text"; fi
    done
    echo
    echo "Every check:"
    for r in "${RESULTS[@]}"; do
      IFS='|' read -r st area text <<<"$r"
      printf '  %-4s  %-9s %s\n' "$st" "$area" "$text"
    done
    if [[ -n "$DETAILS" ]]; then echo; echo "Details:"; printf '%s\n' "$DETAILS"; fi
    echo
    echo "The test runs again at every start until it passes: fix the cause (the cable, the network), then switch the box off"
    echo "and on. A box that fails again on a good network is re-flashed; a board that fails on a freshly flashed card is set aside."
  } >"$REPORT.tmp" && chmod 600 "$REPORT.tmp" && mv -f "$REPORT.tmp" "$REPORT"
  # The same text where a technician on the bench network can read it: http://<the box's address>/pb/factory-qa.txt
  web="$(webroot)"
  if [[ -d "$web/pb" ]]; then install -m 644 "$REPORT" "$web/pb/factory-qa.txt" 2>/dev/null || true; fi
}

start_sos() {
  if (( ${#LEDS[@]} == 0 )); then log "there is no light to show SOS on"; return 0; fi
  # A unit of its own, so that this test ends as failed (systemctl --failed shows it) while the lights go on.
  if systemd-run --quiet --collect --unit="$SOS_UNIT" --description="Sinko factory test failed: SOS on the lights" \
       "$SELF" --sos >/dev/null 2>&1; then
    log "the lights show SOS until the box is unplugged"
    return 0
  fi
  log "the SOS could not be started as a unit of its own: shown from here, until the box is unplugged"
  led_sos_forever
}

verdict_failed() {
  VERDICT=failed
  stop_testing_lights
  write_report
  log "FAILED: $FAILS check(s) failed; the report is in $REPORT. The test runs again at the next start."
  start_sos
  exit 1
}

# What a box that passed still has to do. The flag goes as soon as the box is sealed: a box that loses power after that is
# ready for its customer, and must not test (and switch itself off) again at the customer's.
seal_for_customer() {
  local name rc=0 opts=(--yes --no-zerofill)
  name="$(flag_value hostname)"
  [[ "$name" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$ ]] || name=sinko
  opts+=(--hostname "$name")
  if [[ "$(flag_value keep_ssh)" == 1 ]]; then opts+=(--keep-ssh-access); fi
  # No zero-fill: the golden unit's image was zero-filled, and what this start wrote and the seal now deletes (the test's own
  # questions, this start's keys and ids) is nobody's private data. Writing the whole free card would take many minutes.
  log "every check passed: sealing this box for its customer (seal.sh ${opts[*]})"
  "$SEAL" "${opts[@]}" >"$RUN_DIR/seal.log" 2>&1 || rc=$?
  if (( rc != 0 )); then
    fail seal "tools/seal.sh stopped (status $rc): $(grep -m1 '^seal: ' "$RUN_DIR/seal.log" | cut -c7-)"
    add_details "tools/seal.sh" "$(tail -n 40 "$RUN_DIR/seal.log")"
    return 1
  fi
  pass seal "sealed: no password, no logs or history of this test, its own keys and ids made again at the customer's first start"
  if command -v tailscale >/dev/null || [[ -d "$R/var/lib/tailscale" ]]; then
    systemctl stop tailscaled.service >/dev/null 2>&1 || true
    if rm -f "$R/var/lib/tailscale/tailscaled.state" "$R/var/lib/tailscale/tailscaled.log.conf" "$R"/var/lib/tailscale/tailscaled.log*.txt; then
      pass seal "Tailscale's identity removed: the box makes its own when it first starts for the customer"
    else
      fail seal "Tailscale's identity in /var/lib/tailscale could not be removed"
      return 1
    fi
  fi
  return 0
}

# Armbian saves the lights' state when it shuts down (armbian-led-state.service writes /etc/armbian-leds.conf) and restores it at
# every start: the customer's box would start with every light on. It is stopped now, which saves it one last time, and the
# file the box started with is put back (or removed, when it had none).
keep_armbian_lights() {
  systemctl is-active --quiet armbian-led-state.service 2>/dev/null || return 0
  systemctl stop armbian-led-state.service >/dev/null 2>&1 || true
  if [[ -f "$RUN_DIR/armbian-leds.conf" ]]; then cp -p "$RUN_DIR/armbian-leds.conf" "$ARMBIAN_LEDS"; else rm -f "$ARMBIAN_LEDS"; fi
}

verdict_passed() {
  VERDICT=passed
  rm -f "$FLAG" "$REPORT" "$(webroot)/pb/factory-qa.txt"
  systemctl disable "$UNIT" >/dev/null 2>&1 || true
  rm -f "$UNIT_FILE"
  # No `systemctl daemon-reload` after this: this script runs AS that unit, and a reload that no longer finds its file makes systemd
  # forget the unit's TimeoutStartSec=infinity. Its default, 90 s counted from the unit's start, then kills a run that took longer
  # than that (SIGTERM, exit 143) before the lights and the power-off: found on a real Orange Pi Zero 3, where waiting for the
  # network made a run take 88 s. The unit is gone at the next start anyway, and the power-off is next.
  stop_testing_lights
  led_victory_dance
  led_all 1                                          # every light stays on until the power is cut: then it is safe to unplug
  keep_armbian_lights
  rm -rf "$RUN_DIR"
  log "PASSED and sealed: switching off. Unplug the box when every light is off."
  sync
  systemctl poweroff
  exit 0
}

# A test that ends without a verdict (a bug, a command that was not there) must not leave the lights doing nothing.
# shellcheck disable=SC2329  # the two are called by trap
on_exit() {
  [[ -z "$VERDICT" ]] || return 0
  fail qa "the factory test itself stopped before it finished (see journalctl -u $UNIT)"
  verdict_failed
}
# shellcheck disable=SC2329
on_term() { VERDICT=stopped; stop_testing_lights; led_restore; exit 143; }

# ------------------------------------------------------------------ run
install -d -m 700 "$RUN_DIR"
led_detect
case "$MODE" in
  sos)
    led_sos_forever
    exit 0 ;;
  leds)
    (( ${#LEDS[@]} )) || die "no light was found on this board ($LED_DIR)"
    led_save
    trap led_restore EXIT
    echo "Lights: ${LEDS[*]}"
    echo "Testing (8 seconds): a slow double beat, one light after the other"
    led_testing & TESTING_PID=$!
    pause 8
    stop_testing_lights
    echo "Passed: a fast chase for 8 seconds, then five flashes"
    led_victory_dance
    echo "Failed: SOS (two rounds here; a box that failed repeats it until it is unplugged)"
    led_manual; led_sos_once; led_sos_once
    echo "The lights are back as they were."
    exit 0 ;;
  check)
    WEB_BASE="$(web_base)"
    echo "Factory checks of this box (Sinko $(cat "$APP_DIR/VERSION" 2>/dev/null)), without the seal:"
    run_tests
    if (( FAILS )); then echo "$FAILS check(s) failed."; exit 1; fi
    echo "Every check passed."
    exit 0 ;;
esac

# factory
led_save
if [[ -f "$ARMBIAN_LEDS" ]]; then cp -p "$ARMBIAN_LEDS" "$RUN_DIR/armbian-leds.conf"; fi
led_testing & TESTING_PID=$!
trap on_exit EXIT
trap on_term TERM INT
WEB_BASE="$(web_base)"
log "factory test of this box (Sinko $(cat "$APP_DIR/VERSION" 2>/dev/null), image made on $(flag_value made)): the lights beat slowly while it runs"
wait_until_ready
finish_first_start
run_tests
if (( FAILS )); then verdict_failed; fi
seal_for_customer || verdict_failed
verdict_passed
