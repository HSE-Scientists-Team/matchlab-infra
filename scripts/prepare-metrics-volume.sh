#!/usr/bin/env bash
# Create a fixed-size filesystem image on the storage node. Existing data is never formatted.
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Run as root' >&2; exit 1; }
[[ $# == 0 ]] || { echo 'This script accepts no arguments' >&2; exit 1; }
image_dir=/var/lib/matchlab-storage
image_file=$image_dir/metrics.ext4
mount_dir=/var/lib/matchlab-metrics
size=$((10 * 1024 * 1024 * 1024))
mkdir -p "$image_dir" "$mount_dir"
chmod 0700 "$image_dir"
if [[ ! -e "$image_file" ]]; then
  available=$(df --output=avail -B1 "$image_dir" | tail -1 | tr -d ' ')
  (( available >= size + 10 * 1024 * 1024 * 1024 )) || { echo 'Need 20 GiB free: 10 GiB volume plus 10 GiB remaining reserve' >&2; exit 1; }
  # Preallocate all space and use noclobber to refuse overwriting a concurrent file.
  (set -o noclobber; : > "$image_file")
  chmod 0600 "$image_file"
  fallocate -l "$size" "$image_file"
  mkfs.ext4 -E nodiscard -F -m 1 -L matchlab-metrics "$image_file"
fi
[[ -f "$image_file" && ! -L "$image_file" ]] || { echo 'Expected a regular image file' >&2; exit 1; }
[[ $(stat -c %s "$image_file") == "$size" ]] || { echo 'Existing image has unexpected size; refusing to modify it' >&2; exit 1; }
[[ $(blkid -p -s TYPE -o value "$image_file") == ext4 ]] || { echo 'Existing image is not ext4; refusing to format it' >&2; exit 1; }
# mkfs on some systems may punch holes; reserve missing blocks also on repeated runs.
allocated=$(( $(stat -c %b "$image_file") * 512 ))
if (( allocated < size )); then
  available=$(df --output=avail -B1 "$image_dir" | tail -1 | tr -d ' ')
  (( available >= size - allocated + 10 * 1024 * 1024 * 1024 )) || { echo 'Insufficient free space to preallocate existing volume safely' >&2; exit 1; }
  fallocate -l "$size" "$image_file"
fi
uuid=$(blkid -p -s UUID -o value "$image_file")
if mountpoint -q "$mount_dir"; then
  [[ $(findmnt -n -o UUID --target "$mount_dir") == "$uuid" ]] || { echo 'Another filesystem is mounted at target' >&2; exit 1; }
else
  [[ -z $(find "$mount_dir" -mindepth 1 -maxdepth 1 -print -quit) ]] || { echo 'Mount target is not empty' >&2; exit 1; }
  mount -o loop,nodev,nosuid,noexec "$image_file" "$mount_dir"
fi
entry="$image_file $mount_dir ext4 loop,defaults,nodev,nosuid,noexec 0 0"
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
printf 'Volume prepared. Label the verified storage node matchlab.io/metrics-disk=ready.\n'
