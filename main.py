"""
Discord "Social Posting" LF-button auto-clicker.

Finds the Discord window and reads its text with Windows' built-in OCR, so
there's nothing to set up: no button screenshots, and it doesn't care about
resolution, display scaling, theme, window size or which monitor Discord
is on.

Cycles between two channels, "social" and "social-eu-18+". For each: finds
the channel's name in the channel list and clicks it, clicks the message
pane (to give it keyboard focus), then holds End -- repeatedly pressing it
until the screen stops changing, i.e. the channel has actually reached the
bottom of scrollback -- then clicks the newest "Use legacy bot" button (from the "Social Posting"
message shown by the Valcord bot), which pops out the "LF text" / "LF vc"
buttons. It randomly clicks one of those, checks the bot's post showed up,
waits a few seconds, then moves on to the other channel and does the same.
Once both channels have been checked, it waits a randomized ~3:20 interval
before starting the cycle over.

Usage:
    1. Open the Discord app on the server with those channels, so both
       channels show in the channel list.
    2. Run this script: python main.py
    3. Press Ctrl+C to stop.

Notes:
    - It brings Discord to the front each cycle; the window can be anywhere,
      even minimized, but nothing should cover it while the bot clicks.
    - This reads pixels, it does not talk to Discord's API.
"""
import asyncio
import ctypes
import random
import re
import sys
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from difflib import SequenceMatcher

import cv2
import numpy as np
import pyautogui
import pydirectinput
from mss import MSS
from winrt.windows.globalization import Language
from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage.streams import DataWriter

# Swappable log sink so a GUI can redirect output instead of stdout.
log = print

# Both libraries sleep 0.1s after *every* call by default (move, mouseDown,
# mouseUp, key press...). Halve that: fast, but not instant.
pyautogui.PAUSE = 0.05
pydirectinput.PAUSE = 0.05

# Set by a GUI (or Ctrl+C) to make the run loop stop at the next safe point.
STOP_EVENT = threading.Event()

# Channels to cycle through, as they're named in Discord's channel list.
CHANNELS = ["social", "social-eu-18+", "social-na-18+", "social-other-regions-18+"]

# The server those channels are in. If Discord is showing something else
# (a DM, another server), the bot jumps here with the quick switcher.
SERVER_NAME = "VALORANT LFG"
# After jumping to the server or scrolling the channel list, wait up to this
# long for the screen to stop changing (the switcher closing, the server
# loading, the smooth scroll finishing).
SETTLE_TIMEOUT_SECONDS = 4
SETTLE_POLL_SECONDS = 0.3

LEGACY_LABEL = "Use legacy bot"
LF_LABELS = {"lf_text": "LF text", "lf_vc": "LF vc"}

# How closely OCR'd text must match a label (0-1). OCR sometimes misreads a
# character (e.g. "social-eu-1 8+"), so this isn't an exact match -- but it's
# strict enough that "social-na-18+" doesn't count as "social-eu-18+".
CHANNEL_MATCH_RATIO = 0.9
# Channel names in the list start at most this far right of the server's
# name heading it (anything further right is outside the channel list).
CHANNEL_LIST_MAX_INDENT = 100
# Labels shorter than this (spaces removed) must match exactly, since one
# wrong letter in a short label is a different word.
FUZZY_LABEL_MIN_LENGTH = 10
LABEL_MATCH_RATIO = 0.8

# Discord's UI text is small; upscaling the screenshot before OCR makes it
# read much more reliably.
OCR_SCALE = 2

# Windows OCR misses white text on colored buttons (e.g. "LF text" on
# blurple), but reads it fine once everything brighter than this is turned
# black and the rest white.
BUTTON_TEXT_MIN_BRIGHTNESS = 200

# The LF buttons are Discord's blurple (#5865F2, darker while hovered). OCR
# of the whole window drops short labels like "vc", so each blurple button
# is found by color and read on its own, zoomed in further.
BUTTON_MIN_BLUE = 150
BUTTON_MIN_BLUE_OVER_RED = 100
BUTTON_MIN_BLUE_OVER_GREEN = 90
BUTTON_MIN_SIZE = (30, 20)  # width, height
BUTTON_MAX_SIZE = (400, 60)
BUTTON_ROW_TOLERANCE = 4
# (min brightness counted as label text, zoom, margin) for reading one
# button; tried in turn, since each misses labels the others read.
BUTTON_OCR_SETTINGS = [(200, 3, 10), (200, 6, 30), (170, 4, 30), (200, 2, 30)]
# Where each LF button sits in the bot's row of buttons (0 = leftmost).
LF_BUTTON_ORDER = {"lf_text": 0, "lf_vc": 2}

# After clicking a tab, poll this often (up to the timeout) for the screen to
# change instead of sleeping a fixed amount.
TAB_SWITCH_POLL_SECONDS = 0.03
TAB_SWITCH_TIMEOUT_SECONDS = 1

TAB_CLICK_MAX_ATTEMPTS = 3

# After switching channel, click the message pane to give it keyboard focus
# (so End scrolls it), then press Esc in case the click opened something.
# The click goes halfway down the window, PANE_RIGHT_MARGIN from its right
# edge -- right of where message content usually ends, so it's unlikely to
# hit a name or link, and clear of the member list -- but at least
# PANE_MIN_OFFSET_X right of the channel name, so it's past the channel list.
PANE_RIGHT_MARGIN = 320
PANE_MIN_OFFSET_X = 250

TAB_GAP_SECONDS = 1.5

SCROLL_CHECK_INTERVAL_SECONDS = 0.25
SCROLL_STABLE_CHECKS = 2
SCROLL_MAX_PRESSES = 8
# Mouse wheel movement per scroll of the channel list (120 = one notch;
# negative = down).
SCROLL_WHEEL_AMOUNT = -3000
# To look for a channel that's scrolled out of view, the mouse goes this far
# below the server name at the top of the channel list, scrolls the list all
# the way up (this many big scrolls), then steps down this much at a time
# (120 = one wheel notch), up to this many steps.
CHANNEL_LIST_SCROLL_OFFSET_Y = 150
CHANNEL_LIST_SCROLLS = 3
CHANNEL_LIST_STEP_AMOUNT = -360
CHANNEL_LIST_MAX_STEPS = 10

# After clicking "Use legacy bot", how long to keep looking for the LF
# buttons to pop out before giving up on this tab.
LEGACY_POPUP_TIMEOUT_SECONDS = 5
LEGACY_POPUP_POLL_SECONDS = 0.05

# How many times to redo "Use legacy bot" -> LF click on one tab until the
# post is confirmed, before giving up on that tab for this cycle (e.g. the
# account is still on cooldown).
TAB_MAX_ATTEMPTS = 5
RETRY_DELAY_SECONDS = 1

# Discord highlights messages that @mention you: a gold-tinted background
# with a gold bar down the left edge. Your own LF post mentions you, other
# people's don't, so a new highlighted row means your post went through --
# for any account. The exact background depends on the Discord theme, so
# instead of one exact color it's checked for a warm tint (red well above
# blue). That tint is what tells a mention highlight apart from e.g. a gold
# embed border, whose background is neutral or cool.
HIGHLIGHT_BAR_BGR = (41, 181, 252)  # RGB(252, 181, 41)
HIGHLIGHT_COLOR_TOLERANCE = 30
HIGHLIGHT_BG_MIN_WARMTH = 6
HIGHLIGHT_BAR_MIN_HEIGHT = 30
HIGHLIGHT_BAR_MAX_WIDTH = 4
# How far right of the bar to sample for the highlight background.
HIGHLIGHT_BG_SAMPLE_OFFSET = 20

SUCCESS_TIMEOUT_SECONDS = 6
SUCCESS_POLL_SECONDS = 0.1

# Time from one click in the first channel ("social") to the next: the next
# cycle starts so that it gets back to that channel and clicks again this
# long after the last click there (plus or minus the jitter).
INTERVAL_CENTER_SECONDS = 180
INTERVAL_JITTER_SECONDS = 0

POLL_INTERVAL_SECONDS = 0.5

# How long to wait before looking again when Discord isn't open.
DISCORD_RETRY_SECONDS = 5


# --- Discord window -------------------------------------------------------

user32 = ctypes.windll.user32

SW_RESTORE = 9
SW_MINIMIZE = 6
FOREGROUND_ATTEMPTS = 3
VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x2
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79

# Screen area of the Discord window, as an mss region. Every screenshot is
# of just this area, and every position found in one is relative to it.
_region: dict[str, int] = {}


DISCORD_APP_EXES = {"discord.exe", "discordptb.exe", "discordcanary.exe"}
BROWSER_EXES = {
    "chrome.exe", "msedge.exe", "firefox.exe", "opera.exe", "brave.exe",
    "vivaldi.exe",
}
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _process_name(hwnd: int) -> str:
    """Lowercase exe name of the process that owns a window, e.g.
    "discord.exe", or "" if it can't be read."""
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        path = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
            return ""
        return path.value.rsplit("\\", 1)[-1].lower()
    finally:
        kernel32.CloseHandle(handle)


def _is_discord_tab_title(title: str) -> bool:
    """Whether a browser window's title is a Discord tab's. Browsers show
    the selected tab's title, which Discord formats either as
    "#channel | Server - Discord" or "(3) Discord | #channel | Server"."""
    return " - Discord" in title or re.match(r"(\(\d+\)\s*)?Discord \|", title) is not None


def find_discord_window() -> int | None:
    """Handle of the window showing Discord, or None if there isn't one.
    Either kind counts - the desktop app or a browser whose selected tab is
    Discord - and whichever is on top on screen wins, i.e. the one you can
    see. A minimized one is only used if no other is open."""
    shown, minimized = [], []

    # EnumWindows goes through windows from the top of the screen's stacking
    # order down, so the first one found is the one in front.
    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def check(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, length + 1)
        if not title.value:
            return True
        exe = _process_name(hwnd)
        if exe in DISCORD_APP_EXES or (
            exe in BROWSER_EXES and _is_discord_tab_title(title.value)
        ):
            (minimized if user32.IsIconic(hwnd) else shown).append(hwnd)
        return True

    user32.EnumWindows(check, 0)
    found = shown or minimized
    return found[0] if found else None


def bring_to_front(hwnd: int) -> bool:
    """Make the window the foreground window, on top of everything else.
    Returns whether it worked."""
    for attempt in range(FOREGROUND_ATTEMPTS):
        if user32.GetForegroundWindow() == hwnd:
            return True
        if attempt == FOREGROUND_ATTEMPTS - 1:
            # Last resort: Windows always lets a window that's being
            # restored from minimized come to the front.
            user32.ShowWindow(hwnd, SW_MINIMIZE)
            user32.ShowWindow(hwnd, SW_RESTORE)
        # Windows only lets the foreground app hand focus to another window;
        # a tap of Alt counts as user input and lifts that restriction, and
        # attaching to the foreground window's input queue borrows its right
        # to do so.
        user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        fg_thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
        our_thread = ctypes.windll.kernel32.GetCurrentThreadId()
        attached = fg_thread != our_thread and user32.AttachThreadInput(
            our_thread, fg_thread, True
        )
        try:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(our_thread, fg_thread, False)
        time.sleep(0.3)
    return user32.GetForegroundWindow() == hwnd


def attach_discord() -> bool:
    """Bring Discord to the front and point screenshots at its window.
    Returns False if Discord isn't open."""
    hwnd = find_discord_window()
    if hwnd is None:
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    if not bring_to_front(hwnd):
        log("NOTE: couldn't bring Discord to the front - make sure no other "
            "window covers it")

    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    # A maximized window's rect pokes a few pixels past the screen edges.
    vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    vw = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    vh = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    left, top = max(rect.left, vx), max(rect.top, vy)
    right, bottom = min(rect.right, vx + vw), min(rect.bottom, vy + vh)
    _region.update(left=left, top=top, width=right - left, height=bottom - top)
    return True


# One mss instance per thread, reused across grabs: creating a new one every
# time is the slowest part of a screenshot. (mss handles are tied to the
# thread that made them, and the GUI runs the bot in a worker thread.)
_sct_local = threading.local()


def grab_screen() -> np.ndarray:
    """Screenshot of the Discord window."""
    sct = getattr(_sct_local, "sct", None)
    if sct is None:
        sct = _sct_local.sct = MSS()
    shot = np.asarray(sct.grab(_region))
    return cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)


def click_at(pos: tuple[int, int]) -> None:
    """Click at a position inside the Discord window screenshot."""
    x, y = _region["left"] + pos[0], _region["top"] + pos[1]
    pyautogui.moveTo(x, y, duration=random.uniform(0.1, 0.25))
    pydirectinput.mouseDown()
    time.sleep(random.uniform(0.04, 0.08))
    pydirectinput.mouseUp()


# --- Reading text (Windows OCR) -----------------------------------------------

@dataclass
class Word:
    text: str
    x: int
    y: int
    w: int
    h: int


_ocr_local = threading.local()


def _ocr_engine() -> OcrEngine:
    engine = getattr(_ocr_local, "engine", None)
    if engine is None:
        # The labels are English, so prefer the English recognizer; fall back
        # to whatever OCR language this PC has.
        engine = OcrEngine.try_create_from_language(Language("en-US"))
        if engine is None:
            engine = OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            raise RuntimeError(
                "Windows text recognition (OCR) isn't available. Add English "
                "in Settings > Time & Language > Language, then restart."
            )
        _ocr_local.engine = engine
    return engine


async def _recognize(bitmap: SoftwareBitmap):
    return await _ocr_engine().recognize_async(bitmap)


def read_text(screen: np.ndarray, scale: int = OCR_SCALE) -> list[list[Word]]:
    """Every line of text on screen, each as its list of words, with
    positions in screen (not upscaled) pixels."""
    big = cv2.resize(screen, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    h, w = big.shape[:2]
    writer = DataWriter()
    writer.write_bytes(cv2.cvtColor(big, cv2.COLOR_BGR2BGRA).tobytes())
    bitmap = SoftwareBitmap.create_copy_from_buffer(
        writer.detach_buffer(), BitmapPixelFormat.BGRA8, w, h
    )
    result = asyncio.run(_recognize(bitmap))
    lines = []
    for line in result.lines:
        words = []
        for word in line.words:
            r = word.bounding_rect
            words.append(Word(
                word.text,
                int(r.x / scale), int(r.y / scale),
                int(r.width / scale), int(r.height / scale),
            ))
        lines.append(words)
    return lines


def read_buttons(screen: np.ndarray) -> list[list[Word]]:
    """Text for finding buttons: a pass tuned for white button labels, plus
    a normal pass in case the labels are dark (light theme)."""
    gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
    ink = np.where(gray >= BUTTON_TEXT_MIN_BRIGHTNESS, 0, 255).astype(np.uint8)
    return read_text(cv2.cvtColor(ink, cv2.COLOR_GRAY2BGR)) + read_text(screen)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def _ocr_key(text: str) -> str:
    """Text reduced for comparing with a label: lowercase letters and digits
    only, with the characters OCR mixes up with "l" (e.g. "lf text" is read
    as "If text") all turned into "l"."""
    text = re.sub(r"[^a-z0-9|]", "", text.lower())
    return re.sub(r"[i1|]", "l", text)


def _label_score(text: str, target: str) -> float:
    """How well OCR'd text matches a label, 0-1; 0 if it doesn't count."""
    text, target = _ocr_key(text), _ocr_key(target)
    if len(target) < FUZZY_LABEL_MIN_LENGTH:
        return 1.0 if text == target else 0.0
    ratio = SequenceMatcher(None, text, target).ratio()
    return ratio if ratio >= LABEL_MATCH_RATIO else 0.0


def _span_center(words: list[Word]) -> tuple[int, int]:
    left = min(w.x for w in words)
    right = max(w.x + w.w for w in words)
    top = min(w.y for w in words)
    bottom = max(w.y + w.h for w in words)
    return (left + right) // 2, (top + bottom) // 2


def find_phrase(lines: list[list[Word]], phrase: str) -> list[tuple[int, int]]:
    """Center of every place the phrase appears, sorted top to bottom. Works
    on runs of words rather than whole lines because OCR often merges
    side-by-side buttons ("LF text" "LF vc") into one line, and sometimes
    runs a label's words together ("LFvc")."""
    target = re.sub(r"[^a-z0-9]", "", phrase.lower())
    max_words = len(phrase.split())
    found = []
    for words in lines:
        i = 0
        while i < len(words):
            # Of the runs starting here, take the best match ("Use legacy"
            # alone is a near-match for "Use legacy bot", but the full run
            # scores higher and centers the click on the whole label).
            best_score, best_n = 0.0, 0
            for n in range(1, min(max_words, len(words) - i) + 1):
                text = "".join(w.text for w in words[i:i + n])
                score = _label_score(text, target)
                if score > best_score:
                    best_score, best_n = score, n
            if best_n:
                found.append(_span_center(words[i:i + best_n]))
                i += best_n
            else:
                i += 1
    return sorted(found, key=lambda p: p[1])


def find_newest(lines: list[list[Word]], phrase: str) -> tuple[int, int] | None:
    """The lowest match on screen. Old copies of the bot's messages (e.g. a
    stale LF menu) stay higher up in the channel, and their buttons no
    longer work, so the newest one is the bottom one."""
    matches = find_phrase(lines, phrase)
    return matches[-1] if matches else None


def find_server_heading(lines: list[list[Word]]) -> tuple[int, int] | None:
    """(left, bottom) of the server's name at the top of the channel list:
    the leftmost copy of SERVER_NAME on screen (another one is centered in
    the title bar), or None if it's not on screen."""
    target = _ocr_key(SERVER_NAME)
    n = len(SERVER_NAME.split())
    best = None
    for words in lines:
        for i in range(len(words) - n + 1):
            run = words[i:i + n]
            if _label_score("".join(w.text for w in run), target):
                pos = (run[0].x, max(w.y + w.h for w in run))
                if best is None or pos[0] < best[0]:
                    best = pos
    return best


def find_channel(lines: list[list[Word]], name: str) -> tuple[int, int] | None:
    """Where the channel's name is in the channel list. The channel list is
    the column under the server's name, so only text there counts (not e.g.
    the "# social" heading over the messages, or the browser tab's title);
    of all lines in it reading as the name, take the closest match."""
    target = _normalize(name)
    heading = find_server_heading(lines)
    best = None
    for words in lines:
        x_left = min(w.x for w in words)
        if heading and (
            x_left > heading[0] + CHANNEL_LIST_MAX_INDENT or words[0].y < heading[1]
        ):
            continue
        raw = " ".join(w.text for w in words)
        # Channel names are always lowercase; a capitalized match is a
        # category header (e.g. the "Social" category above the channels).
        first_letter = re.search(r"[A-Za-z]", raw)
        if first_letter and first_letter.group().isupper() and name.islower():
            continue
        text = _normalize(raw)
        # The "#" channel icon is sometimes read as a stray character.
        candidates = [text, re.sub(r"^[^a-z]+", "", text), text[1:]]
        ratio = max(SequenceMatcher(None, c, target).ratio() for c in candidates)
        if ratio < CHANNEL_MATCH_RATIO:
            continue
        # Best match wins; between equally good ones, the leftmost.
        key = (-ratio, x_left)
        if best is None or key < best[0]:
            best = (key, _span_center(words))
    return best[1] if best else None


def find_blurple_buttons(screen: np.ndarray) -> list[tuple[int, int, int, int]]:
    """(x, y, w, h) of every blurple button on screen."""
    b, g, r = (screen[:, :, i].astype(np.int16) for i in range(3))
    mask = (
        (b >= BUTTON_MIN_BLUE)
        & (b - r >= BUTTON_MIN_BLUE_OVER_RED)
        & (b - g >= BUTTON_MIN_BLUE_OVER_GREEN)
    ).astype(np.uint8) * 255
    # Fill in the label's letters so each button is one solid blob.
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    buttons = []
    for x, y, w, h, _ in stats[1:]:
        if (BUTTON_MIN_SIZE[0] <= w <= BUTTON_MAX_SIZE[0]
                and BUTTON_MIN_SIZE[1] <= h <= BUTTON_MAX_SIZE[1] and w > h):
            buttons.append((int(x), int(y), int(w), int(h)))
    return buttons


def read_button_label(
    screen: np.ndarray, rect: tuple[int, int, int, int],
    min_brightness: int, scale: int, padding: int,
) -> str:
    """OCR one button's label on its own: white text turned black on a
    plain white background, with some margin, zoomed in."""
    x, y, w, h = rect
    gray = cv2.cvtColor(screen[y:y + h, x:x + w], cv2.COLOR_BGR2GRAY)
    ink = np.where(gray >= min_brightness, 0, 255).astype(np.uint8)
    ink = cv2.copyMakeBorder(ink, *[padding] * 4, cv2.BORDER_CONSTANT, value=255)
    lines = read_text(cv2.cvtColor(ink, cv2.COLOR_GRAY2BGR), scale=scale)
    return " ".join(w.text for words in lines for w in words)


def _lf_button_name(text: str) -> str | None:
    """Which LF_LABELS button some OCR'd label is, or None. Only the word
    after "LF" is compared: OCR reads that "lf" as "If", "tf", "Tf"..."""
    rest = re.sub(r"^[lt]?f", "", _ocr_key(text))
    for name, label in LF_LABELS.items():
        if rest == _ocr_key(label.split()[-1]):
            return name
    return None


def identify_lf_button(screen: np.ndarray, rect: tuple[int, int, int, int]) -> str | None:
    """Read one button, trying each BUTTON_OCR_SETTINGS until it reads as
    an LF button we want."""
    for min_brightness, scale, padding in BUTTON_OCR_SETTINGS:
        name = _lf_button_name(read_button_label(screen, rect, min_brightness, scale, padding))
        if name:
            return name
    return None


def find_lf_buttons(screen: np.ndarray) -> dict[str, tuple[int, int]]:
    """Where the newest (lowest) "LF text" / "LF vc" buttons are, from the
    lowest row of blurple buttons that has either."""
    rows: list[list[tuple[int, int, int, int]]] = []
    for rect in sorted(find_blurple_buttons(screen), key=lambda r: (r[1], r[0])):
        if rows and abs(rows[-1][0][1] - rect[1]) <= BUTTON_ROW_TOLERANCE:
            rows[-1].append(rect)
        else:
            rows.append([rect])

    for row in reversed(rows):
        row.sort()
        found: dict[str, tuple[int, int]] = {}
        names = [identify_lf_button(screen, rect) for rect in row]
        for name, (x, y, w, h) in zip(names, row):
            if name and name not in found:
                found[name] = (x + w // 2, y + h // 2)
        # The bot always lays its buttons out as "lf text, lf duo, lf vc,
        # lf friends, ...", so if OCR only managed one of the two, the other
        # is where that order puts it.
        if len(found) == 1:
            (known,) = found
            if names.index(known) == LF_BUTTON_ORDER[known]:
                for name, index in LF_BUTTON_ORDER.items():
                    if name not in found and index < len(row):
                        x, y, w, h = row[index]
                        found[name] = (x + w // 2, y + h // 2)
        if found:
            return found
    return {}


# --- Bot ------------------------------------------------------------------

def search_channel_list(lines: list[list[Word]], name: str) -> tuple[int, int] | None:
    """Scroll the channel list to find a channel that's out of view: all the
    way up, then down a bit at a time until the channel shows. Finds the
    list by the server's name heading it. Returns the channel's position, or
    None if it's not found (or the list isn't on screen)."""
    heading = find_server_heading(lines)
    if heading is None:
        return None
    x, y = heading
    pyautogui.moveTo(
        _region["left"] + x, _region["top"] + y + CHANNEL_LIST_SCROLL_OFFSET_Y
    )
    for _ in range(CHANNEL_LIST_SCROLLS):
        pyautogui.scroll(-SCROLL_WHEEL_AMOUNT)
        time.sleep(SCROLL_CHECK_INTERVAL_SECONDS)
    wait_for_screen_settle()
    for _ in range(CHANNEL_LIST_MAX_STEPS):
        screen = grab_screen()
        pos = find_channel(read_text(screen), name)
        if pos or STOP_EVENT.is_set():
            return pos
        pyautogui.scroll(CHANNEL_LIST_STEP_AMOUNT)
        wait_for_screen_settle()
        if np.array_equal(grab_screen(), screen):
            return None  # reached the bottom of the list
    return find_channel(read_text(grab_screen()), name)


def open_server() -> None:
    """Jump to SERVER_NAME with Discord's quick switcher (Ctrl+K; a leading
    "*" searches servers only), so its channels show in the channel list."""
    log(f"Channels not on screen - switching Discord to '{SERVER_NAME}'...")
    pyautogui.hotkey("ctrl", "k")
    time.sleep(0.4)
    pyautogui.write("*" + SERVER_NAME, interval=0.02)
    time.sleep(0.4)
    pyautogui.press("enter")
    wait_for_screen_settle()


def wait_for_screen_settle() -> None:
    """Wait (up to SETTLE_TIMEOUT_SECONDS) for the screen to stop changing,
    e.g. a smooth scroll or a closing popup to finish."""
    deadline = time.monotonic() + SETTLE_TIMEOUT_SECONDS
    previous = None
    while time.monotonic() < deadline and not STOP_EVENT.is_set():
        STOP_EVENT.wait(SETTLE_POLL_SECONDS)
        screen = grab_screen()
        if previous is not None and np.array_equal(screen, previous):
            return
        previous = screen


def switch_to_tab(pos: tuple[int, int]) -> None:
    before = grab_screen()
    for attempt in range(TAB_CLICK_MAX_ATTEMPTS):
        click_at(pos)
        if wait_for_screen_change(before):
            break
        log(f"NOTE: click at {pos} didn't change the screen, retrying tab click...")

    x = max(_region["width"] - PANE_RIGHT_MARGIN, pos[0] + PANE_MIN_OFFSET_X)
    _pane_pos[:] = [x, _region["height"] // 2]
    click_at(tuple(_pane_pos))
    pydirectinput.press("esc")

    # scroll_to_bottom waits for the screen to settle, which also covers
    # the channel finishing loading.
    scroll_to_bottom()


# Where in the window the message pane is clicked to give it focus.
_pane_pos: list[int] = []


def wait_for_screen_change(before: np.ndarray) -> bool:
    deadline = time.monotonic() + TAB_SWITCH_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(TAB_SWITCH_POLL_SECONDS)
        if not np.array_equal(before, grab_screen()):
            return True
    return False


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


# When an LF button was last clicked in each channel (time.monotonic()).
lf_click_times: dict[str, float] = {}


def check_and_click_tab(tab_name: str) -> bool:
    """Switch to one channel, scroll to bottom, click "Use legacy bot", then
    click an LF button once it pops out. Retries the whole thing until the
    post is confirmed (or TAB_MAX_ATTEMPTS runs out). Returns True if an LF
    button was clicked."""
    lines = read_text(grab_screen())
    tab_pos = find_channel(lines, tab_name)
    if tab_pos is None:
        tab_pos = search_channel_list(lines, tab_name)
    if tab_pos is None:
        # Probably on a DM or another server: go to the right one, then look
        # again.
        open_server()
        lines = read_text(grab_screen())
        tab_pos = find_channel(lines, tab_name) or search_channel_list(lines, tab_name)
    if tab_pos is None:
        log(f"NOTE: could not find channel '{tab_name}' in Discord, skipping it")
        return False

    switch_to_tab(tab_pos)

    lf_clicked = False
    for attempt in range(1, TAB_MAX_ATTEMPTS + 1):
        if STOP_EVENT.is_set():
            return lf_clicked
        if attempt > 1:
            log(f"[{tab_name}] retrying (attempt {attempt}/{TAB_MAX_ATTEMPTS})...")
            STOP_EVENT.wait(RETRY_DELAY_SECONDS)
            scroll_to_bottom()

        screen = grab_screen()
        lf_before = find_lf_buttons(screen)
        legacy_pos = find_newest(read_buttons(screen), LEGACY_LABEL)
        if legacy_pos is None:
            log(f"[{tab_name}] '{LEGACY_LABEL}' not on screen")
            continue
        log(f"[{tab_name}] clicking '{LEGACY_LABEL}' at {legacy_pos}")
        click_at(legacy_pos)

        found = wait_for_lf_buttons(lf_before)
        if not found:
            log(f"[{tab_name}] LF buttons didn't pop out after '{LEGACY_LABEL}'")
            continue

        choice = random.choice(list(found.keys()))
        pos = found[choice]
        log(f"[{tab_name}] found buttons {list(found.keys())} -> clicking '{choice}' at {pos}")
        highlights_before = find_highlighted_rows(grab_screen())
        click_at(pos)
        lf_click_times[tab_name] = time.monotonic()
        lf_clicked = True

        if wait_for_success(highlights_before):
            log(f"[{tab_name}] SUCCESS: '{choice}' was posted")
            return True
        log(f"[{tab_name}] clicked '{choice}' but no highlighted post showed up")

    log(f"[{tab_name}] GAVE UP after {TAB_MAX_ATTEMPTS} attempts, moving on")
    return lf_clicked


def find_highlighted_rows(screen: np.ndarray) -> list[tuple[int, int]]:
    """Locate messages Discord highlights because they mention you (gold
    left bar on a tinted background), returned as (x, bottom_y) pairs."""
    target = np.array(HIGHLIGHT_BAR_BGR, dtype=np.int16)
    lower = np.clip(target - HIGHLIGHT_COLOR_TOLERANCE, 0, 255).astype(np.uint8)
    upper = np.clip(target + HIGHLIGHT_COLOR_TOLERANCE, 0, 255).astype(np.uint8)
    mask = cv2.inRange(screen, lower, upper)
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    rows = []
    for x, y, w, h, _ in stats[1:]:
        if h < HIGHLIGHT_BAR_MIN_HEIGHT or w > HIGHLIGHT_BAR_MAX_WIDTH:
            continue
        sample_x = min(x + w + HIGHLIGHT_BG_SAMPLE_OFFSET, screen.shape[1] - 1)
        blue, _, red = screen[y + h // 2, sample_x].astype(np.int16)
        if red - blue >= HIGHLIGHT_BG_MIN_WARMTH:
            rows.append((int(x), int(y + h)))
    return sorted(rows)


def wait_for_success(highlights_before: list[tuple[int, int]]) -> bool:
    """After clicking an LF button, wait for the bot's post to appear. A new
    post adds a highlighted row and pushes older ones up, so a change in
    where those sit on screen means it went through."""
    deadline = time.monotonic() + SUCCESS_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if STOP_EVENT.is_set():
            return False
        highlights = find_highlighted_rows(grab_screen())
        if highlights and highlights != highlights_before:
            return True
        STOP_EVENT.wait(SUCCESS_POLL_SECONDS)
    return False


def wait_for_lf_buttons(
    lf_before: dict[str, tuple[int, int]],
) -> dict[str, tuple[int, int]]:
    """Poll the screen until a fresh set of LF buttons pops out after
    clicking "Use legacy bot". lf_before is what was already on screen (an
    old, dead menu), which doesn't count. If nothing new shows up, scroll to
    the bottom once (in case it appeared below the visible area) and check
    again."""
    deadline = time.monotonic() + LEGACY_POPUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if STOP_EVENT.is_set():
            return {}
        found = find_lf_buttons(grab_screen())
        if found and found != lf_before:
            return found
        STOP_EVENT.wait(LEGACY_POPUP_POLL_SECONDS)

    scroll_to_bottom()
    found = find_lf_buttons(grab_screen())
    return found if found != lf_before else {}


def run_cycle() -> bool | None:
    """One pass over every channel, clicking an LF button on each where
    present, with a short gap between channels. Returns True if any button
    was clicked, or None if Discord isn't open."""
    clicked_any = False
    for i, tab_name in enumerate(CHANNELS):
        if STOP_EVENT.is_set():
            break
        if not attach_discord():
            return None
        if check_and_click_tab(tab_name):
            clicked_any = True
            if TAB_GAP_SECONDS and i < len(CHANNELS) - 1:
                STOP_EVENT.wait(TAB_GAP_SECONDS)
    return clicked_any


def next_interval() -> float:
    return INTERVAL_CENTER_SECONDS + random.uniform(
        -INTERVAL_JITTER_SECONDS, INTERVAL_JITTER_SECONDS
    )


def time_until_next_cycle(cycle_start: float) -> float:
    """How long to wait so the next cycle clicks in the first channel
    next_interval() after this cycle's click there. Getting from the start
    of a cycle to that click takes a few seconds (switching channel,
    scrolling, the popup), so the next cycle starts that much earlier. If
    there was no click there this cycle, counts from the start of the
    cycle instead."""
    first_click = lf_click_times.get(CHANNELS[0], 0.0)
    if first_click >= cycle_start:
        lead = first_click - cycle_start
        next_click = first_click + next_interval()
        log(f"[{CHANNELS[0]}] next click due {next_click - time.monotonic():.0f}s from now")
        return max(0.0, next_click - lead - time.monotonic())
    return max(0.0, cycle_start + next_interval() - time.monotonic())


def main() -> None:
    STOP_EVENT.clear()
    _ocr_engine()  # fail fast if this PC has no OCR language
    log("Discord LF auto-clicker started. Press Ctrl+C to stop.")

    loop_count = 0
    while not STOP_EVENT.is_set():
        loop_count += 1
        cycle_start = time.monotonic()
        clicked_any = run_cycle()
        if STOP_EVENT.is_set():
            break
        if clicked_any is None:
            log(f"Discord isn't open - checking again in {DISCORD_RETRY_SECONDS}s...")
            STOP_EVENT.wait(DISCORD_RETRY_SECONDS)
        elif clicked_any:
            wait_s = time_until_next_cycle(cycle_start)
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
