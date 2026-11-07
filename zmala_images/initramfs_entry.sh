#!/bin/sh
# Registered boot script: initramfs-tools validates source entries as shell.
case "${1:-}" in
    prereqs) exit 0 ;;
esac
exec /usr/bin/python3 -IB -m zmala_system.boot_entry "$@"
