#!/usr/bin/env python3
"""Run the actual USB bootloader callback code against host-side Zephyr stubs.

This tests decisions and failure handling, not physical USB enumeration or timing.
The separate ARM firmware build verifies integration with the pinned Zephyr APIs.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(os.environ.get("CHARYBDIS_TEST_ROOT", Path(__file__).resolve().parents[1]))

STUBS = r'''
#include <stdbool.h>
#include <stdint.h>
#include <errno.h>
struct device { int id; };
static struct device selected_device = {1}, other_device = {2};
static bool ready = true, configured = true, pending;
static int reg_error, baud_error, dtr_error, reboot_count, reboot_type, delay_ms;
static uint32_t current_baud = 115200, current_dtr = 1;
struct k_work { int unused; };
struct k_work_delayable { struct k_work work; void (*handler)(struct k_work *); };
static void (*registered_callback)(const struct device *, uint32_t);
#define DT_HAS_CHOSEN(x) TEST_LEFT
#define DT_CHOSEN(x) 1
#define DEVICE_DT_GET(x) (&selected_device)
#define K_MSEC(x) (x)
#define APPLICATION 0
#define SYS_INIT(fn, level, priority)
#define K_WORK_DELAYABLE_DEFINE(name, fn) struct k_work_delayable name = {.handler = fn}
#define UART_LINE_CTRL_BAUD_RATE 1
#define UART_LINE_CTRL_DTR 2
#define RST_UF2 0x57
static bool device_is_ready(const struct device *dev) { (void)dev; return ready; }
static bool zmk_usb_is_hid_ready(void) { return configured; }
static int uart_line_ctrl_get(const struct device *dev, int key, uint32_t *out) {
    (void)dev;
    if (key == UART_LINE_CTRL_BAUD_RATE) { *out = current_baud; return baud_error; }
    *out = current_dtr; return dtr_error;
}
static int cdc_acm_dte_rate_callback_set(const struct device *dev,
        void (*cb)(const struct device *, uint32_t)) {
    (void)dev; registered_callback = cb; return reg_error;
}
static int k_work_reschedule(struct k_work_delayable *work, int delay) {
    (void)work; pending = true; delay_ms = delay; return 0;
}
static int k_work_cancel_delayable(struct k_work_delayable *work) {
    (void)work; pending = false; return 0;
}
static void sys_reboot(int type) { reboot_count++; reboot_type = type; }
'''

TEST = r'''
#include <assert.h>
#include USB_FLASH_SOURCE
/* Simulate the queue, never a real reset or USB controller. */
static void fire(void) {
    if (pending) { pending = false; boot_work.handler(&boot_work.work); }
}
int main(void) {
    ready = false;
    assert(usb_flash_init() == -ENODEV);
    ready = true; reg_error = -EIO;
    assert(usb_flash_init() == -EIO);
    reg_error = 0;
    assert(usb_flash_init() == 0 && registered_callback == baud_changed);
    /* Plugging USB or changing a normal Studio speed never reboots. */
    fire(); assert(reboot_count == 0);
    baud_changed(&selected_device, 115200); fire(); assert(reboot_count == 0);
    baud_changed(&other_device, 1200); fire(); assert(reboot_count == 0);
    /* Scheduling is deferred, and an open terminal (DTR high) is insufficient. */
    current_baud = 1200;
    baud_changed(&selected_device, 1200);
    assert(pending && delay_ms == 150 && reboot_count == 0);
    fire(); assert(reboot_count == 0);
    current_dtr = 0;
    configured = false; baud_changed(&selected_device, 1200); fire();
    assert(reboot_count == 0);
    configured = true; baud_error = -EIO;
    baud_changed(&selected_device, 1200); fire(); assert(reboot_count == 0);
    baud_error = 0; dtr_error = -EIO;
    baud_changed(&selected_device, 1200); fire(); assert(reboot_count == 0);
    dtr_error = 0; current_baud = 9600;
    baud_changed(&selected_device, 1200); fire(); assert(reboot_count == 0);
    current_baud = 1200;
    baud_changed(&selected_device, 1200);
    baud_changed(&selected_device, 115200); fire(); assert(reboot_count == 0);
    /* Exactly the explicit 1200 + closed-DTR + connected request uses UF2. */
    baud_changed(&selected_device, 1200); fire();
    assert(reboot_count == 1 && reboot_type == 0x57);
    fire(); assert(reboot_count == 1);
    return 0;
}
'''


class FirmwareTests(unittest.TestCase):
    """Compile and exercise both halves' device-selection branches without hardware."""
    def test_callback_guards_and_uf2_request(self):
        """Wrong speed, device, USB state, DTR and read failures must not reboot."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("zephyr/device.h", "zephyr/drivers/uart.h", "zephyr/drivers/uart/cdc_acm.h",
                         "zephyr/init.h", "zephyr/kernel.h", "zephyr/sys/reboot.h",
                         "dt-bindings/zmk/reset.h", "zmk/usb.h"):
                header = root / name
                header.parent.mkdir(parents=True, exist_ok=True)
                header.touch()
            (root / "stubs.h").write_text(STUBS)
            (root / "test.c").write_text(TEST)
            source = ROOT / "config/usb_flash/usb_flash.c"
            for left in (0, 1):
                with self.subTest(left=left):
                    executable = root / f"test-{left}"
                    subprocess.run([
                        "gcc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(root),
                        "-include", str(root / "stubs.h"), f"-DTEST_LEFT={left}",
                        f'-DUSB_FLASH_SOURCE="{source}"', str(root / "test.c"), "-o", str(executable),
                    ], check=True)
                    subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    unittest.main()
