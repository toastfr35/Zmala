#!/bin/sh
# Offline target-root mkinitramfs hook. Never installed by the legacy installers.
set -eu

case "${1:-}" in
    prereqs) exit 0 ;;
esac

. /usr/share/initramfs-tools/hook-functions

stdlib=/usr/lib/python3.13
runtime=/usr/lib/python3/dist-packages/zmala_system
test -d "$stdlib" && test ! -L "$stdlib"
test -d "$runtime" && test ! -L "$runtime"
test -f /usr/lib/zmala/role && test ! -L /usr/lib/zmala/role

# Use the locked target's interpreter and dependencies, never the build host's
# Python or arbitrary site packages. Copy extension dependencies as well as the
# interpreter's ELF closure; merely copying lib-dynload would miss dlopen libs.
bytes=$(du -s -B1 --apparent-size "$stdlib" | cut -f1)
test "$bytes" -le 67108864
count=$(find "$stdlib" -print | wc -l)
test "$count" -le 10000
copy_exec /usr/bin/python3.13
copy_file binary /usr/bin/python3
# copy_exec stops early when its destination already exists. Resolve extension
# ELF dependencies BEFORE copying the complete Python tree over those files.
find "$stdlib/lib-dynload" -maxdepth 1 -type f -name '*.so' -print |
while IFS= read -r extension; do
    copy_exec "$extension"
done
mkdir -p "$DESTDIR/usr/lib"
cp -a "$stdlib" "$DESTDIR/usr/lib/"

for module in __init__ host_layout host_storage device_identity boot_layout boot_devices boot_storage boot_entry boot_gate boot_state boot_media boot_capacity boot_environment boot_backend; do
    test -f "$runtime/$module.py" && test ! -L "$runtime/$module.py"
    copy_file config "$runtime/$module.py"
done
copy_file config "$runtime/boot_select.sh"
copy_file config /usr/lib/zmala/role

# Private names avoid whichever busybox mount/umount applets other hooks add.
for tool in mount umount blkid; do
    source=$(command -v "$tool")
    copy_exec "$source" "/usr/lib/zmala/bin/$tool"
    chmod 0755 "$DESTDIR/usr/lib/zmala/bin/$tool"
done
manual_add_modules overlay ext4

# The worker registers the shell entry in /etc/initramfs-tools/scripts before
# mkinitramfs. Copying an entry only into DESTDIR would omit it from ORDER.
