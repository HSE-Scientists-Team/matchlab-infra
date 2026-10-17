#!/usr/bin/env bash
# Prepare a dedicated, <=10 GiB filesystem for the static Prometheus local PV.
# Run on the storage node as root. Never reuse a disk containing data.
set -euo pipefail
if [[ $EUID != 0 || $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: sudo $0 /dev/disk/by-id/DEVICE [--format-blank]" >&2; exit 1
fi
device=$(readlink -f -- "$1")
mode=${2:-}
[[ -z "$mode" || "$mode" == --format-blank ]] || { echo 'Unknown argument' >&2; exit 1; }
[[ -b "$device" ]] || { echo 'Not a block device' >&2; exit 1; }
bytes=$(blockdev --getsize64 "$device")
(( bytes >= 9 * 1024 * 1024 * 1024 && bytes <= 10 * 1024 * 1024 * 1024 )) || { echo 'Device must be 9–10 GiB' >&2; exit 1; }
mount_dir=/var/lib/matchlab-metrics
if [[ "$mode" == --format-blank ]]; then
  # Any signature, child partition, swap or mount rejects formatting.
  [[ $(lsblk -nr -o NAME "$device" | wc -l) -eq 1 ]] || { echo 'Device has partitions' >&2; exit 1; }
  [[ -z $(lsblk -nr -o MOUNTPOINTS "$device" | tr -d '[:space:]') ]] || { echo 'Device is in use' >&2; exit 1; }
  [[ -z $(wipefs --no-act --noheadings --output TYPE "$device") ]] || { echo 'Device has a filesystem/signature; refusing to format' >&2; exit 1; }
  mkfs.ext4 -m 1 -L matchlab-metrics "$device"
fi
[[ $(blkid -s TYPE -o value "$device") == ext4 ]] || { echo 'Expected ext4; use --format-blank only for a new empty disk' >&2; exit 1; }
uuid=$(blkid -s UUID -o value "$device")
mkdir -p "$mount_dir"
if mountpoint -q "$mount_dir"; then
  [[ $(findmnt -n -o UUID --target "$mount_dir") == "$uuid" ]] || { echo 'Another filesystem mounted at target' >&2; exit 1; }
else
  [[ -z $(find "$mount_dir" -mindepth 1 -maxdepth 1 -print -quit) ]] || { echo 'Mount target is not empty' >&2; exit 1; }
  [[ -z $(findmnt -rn -S "UUID=$uuid" -o TARGET) ]] || { echo 'Device is mounted elsewhere' >&2; exit 1; }
  mount -t ext4 "UUID=$uuid" "$mount_dir"
fi
# Refuse conflicting fstab entries instead of overwriting system configuration.
entry="UUID=$uuid $mount_dir ext4 defaults,nodev,nosuid,noexec 0 2"
if awk -v target="$mount_dir" '$1 !~ /^#/ && $2 == target {found=1} END {exit !found}' /etc/fstab; then
  grep -Fxq "$entry" /etc/fstab || { echo 'Conflicting fstab entry; inspect manually' >&2; exit 1; }
else
  printf '\n%s\n' "$entry" >> /etc/fstab
fi
chown 65534:65534 "$mount_dir"
chmod 0750 "$mount_dir"
mkdir -p /etc/systemd/system/k3s.service.d
printf '[Unit]\nRequiresMountsFor=%s\n' "$mount_dir" > /etc/systemd/system/k3s.service.d/metrics-disk.conf
systemctl daemon-reload
findmnt --target "$mount_dir" --output SOURCE,TARGET,FSTYPE,SIZE
printf 'Disk prepared. After verifying the mount, label this node matchlab.io/metrics-disk=ready.\n'
