"""Live task-success suite: PASTA executes real commands on this desktop.

    python -m pasta.eval.live            # asks before starting; takes ~1 minute

It opens its own Notepad and a Downloads window, types into that Notepad only,
changes the volume and restores it, and closes what it opened. Every task is
scored by an *independent* check written here (not by PASTA's own verifier), so
the result also measures whether PASTA's verification is honest:

* task success  = independent check passed
* verifier agreement = PASTA said "verified" exactly when the check passed

Safety interlock: before any task that sends keystrokes, the foreground window
must be the Notepad window this suite opened; otherwise the suite stops.
Do not use the computer while it runs.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research" / "results" / "live"


@dataclass
class Task:
    name: str
    utterance: str
    check: object  # callable(ctx) -> bool
    needs_own_notepad: bool = False


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--yes" not in sys.argv:
        ans = input("This suite will open Notepad/Explorer, type into its own Notepad and change the volume "
                    "temporarily. Do not touch the keyboard/mouse while it runs. Start? [y/N] ")
        if ans.strip().lower() not in ("y", "yes", "ν", "ναι"):
            return 1

    import threading

    from pesto.config import load_config
    from pesto.events import TERMINAL, EventBus, Status
    from pesto.inject import TextInjector

    from pasta import settings  # noqa: F401
    from pasta.agent import Agent
    from pasta.executors import Executors, clipboard_seq
    from pasta.planner import Planner
    from pasta.world import audio
    from pasta.world import windows as W
    from pasta.world.apps import AppIndex

    cfg = load_config()
    cfg.permissions.close_windows = "auto"  # the suite closes only windows it opened
    apps = AppIndex()
    apps.start()
    apps.wait(15)
    bus = EventBus()
    agent = Agent(cfg, bus, None, Planner(Executors(TextInjector(cfg.inject), apps, cfg.agent, cfg.permissions),
                                          apps, cfg.agent, cfg.permissions))
    ctx: dict = {"notepad": None, "volume": audio.get_state()}

    def run(utterance: str) -> tuple[list[dict], float]:
        done = threading.Event()
        last: dict = {}

        def watch(st: Status) -> None:
            last["steps"] = st.data.get("steps", [])
            if st.phase.value == "confirm":
                agent.answer(True)  # confirmations are part of normal use; count them separately
                ctx["confirmations"] = ctx.get("confirmations", 0) + 1
            if st.phase in TERMINAL:
                done.set()

        unsub = bus.subscribe(watch, Status)
        t0 = time.perf_counter()
        agent.submit(utterance)
        done.wait(30)
        while agent.busy:
            time.sleep(0.05)
        unsub()
        return last.get("steps", []), (time.perf_counter() - t0) * 1000

    def own_notepad_in_front() -> bool:
        np_ = ctx["notepad"]
        return np_ is not None and W.foreground_hwnd() == np_

    def find_new_notepad(before: set[int]):
        for w in W.list_windows():
            if w.process.lower() == "notepad.exe" and w.hwnd not in before:
                return w.hwnd
        return None

    def notepad_text() -> str:
        import uiautomation as auto

        with auto.UIAutomationInitializerInThread():
            win = auto.ControlFromHandle(ctx["notepad"])
            for ctrl, _ in auto.WalkControl(win, maxDepth=6):
                if ctrl.ControlTypeName in ("DocumentControl", "EditControl"):
                    try:
                        return ctrl.GetValuePattern().Value
                    except Exception:
                        try:
                            return ctrl.GetTextPattern().DocumentRange.GetText(-1)
                        except Exception:
                            continue
        return ""

    before = {w.hwnd for w in W.list_windows()}
    tasks = [
        Task("open_notepad", "open notepad", lambda c: c.__setitem__("notepad", find_new_notepad(before))
             or c["notepad"] is not None),
        Task("type_text", "type Καλημέρα από την ΠΑΣΤΑ", lambda c: "Καλημέρα από την ΠΑΣΤΑ" in notepad_text(), True),
        Task("select_all", "select all", None, True),  # no independent check (selection is not observable)
        Task("copy", "copy", lambda c: clipboard_seq() != c.get("seq_before"), True),
        Task("maximize", "maximize the window", lambda c: bool(W.user32.IsZoomed(c["notepad"])), True),
        Task("minimize", "minimize the window", lambda c: bool(W.user32.IsIconic(c["notepad"]))),
        Task("focus_back", "switch to notepad", lambda c: W.foreground_hwnd() == c["notepad"]),
        Task("volume_set", "set the volume to 23 percent", lambda c: audio.get_state()[0] == 23),
        Task("mute", "mute", lambda c: audio.get_state()[1] is True),
        Task("unmute", "unmute", lambda c: audio.get_state()[1] is False),
        Task("list", "what windows are open", None),  # read-only; no independent check
        Task("open_downloads", "open downloads", lambda c: any(w.process.lower() == "explorer.exe" and w.foreground
                                                                for w in W.list_windows())),
        Task("close_explorer", "close this window", lambda c: not any(
            w.process.lower() == "explorer.exe" and w.foreground for w in W.list_windows())),
    ]
    results = []
    for task in tasks:
        if task.needs_own_notepad:
            if ctx["notepad"] is None:
                print(f"skip {task.name}: no notepad")
                continue
            W.activate(ctx["notepad"])
            time.sleep(0.3)
            if not own_notepad_in_front():
                print("SAFETY STOP: the suite's Notepad is not in front; not sending keystrokes.")
                break
        ctx["seq_before"] = clipboard_seq()
        steps, ms = run(task.utterance)
        time.sleep(0.4)
        try:
            ok = None if task.check is None else bool(task.check(ctx))
        except Exception as exc:
            ok = False
            print(f"  check error: {exc}")
        claimed = bool(steps) and all(s["state"] == "done" for s in steps)
        results.append({"task": task.name, "utterance": task.utterance, "success": ok, "pasta_verified": claimed,
                        "pasta_states": [s["state"] for s in steps], "ms": round(ms)})
        print(f"{'----' if ok is None else 'PASS' if ok else 'FAIL'}  {task.name:16} {ms:6.0f} ms  PASTA: {[s['state'] for s in steps]}")

    # clean up: restore volume, close our Notepad without saving
    try:
        audio.set_volume(ctx["volume"][0])
        audio.set_mute(ctx["volume"][1])
    except Exception:
        pass
    if ctx["notepad"] and W.exists(ctx["notepad"]):
        W.close(ctx["notepad"])
        time.sleep(0.6)
        fg = W.window_info(W.foreground_hwnd())
        if fg and fg.process.lower() == "notepad.exe" and fg.hwnd != ctx["notepad"]:
            from pasta.executors import send_combo

            send_combo("alt+n")  # "Don't save" in the unsaved-changes dialog

    checked = [r for r in results if r["success"] is not None]
    n = len(checked)
    summary = {
        "n_tasks": len(results), "n_checked": n, "success_rate": sum(r["success"] for r in checked) / max(n, 1),
        "verifier_agreement": sum(r["success"] == r["pasta_verified"] for r in checked) / max(n, 1),
        "false_verified": sum(r["pasta_verified"] and not r["success"] for r in checked),
        "confirmations": ctx.get("confirmations", 0), "results": results,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"live-{time.strftime('%Y%m%d-%H%M%S')}.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False),
                                                                      encoding="utf-8")
    print(f"\nsuccess {summary['success_rate']:.0%} · verifier agreement {summary['verifier_agreement']:.0%} · "
          f"falsely 'verified': {summary['false_verified']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
