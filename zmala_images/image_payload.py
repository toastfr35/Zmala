"""Bounded payload preparation for an explicitly unqualified Pi 4 image."""
import gzip
import io
from pathlib import Path
import struct
import zlib

from zmala_system import boot_capacity, boot_media, boot_state

MIB = 1024**2
SIZES = boot_capacity.SIZES


def disk_bytes(capacity=None):
    minimum = boot_media.FIRST_PARTITION_BYTES+sum(SIZES)+MIB
    if capacity is None:
        return minimum
    if type(capacity) is not int or capacity % 512 or not minimum <= capacity <= 128*1024**3:
        raise ValueError('Media capacity must be sector-aligned, fit the layout and be at most 128 GiB')
    return capacity


def kernel_image(body):
    if body[:2] == b'\x1f\x8b':
        with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
            body = stream.read(32*MIB+1)
    if not 64 <= len(body) <= 32*MIB or body[56:60] != b'ARMd':
        raise ValueError('Kernel must be an ARM64 Image fitting the reserved 32 MiB window')
    return body


def environment(initial, role, flag):
    fields = {}
    for line in initial.splitlines():
        key, value = line.split('=', 1)
        if key in fields or key.startswith('zm_') or '\0' in line:
            raise ValueError('Compiled environment contains duplicate or appliance state fields')
        fields[key] = value
    fields.update(boot_state.State(role, 'A').fields())
    body = b''.join((key+'='+str(value)).encode()+b'\0' for key, value in fields.items())+b'\0'
    if len(body) > boot_media.ENV_BYTES-5 or flag not in (0, 1):
        raise ValueError('Invalid raw environment footprint or redundancy flag')
    body = body.ljust(boot_media.ENV_BYTES-5, b'\xff')
    return struct.pack('<I', zlib.crc32(body))+bytes([flag])+body


def boot_script():
    selector = (Path(__file__).resolve().parents[1]/'zmala_system/boot_select.sh').read_text()
    return selector+'''
if test -z "${zm_selected}"; then reset; fi
if test "${zm_selected}" = "A"; then
    setenv zm_bootpart 2
    setenv zm_rootpart 4
else
    setenv zm_bootpart 3
    setenv zm_rootpart 5
fi
# Pi firmware enables RTS/CTS for the onboard Bluetooth UART on some revisions.
# Recognize the firmware pin group before loading the selected slot.
setenv zm_uart_flow_control
setenv zm_uart_pins /soc/gpio@7e200000/uart0_pins
if test -n "${fdt_addr}" && fdt addr ${fdt_addr}; then
    if fdt get value zm_pins ${zm_uart_pins} brcm,pins && fdt get value zm_pulls ${zm_uart_pins} brcm,pull; then
        if test "${zm_pins}" = "0000001e0000001f0000002000000021" && test "${zm_pulls}" = "00000002000000000000000000000002"; then
            setenv zm_uart_flow_control 1
        fi
    fi
fi
if part uuid mmc 0:${zm_rootpart} zm_rootuuid; then
    setenv kernel_addr_r 0x00080000
    setenv ramdisk_addr_r 0x02100000
    setenv fdt_addr_r 0x05600000
    setenv fdt_high 0xffffffffffffffff
    setenv initrd_high 0xffffffffffffffff
    if fatload mmc 0:${zm_bootpart} ${kernel_addr_r} Image; then
        if fatload mmc 0:${zm_bootpart} ${ramdisk_addr_r} initramfs.img; then
            setenv zm_initrd_bytes ${filesize}
            if fatload mmc 0:${zm_bootpart} ${fdt_addr_r} board.dtb; then
                if fdt addr ${fdt_addr_r} && fdt resize 0x10000; then
                    # Keep the slot DTB and adjust only the known TX/RX-only layout.
                    if test "${zm_uart_flow_control}" = "1"; then
                        if fdt get value zm_pins ${zm_uart_pins} brcm,pins && fdt get value zm_pulls ${zm_uart_pins} brcm,pull; then
                            if test "${zm_pins}" = "0000002000000021" && test "${zm_pulls}" = "0000000000000002"; then
                                if fdt set ${zm_uart_pins} brcm,pins "<30 31 32 33>" && fdt set ${zm_uart_pins} brcm,pull "<2 0 0 2>"; then
                                    echo "Enabled firmware Bluetooth UART flow control"
                                else
                                    reset
                                fi
                            fi
                        fi
                    fi
                    setenv bootargs "console=tty1 root=PARTUUID=${zm_rootuuid} rootfstype=ext4 rootwait ro rauc.slot=${zm_selected} watchdog.handle_boot_enabled=1 watchdog.open_timeout=60"
                    if test "${zm_role}" = "terminal" || test "${zm_role}" = "combined"; then
                        setenv bootargs "root=PARTUUID=${zm_rootuuid} rootfstype=ext4 rootwait ro rauc.slot=${zm_selected} watchdog.handle_boot_enabled=1 watchdog.open_timeout=60 quiet splash plymouth.ignore-serial-consoles loglevel=3 logo.nologo vt.global_cursor_default=0"
                    fi
                    if wdt dev watchdog@7e100000; then
                        if test "${zm_is_trial}" = "1"; then
                            if wdt start 15000; then
                                booti ${kernel_addr_r} ${ramdisk_addr_r}:${zm_initrd_bytes} ${fdt_addr_r}
                            fi
                        else
                            # Development factory boot only: joint health transfer is not implemented.
                            if wdt stop; then
                                booti ${kernel_addr_r} ${ramdisk_addr_r}:${zm_initrd_bytes} ${fdt_addr_r}
                            fi
                        fi
                    fi
                fi
            fi
        fi
    fi
fi
reset
'''
