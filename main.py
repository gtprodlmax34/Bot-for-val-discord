"""
Discord "Social Posting" LF-button auto-clicker.

Cycles between two channel tabs: "social" (templates/tab1.png) and
"social-eu-18+" (templates/tab2.png). For each tab: clicks the tab, clicks
again just to the right of it (to move keyboard focus from the channel
list into the message pane), then holds End -- repeatedly pressing it
until the screen stops changing, i.e. the channel has actually reached
the bottom of scrollback -- then looks
for the "LF text" / "LF vc" buttons (from the "Social Posting" message
shown by the Valcord bot). When one is found, it randomly clicks either
"LF text" or "LF vc", waits a few seconds, then moves on to the other tab
and does the same. Once both tabs have been checked, it waits a randomized
~3:20 interval before starting the cycle over from the first tab.

Setup:
    1. Run capture_templates.py once to save templates/lf_text.png,
       templates/lf_vc.png, templates/tab1.png and templates/tab2.png
       from your own screen.
    2. Run this script: python main.py
    3. Press Ctrl+C to stop.

Notes:
    - Keep the Discord window visible and unobstructed on screen;
      this reads pixels, it does not talk to Discord's API.
    - MATCH_THRESHOLD may need tuning (0.0-1.0, higher = stricter)
      depending on how closely your capture matches the live button.
"""
import random
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import pyautogui
import pydirectinput
from mss import mss

if getattr(sys, "frozen", False):
    # Running from a PyInstaller-built .exe: data files (templates/) are
    # unpacked next to the executable, not next to this source file.
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

# Swappable log sink so a GUI can redirect output instead of stdout.
log = print

# Set by a GUI (or Ctrl+C) to make the run loop stop at the next safe point.
STOP_EVENT = threading.Event()

TEMPLATES = {
    "lf_text": BASE_DIR / "templates" / "lf_text.png",
    "lf_vc": BASE_DIR / "templates" / "lf_vc.png",
}

TAB_TEMPLATES = {
    "social": BASE_DIR / "templates" / "tab1.png",
    "social-eu-18+": BASE_DIR / "templates" / "tab2.png",
}

TAB_SWITCH_SETTLE_SECONDS = 0.5

TAB_CLICK_MAX_ATTEMPTS = 3

FOCUS_CLICK_OFFSET_X = 1000

TAB_GAP_SECONDS = 3

SCROLL_CHECK_INTERVAL_SECONDS = 0.3
SCROLL_STABLE_CHECKS = 2
SCROLL_MAX_PRESSES = 15

MATCH_THRESHOLD = 0.85

INTERVAL_CENTER_SECONDS = 200
INTERVAL_JITTER_SECONDS = 20

POLL_INTERVAL_SECONDS = 2

MONITOR_INDEX = 1


def load_templates() -> dict[str, np.ndarray]:
    templates = {}
    for name, path in TEMPLATES.items():
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            log(f"ERROR: could not load {path}. Run capture_templates.py first.")
            sys.exit(1)
        templates[name] = img
    return templates


def load_tab_templates() -> dict[str, np.ndarray]:
    templates = {}
    for name, path in TAB_TEMPLATES.items():
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            log(f"ERROR: could not load {path}. Run capture_templates.py first.")
            sys.exit(1)
        templates[name] = img
    return templates


def grab_screen() -> np.ndarray:
    with mss() as sct:
        monitor = sct.monitors[MONITOR_INDEX]
        shot = np.array(sct.grab(monitor))
    return cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)


def find_button(screen: np.ndarray, template: np.ndarray) -> tuple[int, int] | None:
    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val < MATCH_THRESHOLD:
        return None
    h, w = template.shape[:2]
    center_x = max_loc[0] + w // 2
    center_y = max_loc[1] + h // 2
    return center_x, center_y


def switch_to_tab(pos: tuple[int, int]) -> None:
    before = grab_screen()
    for attempt in range(TAB_CLICK_MAX_ATTEMPTS):
        click_at(pos)
        time.sleep(TAB_SWITCH_SETTLE_SECONDS)
        after = grab_screen()
        if not np.array_equal(before, after):
            break
        log(f"NOTE: click at {pos} didn't change the screen, retrying tab click...")

    focus_pos = (pos[0] + FOCUS_CLICK_OFFSET_X, pos[1])
    click_at(focus_pos)
    time.sleep(TAB_SWITCH_SETTLE_SECONDS)

    scroll_to_bottom()


def scroll_to_bottom() -> None:
    previous = None
    stable_count = 0
    for _ in range(SCROLL_MAX_PRESSES):
        if STOP_EVENT.is_set():
            return
        pydirectinput.press("end")
        time.sleep(SCROLL_CHECK_INTERVAL_SECONDS)
        screen = grab_screen()
        if previous is not None and np.array_equal(screen, previous):
            stable_count += 1
            if stable_count >= SCROLL_STABLE_CHECKS:
                return
        else:
            stable_count = 0
        previous = screen


def check_and_click_tab(
    tab_name: str,
    tab_template: np.ndarray,
    templates: dict[str, np.ndarray],
) -> bool:
    """Switch to one tab, scroll to bottom, and click an LF button if
    present. Returns True if a button was clicked."""
    screen = grab_screen()
    tab_pos = find_button(screen, tab_template)
    if tab_pos is None:
        log(f"NOTE: could not find '{tab_name}' on screen, skipping it")
        return False

    switch_to_tab(tab_pos)

    screen = grab_screen()
    found = {}
    for name, template in templates.items():
        pos = find_button(screen, template)
        if pos:
            found[name] = pos

    if not found:
        return False

    choice = random.choice(list(found.keys()))
    pos = found[choice]
    log(f"[{tab_name}] found buttons {list(found.keys())} -> clicking '{choice}' at {pos}")
    click_at(pos)
    return True


def run_cycle(
    templates: dict[str, np.ndarray], tab_templates: dict[str, np.ndarray]
) -> bool:
    """One pass over every tab, clicking an LF button on each where present,
    with a short gap between tabs. Returns True if any button was clicked."""
    clicked_any = False
    tab_items = list(tab_templates.items())
    for i, (tab_name, tab_template) in enumerate(tab_items):
        if STOP_EVENT.is_set():
            break
        if check_and_click_tab(tab_name, tab_template, templates):
            clicked_any = True
            if i < len(tab_items) - 1:
                STOP_EVENT.wait(TAB_GAP_SECONDS)
    return clicked_any


def click_at(pos: tuple[int, int]) -> None:
    pyautogui.moveTo(pos[0], pos[1], duration=random.uniform(0.15, 0.4))
    pydirectinput.mouseDown()
    time.sleep(random.uniform(0.05, 0.1))
    pydirectinput.mouseUp()


def next_interval() -> float:
    return INTERVAL_CENTER_SECONDS + random.uniform(
        -INTERVAL_JITTER_SECONDS, INTERVAL_JITTER_SECONDS
    )


def main() -> None:
    STOP_EVENT.clear()
    templates = load_templates()
    tab_templates = load_tab_templates()
    log("Discord LF auto-clicker started. Press Ctrl+C to stop.")

    loop_count = 0
    while not STOP_EVENT.is_set():
        loop_count += 1
        clicked_any = run_cycle(templates, tab_templates)
        if STOP_EVENT.is_set():
            break
        if clicked_any:
            wait_s = next_interval()
            log(f"Waiting {wait_s:.0f}s before next check...")
            log(f"Looped {loop_count} times")
            STOP_EVENT.wait(wait_s)
        else:
            STOP_EVENT.wait(POLL_INTERVAL_SECONDS)
    log("Stopped.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        STOP_EVENT.set()
        log("\nStopped.")
