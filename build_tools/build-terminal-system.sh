#!/usr/bin/env bash
# Build release inputs only. The release environment owns signing and publication.
set -euo pipefail

terminal=$1
cache=$2
work=$3
checkout=$(cd "$(dirname "$0")/.." && pwd)
cd "$checkout"
mkdir "$work"
mkdir "$work/tmp" "$work/artifacts"
export TMPDIR="$work/tmp"
export PYTHONDONTWRITEBYTECODE=1

pick() {
    python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$1" "$2"
}
digest() {
    sha256sum "$1" | cut -d ' ' -f 1
}
builder() {
    python3 -m zmala_images "$@"
}
show_failure() {
    local result=$?
    if (( result != 0 )); then
        for log in "$work"/{root,application,loader,initramfs,image}/build.log; do
            if [[ -f "$log" ]]; then
                printf '\n%s\n' "$log"
                tail -30 "$log"
            fi
        done
    fi
    exit "$result"
}
trap show_failure EXIT

git -C "$terminal" diff --quiet HEAD --
terminal_commit=$(git -C "$terminal" rev-parse HEAD)
terminal_version=$(pick "$terminal/VERSION.json" version)
[[ $terminal_version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
package="$work/packages/ZmalaTerminal-$terminal_version-linux-arm64.tar.gz"
python3 "$terminal/build_tools/linux/package-terminal.py" --output "$package"
python3 - "$work/components.lock.json" "$terminal_version" "$terminal_commit" "$(digest "$package")" <<'PY'
import json
from pathlib import Path
import sys

output, version, commit, digest = sys.argv[1:]
lock = json.loads(Path('components.lock.json').read_text())
lock['components']['terminal'] = {'version': version, 'commit': commit, 'sha256': digest}
Path(output).write_text(json.dumps(lock, indent=2)+'\n')
PY

builder application-inputs terminal --packages "$work/packages" \
    --components-lock "$work/components.lock.json" --output "$work/inputs"
builder build-root terminal --base-cache "$cache/base" --role-cache "$cache/terminal" --output "$work/root"
builder provision-applications terminal --source "$work/root/root.tar" \
    --expected-root-sha256 "$(pick "$work/root/READY.json" root_tar_sha256)" \
    --applications "$work/inputs/applications.tar" \
    --expected-applications-sha256 "$(pick "$work/inputs/READY.json" applications_sha256)" \
    --base-cache "$cache/base" --role-cache "$cache/terminal" --output "$work/application"
builder prepare-root terminal --source "$work/application/root.tar" \
    --expected-root-sha256 "$(pick "$work/application/READY.json" root_tar_sha256)" \
    --base-cache "$cache/base" --role-cache "$cache/terminal" --output "$work/prepared"
prepared=$(pick "$work/prepared/READY.json" root_tar_sha256)
builder build-initramfs terminal --source "$work/prepared/root.tar" --expected-root-sha256 "$prepared" \
    --base-cache "$cache/base" --role-cache "$cache/terminal" --output "$work/initramfs"
builder build-loader --output "$work/loader"
builder assemble-image terminal --source "$work/prepared/root.tar" --expected-root-sha256 "$prepared" \
    --base-cache "$cache/base" --role-cache "$cache/terminal" --output "$work/image" \
    --initramfs "$work/initramfs" --initramfs-manifest-sha256 "$(digest "$work/initramfs/READY.json")" \
    --loader "$work/loader" --loader-manifest-sha256 "$(digest "$work/loader/READY.json")"
python3 -m zmala_images.system_bundle --image "$work/image" \
    --manifest-sha256 "$(digest "$work/image/READY.json")" --output "$work/system-inputs"
cp "$work/image/READY.json" "$work/artifacts/READY.json"
for slot in A B; do
    archive="$work/artifacts/$slot.tar.zst"
    tar --sparse -I 'zstd -T4 -6' -cf "$archive" -C "$work/system-inputs/$slot" manifest.raucm boot.vfat root.ext4
    zstd --test "$archive"
    test "$(stat -c %s "$archive")" -lt 2147483648
done
(cd "$work/artifacts"; sha256sum A.tar.zst B.tar.zst > SHA256SUMS)
