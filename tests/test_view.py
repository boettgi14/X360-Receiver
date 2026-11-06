"""Tests for the receiver view (x360w.view), LED assignment and sysfs presence."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "py_modules"))
sys.path.insert(0, str(ROOT / "tests"))

from test_discovery import make_receiver  # noqa: E402
from x360w import controls, view  # noqa: E402
from x360w.discovery import connected_slots_sysfs, find_receivers  # noqa: E402
from x360w.monitor import blank_slot_dict  # noqa: E402


def monitor_entry(bus, devnum, connected_slots):
    slots = []
    for i in range(4):
        d = blank_slot_dict(i)
        d["connected"] = i in connected_slots
        slots.append(d)
    return {"bus": bus, "devnum": devnum, "slots": slots}


class Env:
    """Two receivers in the reconstructed sysfs tree."""

    def __init__(self, tmp):
        self.root = Path(tmp)
        make_receiver(self.root, "1-2", "0719", bus=1, devnum=4)
        make_receiver(self.root, "3-1", "0291", bus=3, devnum=7)
        self.receivers = find_receivers(self.root)

    def add_input(self, usb_path, slot):
        (self.root / f"{usb_path}:1.{2 * slot}" / "input" / "input42").mkdir(parents=True)

    def add_led(self, usb_path, name):
        real = self.root / usb_path / "leds" / name
        real.mkdir(parents=True)
        leds = self.root / "class_leds"
        leds.mkdir(exist_ok=True)
        os.symlink(real, leds / name)
        return leds


class SysfsPresenceTests(unittest.TestCase):
    def test_slots_with_input_device_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Env(tmp)
            env.add_input("1-2", 0)
            env.add_input("1-2", 2)
            (env.root / "1-2:1.2" / "input").mkdir(parents=True, exist_ok=True)  # an empty folder does not count
            self.assertEqual(connected_slots_sysfs(env.receivers[0], env.root), {0, 2})
            self.assertEqual(connected_slots_sysfs(env.receivers[1], env.root), set())

    def test_audio_interfaces_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Env(tmp)
            (env.root / "1-2:1.1" / "input" / "input7").mkdir(parents=True)  # audio interface
            self.assertEqual(connected_slots_sysfs(env.receivers[0], env.root), set())


class LedOwnerTests(unittest.TestCase):
    def test_led_belongs_to_receiver_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Env(tmp)
            env.add_led("1-2", "xpad0")
            leds = env.add_led("3-1", "xpad1")
            self.assertEqual(controls.led_owner("xpad0", leds), "1-2")
            self.assertEqual(controls.led_owners(leds), {"1-2": ["xpad0"], "3-1": ["xpad1"]})

    def test_invalid_or_foreign_led(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "input3::capslock").mkdir()
            self.assertIsNone(controls.led_owner("input3::capslock", base))
            self.assertIsNone(controls.led_owner("../x", base))
            self.assertIsNone(controls.led_owner("xpad9", base))  # does not exist
            (base / "xpad5").mkdir()  # not a symlink to .../leds/xpad5
            self.assertIsNone(controls.led_owner("xpad5", base))


class ViewTests(unittest.TestCase):
    def build(self, env, monitor=(), owners=None, sysfs=None):
        return view.build_receiver_views(env.receivers, list(monitor), owners or {}, sysfs or {})

    def test_no_controllers(self):
        with tempfile.TemporaryDirectory() as tmp:
            views = self.build(Env(tmp))
        self.assertEqual([v["usb_path"] for v in views], ["1-2", "3-1"])
        self.assertTrue(all(v["controllers"] == [] and v["unlocated_count"] == 0 for v in views))

    def test_monitor_and_sysfs_are_merged_per_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Env(tmp)
            views = self.build(env, [monitor_entry(1, 4, {0, 1})], sysfs={"1-2": {1, 3}})
        slots = {c["slot"]: c["detected_by"] for c in views[0]["controllers"]}
        self.assertEqual(slots, {0: ["monitor"], 1: ["monitor", "sysfs"], 3: ["sysfs"]})
        self.assertEqual(views[1]["controllers"], [])  # other receiver untouched

    def test_controller_dict_has_monitor_fields_even_without_monitor(self):
        with tempfile.TemporaryDirectory() as tmp:
            views = self.build(Env(tmp), sysfs={"3-1": {2}})
        c = views[1]["controllers"][0]
        self.assertEqual(c["slot"], 2)
        self.assertTrue(c["connected"])
        self.assertIsNone(c["battery_level"])
        self.assertIn("state_age_s", c)

    def test_leds_follow_controller_order(self):
        # xpad0 = controller 1, xpad1 = controller 2 etc. (in slot order)
        with tempfile.TemporaryDirectory() as tmp:
            env = Env(tmp)
            one = self.build(env, sysfs={"1-2": {0}}, owners={"1-2": ["xpad0"]})
            three = self.build(env, sysfs={"1-2": {0, 1, 2}}, owners={"1-2": ["xpad0", "xpad1", "xpad2"]})
            gap = self.build(env, sysfs={"1-2": {0, 2}}, owners={"1-2": ["xpad0", "xpad1"]})
        self.assertEqual(one[0]["controllers"][0]["led"], "xpad0")
        self.assertEqual([(c["slot"], c["led"]) for c in three[0]["controllers"]], [(0, "xpad0"), (1, "xpad1"), (2, "xpad2")])
        self.assertEqual([(c["slot"], c["led"]) for c in gap[0]["controllers"]], [(0, "xpad0"), (2, "xpad1")])
        for v in (one, three, gap):
            self.assertEqual(v[0]["unassigned_leds"], [])

    def test_led_order_is_numeric_not_alphabetic(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Env(tmp)
            names = ["xpad10", "xpad9"]  # alphabetically xpad10 would come before xpad9
            views = self.build(env, sysfs={"1-2": {0, 1}}, owners={"1-2": names})
        self.assertEqual([c["led"] for c in views[0]["controllers"]], ["xpad9", "xpad10"])

    def test_leds_of_each_receiver_are_assigned_separately(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Env(tmp)
            views = self.build(env, sysfs={"1-2": {0}, "3-1": {1}}, owners={"1-2": ["xpad0"], "3-1": ["xpad1"]})
        self.assertEqual(views[0]["controllers"][0]["led"], "xpad0")
        self.assertEqual(views[1]["controllers"][0]["led"], "xpad1")

    def test_led_count_mismatch_leaves_leds_unassigned(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Env(tmp)
            more_leds = self.build(env, sysfs={"1-2": {0}}, owners={"1-2": ["xpad0", "xpad1"]})
            fewer_leds = self.build(env, sysfs={"1-2": {0, 1}}, owners={"1-2": ["xpad0"]})
        for v in (more_leds, fewer_leds):
            self.assertTrue(all(c["led"] is None for c in v[0]["controllers"]))
        self.assertEqual(more_leds[0]["unassigned_leds"], ["xpad0", "xpad1"])
        self.assertEqual(fewer_leds[0]["unassigned_leds"], ["xpad0"])

    def test_led_without_located_controller_counts_as_unlocated(self):
        with tempfile.TemporaryDirectory() as tmp:
            views = self.build(Env(tmp), owners={"1-2": ["xpad0"]})
        self.assertEqual(views[0]["controllers"], [])
        self.assertEqual(views[0]["unlocated_count"], 1)
        self.assertEqual(views[0]["unassigned_leds"], ["xpad0"])


class CachedBatteryTests(unittest.TestCase):
    def build(self, env, monitor=(), cached=None, sysfs=None):
        return view.build_receiver_views(env.receivers, list(monitor), {}, {"1-2": {0}} if sysfs is None else sysfs, cached)

    def entry(self, level=2, age=30.0):
        return {"battery_level": level, "battery_type_raw": 1, "power_state_raw": 2, "age_s": age}

    def test_cached_value_fills_missing_battery(self):
        with tempfile.TemporaryDirectory() as tmp:
            [first, _] = self.build(Env(tmp), cached={(1, 4, 0): self.entry()})
        c = first["controllers"][0]
        self.assertEqual((c["battery_level"], c["state_source"]), (2, "query"))
        self.assertAlmostEqual(c["state_age_s"], 30.0)

    def test_monitor_value_wins_when_newer(self):
        with tempfile.TemporaryDirectory() as tmp:
            entry = monitor_entry(1, 4, {0})
            entry["slots"][0].update(battery_level=3, state_age_s=5.0, state_source="report")
            [first, _] = self.build(Env(tmp), monitor=[entry], cached={(1, 4, 0): self.entry(level=1, age=30.0)})
        c = first["controllers"][0]
        self.assertEqual((c["battery_level"], c["state_source"]), (3, "report"))

    def test_cached_value_wins_when_newer_than_monitor(self):
        with tempfile.TemporaryDirectory() as tmp:
            entry = monitor_entry(1, 4, {0})
            entry["slots"][0].update(battery_level=3, state_age_s=300.0, state_source="report")
            [first, _] = self.build(Env(tmp), monitor=[entry], cached={(1, 4, 0): self.entry(level=1, age=2.0)})
        c = first["controllers"][0]
        self.assertEqual((c["battery_level"], c["state_source"]), (1, "query"))

    def test_cache_of_other_slot_or_receiver_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            [first, second] = self.build(Env(tmp), sysfs={"1-2": {0}, "3-1": {0}},
                                         cached={(1, 4, 1): self.entry(), (9, 9, 0): self.entry()})
        self.assertIsNone(first["controllers"][0]["battery_level"])
        self.assertIsNone(second["controllers"][0]["battery_level"])

    def test_disconnected_slot_is_not_resurrected_by_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            [first, _] = self.build(Env(tmp), sysfs={}, cached={(1, 4, 0): self.entry()})
        self.assertEqual(first["controllers"], [])


class ConnectedTargetsTests(unittest.TestCase):
    def test_only_located_controllers_no_guessing(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Env(tmp)
            views = view.build_receiver_views(env.receivers, [], {"3-1": ["xpad0"]}, {"1-2": {1, 3}})
            targets = view.connected_targets(views)
        # Receiver 2 has only a LED but no detected slots: NOT guessed here
        self.assertEqual(targets, [(1, 4, 1), (1, 4, 3)])


class PlanTargetsTests(unittest.TestCase):
    def plan(self, **kw):
        with tempfile.TemporaryDirectory() as tmp:
            env = Env(tmp)
            return view.plan_targets(view.build_receiver_views(
                env.receivers, kw.get("monitor", []), kw.get("owners", {}), kw.get("sysfs", {})))

    def test_nothing_connected_nothing_targeted(self):
        self.assertEqual(self.plan(), [])

    def test_known_slots_only(self):
        self.assertEqual(self.plan(sysfs={"1-2": {1}, "3-1": {0, 3}}, owners={"1-2": ["xpad0"], "3-1": ["xpad1", "xpad2"]}),
                         [(1, 4, 1), (3, 7, 0), (3, 7, 3)])

    def test_led_but_unknown_slot_targets_all_slots_of_that_receiver_only(self):
        self.assertEqual(self.plan(owners={"3-1": ["xpad0"]}), [(3, 7, s) for s in range(4)])

    def test_more_leds_than_located_controllers_targets_all_slots(self):
        targets = self.plan(sysfs={"1-2": {0}}, owners={"1-2": ["xpad0", "xpad1"]})
        self.assertEqual(targets, [(1, 4, s) for s in range(4)])

    def test_monitor_slots(self):
        self.assertEqual(self.plan(monitor=[monitor_entry(1, 4, {2})], owners={"1-2": ["xpad0"]}), [(1, 4, 2)])


if __name__ == "__main__":
    unittest.main()
