#!/usr/bin/env bash
# Turn a finished golden unit into the master image of a batch of ready-made boxes: test it, seal it, arm the factory test,
# and print the commands that copy its card to an image. Run it once, on the golden unit, after Sinko is installed and works
# (docs/product-image.md, section 1), from the console or from an SSH session that you keep open until it has finished:
#
#   sudo /opt/sinko/tools/prepare-golden-master.sh --dry-run    tests the unit and shows the plan; changes nothing
#   sudo /opt/sinko/tools/prepare-golden-master.sh              the same, then the seal asks you to type SEAL
#
# What it does, in this order:
#   1. the factory test's own checks, on this unit (tools/factory-qa.sh --check), the board's lights among them: a golden unit
#      that fails them makes a batch of boxes that all fail. When one fails, nothing is changed
#   2. the seal (tools/seal.sh): everything that must be unique to each box or private to you goes, and root is locked
#   3. the factory test is armed: its flag (/var/lib/sinko/factory-qa) and sinko-factory-qa.service, enabled. Every card
#      flashed from this image tests itself at its first start, and seals itself and switches off when it passes
#   4. the commands that copy this card to an image, with the card's size
#
# Options:
#   --hostname NAME     the name of every box (http://NAME.local/ opens the page; default sinko)
#   --dry-run           step 1 and the seal's plan only
#   --yes               do not ask for SEAL
#   --no-zerofill       a test image only: the seal's option (what was deleted could still be read from the image)
#   --keep-ssh-access   a test image only: the seal leaves root and SSH logins alone, here and on every box that passes
set -Eeuo pipefail

R="${SINKO_ROOT:-}"                                  # test hook: act on a fake root
[[ -z "$R" || "$R" == /* ]] || { echo "prepare-golden-master: SINKO_ROOT must be an absolute path" >&2; exit 2; }
STATE_DIR="${SINKO_STATE_DIR:-$R/var/lib/sinko}"
FLAG="$STATE_DIR/factory-qa"
APP_DIR="$R/opt/sinko"
QA="$APP_DIR/tools/factory-qa.sh"
SEAL="$APP_DIR/tools/seal.sh"
UNIT=sinko-factory-qa.service
UNIT_DIR="$R/etc/systemd/system"

YES=0 DRY=0 ZEROFILL=1 KEEP_SSH=0 NAME=sinko

die() { printf 'prepare-golden-master: %s\n' "$*" >&2; exit 1; }
trap 'printf "prepare-golden-master: stopped because a command failed (line %s). Fix the problem and run it again.\n" "$LINENO" >&2' ERR
usage() { sed -n '2,/^set -Eeuo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; }

while (( $# )); do
  case "$1" in
    --yes) YES=1 ;;
    --dry-run) DRY=1 ;;
    --no-zerofill) ZEROFILL=0 ;;
    --keep-ssh-access) KEEP_SSH=1 ;;
    --hostname)
      (( $# >= 2 )) || die "--hostname needs a name"
      NAME="$2"; shift ;;
    --hostname=*) NAME="${1#--hostname=}" ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'prepare-golden-master: unknown option %s\n\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done
NAME="${NAME,,}"
[[ "$NAME" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$ ]] \
  || die "'$NAME' is not a usable host name: use letters, digits and hyphens only (one word, at most 63 characters), such as sinko"

[[ "$(id -u)" -eq 0 ]] || die "run as root: sudo $0"
[[ -x "$QA" && -x "$SEAL" && -f "$UNIT_DIR/$UNIT" ]] \
  || die "this Sinko has no factory test ($QA, $SEAL and $UNIT_DIR/$UNIT). Install a release that has one, then run this again."
VERSION="$(tr -d '[:space:]' <"$APP_DIR/VERSION" 2>/dev/null || true)"
VERSION="${VERSION:-unknown}"

# The disk the system runs from (the microSD card on an Orange Pi): "name bytes", or nothing when it cannot be told.
root_disk() {
  local majmin dev disk sectors
  majmin="$( { findmnt -n -o MAJ:MIN / 2>/dev/null || true; } | head -n1 | tr -d '[:space:]')"
  [[ "$majmin" =~ ^[0-9]+:[0-9]+$ ]] || return 0
  dev="$(readlink -f "$R/sys/dev/block/$majmin" 2>/dev/null || true)"
  [[ -n "$dev" && -d "$dev" ]] || return 0
  if [[ -e "$dev/partition" ]]; then disk="$(dirname "$dev")"; else disk="$dev"; fi
  sectors="$(cat "$disk/size" 2>/dev/null || true)"
  if [[ "$sectors" =~ ^[0-9]+$ ]] && (( sectors > 0 )); then printf '%s %s\n' "${disk##*/}" "$(( sectors * 512 ))"; fi
}

print_imaging() {
  local file="sinko-$VERSION-orangepizero3.img" found disk="" bytes="" size=""
  found="$(root_disk)"
  if [[ -n "$found" ]]; then
    read -r disk bytes <<<"$found"
    size="$(awk -v b="$bytes" 'BEGIN { printf "%.1f GB", b / 1e9 }')"
  fi
  cat <<EOF

1. Switch this unit off now, from this session:   unset HISTFILE; poweroff
   Do not start it again before its card is copied: the next start runs the factory test, which seals the card for a
   customer and switches the unit off.

2. On a Linux computer, put the card in a card reader and find it${bytes:+. It is the disk of $size ($bytes bytes, the number that lsblk -b shows)}:
     lsblk -b -d -o NAME,SIZE,MODEL,TRAN

3. Copy the card to an image. Replace sdX with the name you found, and check it twice: dd overwrites a disk without asking.
     sudo dd if=/dev/sdX of=$file bs=4M status=progress conv=fsync
     xz -T0 -9 $file
     sha256sum $file.xz > $file.xz.sha256
   On a Mac: find the card with  diskutil list  (/dev/diskN), then  diskutil unmountDisk /dev/diskN  and
     sudo dd if=/dev/rdiskN of=$file bs=4m

4. Flash every card from the image: balenaEtcher (it checks what it wrote), or on Linux
     xzcat $file.xz | sudo dd of=/dev/sdX bs=4M conv=fsync status=progress
   Every card must be at least as big as this one${bytes:+ ($bytes bytes)}: use the same size class, or a bigger one.

5. Every box: Ethernet first, then power, and watch its lights (docs/factory-qa.md). A box that passes switches itself off,
   sealed for its customer. Keep this image for the factory: every card flashed from it tests itself at its first start.
   For a customer's re-flash, copy a card that has passed the test instead.
EOF
  if [[ -n "$bytes" ]] && (( bytes > 17000000000 )); then
    printf '\nThis card holds %s: the image is that big, and so must be every card you ship. A small card (8 GB) for the\ngolden unit makes a small image (docs/product-image.md, "How big the card is").\n' "$size"
  fi
  if [[ -z "$disk" ]]; then
    printf '\n(The card this unit runs from could not be found, so its size is not shown: copy the whole card.)\n'
  fi
}

# ------------------------------------------------------------------ 1. the factory checks, on this unit
printf '==> 1. The factory test'"'"'s checks, on this unit (tools/factory-qa.sh --check)\n\n'
if ! "$QA" --check; then
  die "this unit does not pass the factory test's checks (above), and every box made from it would fail them too. Nothing was changed: fix it, then run this again."
fi
TAILSCALE=0
if command -v tailscale >/dev/null; then TAILSCALE=1; fi

# ------------------------------------------------------------------ 2. the seal
SEAL_OPTS=(--hostname "$NAME")
if (( YES )); then SEAL_OPTS+=(--yes); fi
if (( DRY )); then SEAL_OPTS+=(--dry-run); fi
if (( ! ZEROFILL )); then SEAL_OPTS+=(--no-zerofill); fi
if (( KEEP_SSH )); then SEAL_OPTS+=(--keep-ssh-access); fi
printf '\n==> 2. The seal (tools/seal.sh %s)\n' "${SEAL_OPTS[*]}"
if ! "$SEAL" "${SEAL_OPTS[@]}"; then
  die "the seal did not finish (above), so the factory test was not armed. Fix the problem and run this again."
fi

if (( DRY )); then
  cat <<EOF

==> 3. Arming the factory test (not done in a dry run)
   It would write $FLAG (hostname=$NAME, tailscale=$TAILSCALE, keep_ssh=$KEEP_SSH and today's date) and enable $UNIT.

==> 4. Copying the card (what will be printed at the end)
EOF
  print_imaging
  printf '\nDry run: nothing was changed.\n'
  exit 0
fi

# ------------------------------------------------------------------ 3. arm the factory test
# After the seal, so that nothing is armed on a unit the seal stopped on. What the flag says is what every box is held to.
printf '\n==> 3. Arming the factory test\n'
install -d -m 700 "$STATE_DIR"
( umask 077; printf 'hostname=%s\ntailscale=%s\nkeep_ssh=%s\nmade=%s\n' "$NAME" "$TAILSCALE" "$KEEP_SSH" "$(date +%Y-%m-%d)" >"$FLAG.tmp" )
mv -f "$FLAG.tmp" "$FLAG"
systemctl daemon-reload
systemctl enable "$UNIT" >/dev/null 2>&1 || die "could not enable $UNIT: the unit is sealed, but its boxes would not test themselves. Run: systemctl enable $UNIT"
systemctl is-enabled --quiet "$UNIT" || die "$UNIT is not enabled: run  systemctl enable $UNIT"
printf '  armed: %s and %s\n' "$FLAG" "$UNIT"

# ------------------------------------------------------------------ 4. how to copy the card
printf '\n==> 4. Copying the card\n'
print_imaging
if (( KEEP_SSH )); then
  printf '\nWARNING: --keep-ssh-access: root and SSH logins stay open on this unit and on every box that passes. A test image only.\n'
fi
if (( ! ZEROFILL )); then
  printf '\nWARNING: --no-zerofill: what was deleted from this unit can still be read from the image. A test image only.\n'
fi
