"""Tests für die Receiver-Erkennung gegen einen nachgebauten sysfs-Baum (ohne Hardware)."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "py_modules"))

from x360w.discovery import find_receivers  # noqa: E402


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
            # Fremdes Gerät (Tastatur) darf nicht auftauchen
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

    def test_missing_sysfs(self):
        self.assertEqual(find_receivers(Path("/nonexistent/sysfs")), [])


if __name__ == "__main__":
    unittest.main()
