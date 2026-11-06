"""Error codes the backend sends to the frontend next to its English error text.

The backend never produces text in the user's language. A failed action returns
{"ok": False, "error": <English text>} and, for failures a user can act on, a `code` from this list
(plus an optional `detail`). The frontend (src/i18n.ts, `errors`) translates the code and appends the
detail; for an unknown code it shows the English text. `tests/test_i18n_contract.py` checks that every
code listed here has a translation.
"""

BUSY = "busy"  # another USB access to the receiver is running
RECEIVER_NOT_FOUND = "receiver_not_found"  # the receiver is gone (e.g. unplugged) since the UI last refreshed
LED_MISSING = "led_missing"  # the LED only exists while its controller is connected
LIBUSB_UNAVAILABLE = "libusb_unavailable"  # libusb cannot be loaded in the plugin process; detail = reason
UNIT_SETUP_FAILED = "unit_setup_failed"  # setting up the shutdown service failed; detail = reason
UNIT_REMOVAL_FAILED = "unit_removal_failed"  # removing the shutdown service failed; detail = reasons
SETTINGS_NOT_SAVED = "settings_not_saved"  # the settings file could not be written; detail = reason

ALL = (
    BUSY,
    RECEIVER_NOT_FOUND,
    LED_MISSING,
    LIBUSB_UNAVAILABLE,
    UNIT_SETUP_FAILED,
    UNIT_REMOVAL_FAILED,
    SETTINGS_NOT_SAVED,
)
