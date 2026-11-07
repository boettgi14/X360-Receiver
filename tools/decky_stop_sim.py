#!/usr/bin/env python3
"""Mimics how Decky stops a plugin, around this plugin's main.py (Linux only; not part of `unittest`).

Based on Decky Loader's source (read 2026-11-07): the plugin runs in its own process with its own event loop;
SIGTERM triggers `shutdown()`, which awaits the plugin's `_unload()`, then ends the loop and calls
`sys.exit(0)`; if the process is still alive 5 s after SIGTERM, Decky sends SIGKILL.

This is a simulation, not Decky: it did NOT reproduce the hang seen on the device. Its use is to show that the
plugin stops quickly in a clean environment and what the exit watchdog does when something keeps the process
alive.

Usage:  python3 tools/decky_stop_sim.py <directory with main.py and py_modules/>
Environment:  RUN_S=7        seconds the plugin runs before SIGTERM
              SETTINGS='{}'  contents of x360w.json
              STALL=thread   a non-daemon thread keeps the interpreter from exiting after the loop is closed
              STALL=disable  the monitor stop hangs forever
"""
import asyncio
import importlib.util
import logging
import multiprocessing
import os
import signal
import sys
import tempfile
import threading
import time
import types

PLUGIN_DIR = sys.argv[1] if len(sys.argv) > 1 else "."
SETTINGS = os.environ.get("SETTINGS", "{}")
RUN_S = float(os.environ.get("RUN_S", "7"))
STALL = os.environ.get("STALL", "")


def child(settings_dir):
    logging.basicConfig(level=logging.INFO, format="  child: %(message)s", stream=sys.stdout)
    stub = types.ModuleType("decky")
    stub.logger = logging.getLogger("plugin")
    stub.DECKY_SETTINGS_DIR = settings_dir
    sys.modules["decky"] = stub
    sys.path.insert(0, PLUGIN_DIR)
    spec = importlib.util.spec_from_file_location("plugin_main", os.path.join(PLUGIN_DIR, "main.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    plugin = module.Plugin()
    state = {"running": False}

    async def shutdown():
        if not state["running"]:
            state["running"] = True
            print("  child: Calling Loader unload function", flush=True)
            print("  child: Attempting to unload", flush=True)
            await plugin._unload()
            print("  child: Unloaded", flush=True)
        asyncio.get_event_loop().call_soon_threadsafe(asyncio.get_event_loop().stop)
        sys.exit(0)

    loop.add_signal_handler(signal.SIGTERM, lambda: asyncio.ensure_future(shutdown()))

    async def frontend():
        # what the open panel does: get_status every 2 s, the notification poll every 10 s
        n = 0
        while True:
            await plugin.get_status()
            if n % 5 == 0:
                await plugin.take_low_battery_notices()
            n += 1
            await asyncio.sleep(2)

    if STALL == "thread":
        threading.Thread(target=lambda: time.sleep(60)).start()
    if STALL == "disable":
        async def hang_later():
            await asyncio.sleep(0.5)
            gate = threading.Event()
            plugin.service.disable = lambda: gate.wait(60)

        loop.create_task(hang_later())

    loop.create_task(plugin._main())
    loop.create_task(frontend())
    try:
        loop.run_forever()
    except SystemExit:
        pass
    finally:
        loop.close()
    print("  child: loop closed, the process function returns", flush=True)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "x360w.json"), "w", encoding="utf-8") as handle:
            handle.write(SETTINGS)
        proc = multiprocessing.Process(target=child, args=[tmp])
        proc.start()
        time.sleep(RUN_S)
        print(f"parent: SIGTERM after {RUN_S:g} s", flush=True)
        started = time.time()
        proc.terminate()
        while proc.is_alive() and time.time() - started < 5.5:
            time.sleep(0.05)
        took = time.time() - started
        if proc.is_alive():
            print(f"parent: STILL ALIVE after {took:.1f} s -> SIGKILL (this is what Decky does)", flush=True)
            proc.kill()
        else:
            print(f"parent: process ended after {took:.2f} s (exit code {proc.exitcode})", flush=True)
