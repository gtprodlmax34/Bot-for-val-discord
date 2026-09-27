
"""
One-off helper to grab button template images from your screen.

Usage:
    1. Open Discord and make sure the "Social Posting" message with the
       LF buttons is visible on screen.
    2. Run this script: python capture_templates.py
    3. When prompted, move your mouse to the TOP-LEFT corner of the
       "LF text" button and press Enter, then to the BOTTOM-RIGHT
       corner of the same button and press Enter.
    4. Repeat for "LF vc".
    5. Repeat for the two channel tabs ("tab1", "tab2") that main.py
       should cycle between -- capture each tab/channel-link icon itself,
       not its contents.
    6. The cropped images are saved to templates/lf_text.png,
       templates/lf_vc.png, templates/tab1.png and templates/tab2.png
       for main.py to use.
"""
import time
from pathlib import Path

import pyautogui

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"


def get_point(label: str) -> tuple[int, int]:
    input(f"Hover the mouse over {label}, then press Enter here...")
    time.sleep(0.2)
    pos = pyautogui.position()
    print(f"  -> captured {label} at {pos}")
    return pos


def capture_button(name: str) -> None:
    print(f"\n--- Capturing '{name}' ---")
    x1, y1 = get_point(f"the TOP-LEFT corner of '{name}'")
    x2, y2 = get_point(f"the BOTTOM-RIGHT corner of '{name}'")

    left, top = min(x1, x2), min(y1, y2)
    width, height = abs(x2 - x1), abs(y2 - y1)
    if width < 2 or height < 2:
        print("  Region too small, skipping.")
        return

    img = pyautogui.screenshot(region=(left, top, width, height))
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = TEMPLATES_DIR / f"{name}.png"
    img.save(out_path)
    print(f"  Saved {out_path} ({width}x{height})")


if __name__ == "__main__":
    print(
        "This will capture the 'LF text' and 'LF vc' button images, plus the "
        "two channel tabs main.py should cycle between."
    )
    capture_button("lf_text")
    capture_button("lf_vc")

    print(
        "\n--- Capturing 'tab1' ---\n"
        "Capture the first channel tab/link itself (e.g. in the channel list "
        "or a pinned DM/tab bar), not its contents."
    )
    capture_button("tab1")

    print(
        "\n--- Capturing 'tab2' ---\n"
        "Now capture the second channel tab/link the same way."
    )
    capture_button("tab2")
    print("\nDone. Run main.py to start the bot.")
