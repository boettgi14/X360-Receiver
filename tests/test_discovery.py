"""Tests for receiver discovery against a reconstructed sysfs tree (no hardware)."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "py_modules"))

from x360w.discovery import find_receivers, input_event_nodes  # noqa: E402


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n")


def make_receiver(root: Path, name: str, pid: str, bus: int, devnum: int) -> None:
    dev = root / name
    write(dev / "idVendor", "045e")
    write(dev / "idProduct", pid)
    write(dev / "busnum", str(bus))
    write(dev / "devnum", str(devnum))
    write(dev / "product", "Xbox 360 Wireless Receiver for Windows")
    write(dev / "bcdDevice", "0100")
    for number in range(8):
        intf = dev / f"{name}:1.{number}"
        write(intf / "bInterfaceNumber", f"{number:02x}")
        write(intf / "bInterfaceSubClass", "5d")
        write(intf / "bInterfaceProtocol", "81" if number % 2 == 0 else "82")


class DiscoveryTests(unittest.TestCase):
    def test_two_receivers_and_foreign_device(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_receiver(root, "1-2", "0719", bus=1, devnum=4)
            make_receiver(root, "3-1", "0291", bus=3, devnum=7)
            # A foreign device (keyboard) must not show up
            keyboard = root / "1-4"
            write(keyboard / "idVendor", "046d")
            write(keyboard / "idProduct", "c52b")

            receivers = find_receivers(root)

        self.assertEqual([r.usb_path for r in receivers], ["1-2", "3-1"])
        first = receivers[0]
        self.assertEqual((first.bus, first.devnum), (1, 4))
        self.assertEqual(len(first.interfaces), 8)
        controllers = [i for i in first.interfaces if i.role == "controller"]
        self.assertEqual([i.slot for i in controllers], [0, 1, 2, 3])
        audio = [i for i in first.interfaces if i.role == "audio"]
        self.assertEqual(len(audio), 4)
        self.assertTrue(all(i.slot is None for i in audio))

    def test_labels_are_language_neutral_and_the_02a9_id_is_flagged_unofficial(self):
        # The frontend adds a translated "unofficial" note; the backend label stays the same in every language.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_receiver(root, "1-2", "0719", bus=1, devnum=4)
            make_receiver(root, "1-3", "0291", bus=1, devnum=5)
            make_receiver(root, "1-5", "02a9", bus=1, devnum=6)
            receivers = {r.usb_path: r for r in find_receivers(root)}
        self.assertEqual(receivers["1-2"].label, "Xbox 360 Wireless Receiver (0719)")
        self.assertEqual(receivers["1-3"].label, "Xbox 360 Wireless Receiver (0291)")
        self.assertEqual(receivers["1-5"].label, "Xbox 360 Wireless Receiver (02A9)")
        self.assertEqual({path: r.unofficial for path, r in receivers.items()},
                         {"1-2": False, "1-3": False, "1-5": True})
        self.assertIs(receivers["1-5"].to_dict()["unofficial"], True)
        self.assertTrue(all(r.label.isascii() for r in receivers.values()))

    def test_input_event_nodes_of_a_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_receiver(root, "1-2", "0719", bus=1, devnum=4)
            [receiver] = find_receivers(root)
            # slot 0 (interface :1.0) has an input device with two event nodes and other children
            for name in ("event7", "event10", "js0", "power", "subsystem"):
                (root / "1-2:1.0" / "input" / "input42" / name).mkdir(parents=True)
            (root / "1-2:1.0" / "input" / "not-an-input").mkdir()
            (root / "1-2:1.2" / "input" / "input43" / "event9").mkdir(parents=True)  # slot 1
            (root / "1-2:1.3" / "input" / "input44" / "event11").mkdir(parents=True)  # an audio interface
            self.assertEqual(input_event_nodes(receiver, 0, root), ["event7", "event10"])  # numeric order
            self.assertEqual(input_event_nodes(receiver, 1, root), ["event9"])
            self.assertEqual(input_event_nodes(receiver, 2, root), [])  # no controller in slot 2
            self.assertEqual(input_event_nodes(receiver, 9, root), [])

    def test_missing_sysfs(self):
        self.assertEqual(find_receivers(Path("/nonexistent/sysfs")), [])


if __name__ == "__main__":
    unittest.main()
