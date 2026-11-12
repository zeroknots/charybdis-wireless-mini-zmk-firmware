/* USB-only bootloader request using the existing nice!nano reset behavior.
 * The host must explicitly change baud rate to 1200 and release DTR. A delayed
 * work item lets the control transfer finish before USB disappears. No settings,
 * pairings, bootloader image or Studio receive callbacks are modified.
 */
#include <errno.h>
#include <zephyr/device.h>
#include <zephyr/drivers/uart.h>
#include <zephyr/drivers/uart/cdc_acm.h>
#include <zephyr/init.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/reboot.h>
#include <dt-bindings/zmk/reset.h>
#include <zmk/usb.h>

#if DT_HAS_CHOSEN(charybdis_usb_flash_uart)
#define FLASH_UART DT_CHOSEN(charybdis_usb_flash_uart)
#else
#define FLASH_UART DT_CHOSEN(zmk_studio_rpc_uart)
#endif

static const struct device *const flash_uart = DEVICE_DT_GET(FLASH_UART);

/* Recheck all conditions after the delay. Disconnect, changed baud, active
 * terminal DTR or failed reads cancel the request instead of rebooting blindly.
 */
static void reboot_if_requested(struct k_work *work) {
    uint32_t baud = 0, dtr = 1;
    (void)work;
    if (!zmk_usb_is_hid_ready() ||
        uart_line_ctrl_get(flash_uart, UART_LINE_CTRL_BAUD_RATE, &baud) != 0 ||
        uart_line_ctrl_get(flash_uart, UART_LINE_CTRL_DTR, &dtr) != 0 ||
        baud != 1200 || dtr != 0) {
        return;
    }
    /* Same request code as &bootloader; preserves the storage partition. */
    sys_reboot(RST_UF2);
}

K_WORK_DELAYABLE_DEFINE(boot_work, reboot_if_requested);

/* The CDC driver calls this only when the USB host changes line coding.
 * Ordinary serial speeds cancel pending requests and cannot enter bootloader.
 */
static void baud_changed(const struct device *dev, uint32_t baud) {
    if (dev != flash_uart) {
        return;
    }
    if (baud == 1200) {
        k_work_reschedule(&boot_work, K_MSEC(150));
    } else {
        k_work_cancel_delayable(&boot_work);
    }
}

/* Register after USB initialization. Failure leaves the manual bootloader chord
 * usable; the CLI times out without writing if automatic entry is unavailable.
 */
static int usb_flash_init(void) {
    if (!device_is_ready(flash_uart)) {
        return -ENODEV;
    }
    return cdc_acm_dte_rate_callback_set(flash_uart, baud_changed);
}

SYS_INIT(usb_flash_init, APPLICATION, 99);
