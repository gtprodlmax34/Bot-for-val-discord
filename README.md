# discordlf

A screen-watching auto-clicker for a Discord server's "Social Posting" bot message
(posted by the **Valcord** app). That message shows a row of buttons — `LF text`,
`LF duo`, `LF vc`, `LF friends`, `LF <pick game>` — with a per-account cooldown
between clicks. This project cycles between two channel tabs, scrolling each to
the bottom and clicking either `LF text` or `LF vc` when the message is found
(a few seconds apart, tab-to-tab), then waits a randomized ~3:20 interval
before starting the cycle over, so the user doesn't have to babysit it.

It works purely by **pixel matching on screenshots** — it does not use the
Discord API, a bot token, or Discord.py. There is no network access involved
at all; everything happens by reading the screen and moving the mouse.

## Why it's built this way

- Discord's ToS restricts client automation, so this intentionally does not
  touch Discord's API or any account tokens — it just simulates a human
  looking at the screen and clicking a button, the same as the user would.
- Only `LF text` and `LF vc` are targeted (not the other LF buttons) — this
  was a deliberate choice, not a missing feature.

## Files

- **`main.py`** — the bot loop. Each cycle goes through both channel tabs in
  order, **social** (`templates/tab1.png`) then **social-eu-18+**
  (`templates/tab2.png`): for each, it finds and clicks the tab (retrying if
  the screen doesn't visibly change), then clicks again `FOCUS_CLICK_OFFSET_X`
  pixels to the right of it to move keyboard focus off the channel list and
  into the message pane — otherwise `End` does nothing. It then holds `End` —
  repeatedly pressing it and re-screenshotting until the screen stops
  changing — so it reliably reaches the actual bottom of scrollback rather
  than just firing `End` once. It then grabs the screen (via `mss`) and looks
  for `templates/lf_text.png` and `templates/lf_vc.png` with OpenCV template
  matching, randomly clicking whichever is present. If a button was clicked
  on a tab, it waits `TAB_GAP_SECONDS` (a few seconds) before moving to the
  next tab. Once both tabs have been checked, if at least one button was
  clicked it sleeps a randomized interval (~3:00–3:40) before starting the
  cycle over from the first tab; if neither tab had a button yet, it retries
  the whole cycle again after a short poll delay instead of waiting that long.
- **`capture_templates.py`** — a one-time interactive helper. Prompts the
  user to hover the mouse over each button's/tab's corners and press Enter,
  then crops and saves `templates/lf_text.png`, `templates/lf_vc.png`,
  `templates/tab1.png`, and `templates/tab2.png` from the user's actual
  screen. **Must be run before `main.py` will work** — `templates/` is empty
  until this has been run at least once.
- **`templates/`** — cropped reference images of the LF buttons and the two
  channel tabs, at the user's own screen resolution/DPI/theme. Not portable
  between machines or Discord themes — regenerate with `capture_templates.py`
  if matching fails after a display/resolution/theme change.

## Setup

Dependencies live in the project's `.venv` (already created): `pyautogui`,
`opencv-python`, `mss`, `pillow`, `numpy`, `pydirectinput`. If the venv needs
to be rebuilt:

```bash
.venv\Scripts\python.exe -m pip install pyautogui opencv-python mss pillow pydirectinput
```

## Usage

1. Open Discord, scroll the "Social Posting" message into view.
2. Capture the button templates (one-time, or after any UI/resolution change):
   ```bash
   .venv\Scripts\python.exe capture_templates.py
   ```
3. Run the bot:
   ```bash
   .venv\Scripts\python.exe main.py
   ```
4. `Ctrl+C` to stop.

## Tuning knobs (in `main.py`)

- `MATCH_THRESHOLD` (default `0.85`) — OpenCV match confidence, 0–1. Lower it
  (e.g. `0.75`) if the bot fails to find a visible button; raise it if it
  clicks the wrong thing.
- `INTERVAL_CENTER_SECONDS` / `INTERVAL_JITTER_SECONDS` (default `200` ± `20`)
  — the randomized wait between clicks, centered on the button's 3:20 cooldown.
- `POLL_INTERVAL_SECONDS` (default `2`) — how often it cycles through both
  tabs again while waiting for the buttons to appear.
- `TAB_SWITCH_SETTLE_SECONDS` (default `0.5`) — how long to wait after
  clicking a tab before checking whether it switched / pressing `End`.
- `TAB_CLICK_MAX_ATTEMPTS` (default `3`) — how many times to retry clicking
  a tab if the screen doesn't visibly change (i.e. Discord didn't register
  the click as a channel switch).
- `FOCUS_CLICK_OFFSET_X` (default `300`) — pixels to the right of the tab to
  click after switching, so keyboard focus moves into the message pane
  before `End` is pressed. Adjust if this still lands outside the message
  area on your layout.
- `TAB_GAP_SECONDS` (default `3`) — how long to wait after clicking a button
  on one tab before moving on to check the other tab.
- `SCROLL_CHECK_INTERVAL_SECONDS` (default `0.3`) — delay between each `End`
  press while scrolling, before re-checking whether the screen changed.
- `SCROLL_STABLE_CHECKS` (default `2`) — how many consecutive unchanged
  screenshots mean "reached the bottom".
- `SCROLL_MAX_PRESSES` (default `15`) — safety cap on `End` presses per tab,
  in case the screen never stabilizes (e.g. very active chat).
- If clicks aren't registering in Discord, swap `pyautogui.click()` for
  `pydirectinput.click()` in `click_at()` — some Electron apps ignore
  `pyautogui`'s synthetic input but accept `pydirectinput`'s lower-level events.

## Known limitations

- Requires the Discord window with the LF message to be visible and
  unobstructed on screen — this is pixel-based, not headless.
- If the "Social Posting" message gets reposted (deleted + re-sent further
  down the channel, e.g. after every 5-6 new messages) and an old, no-longer-
  functional copy is still visible higher up in the scrollback, template
  matching has no way to tell old from new — `cv2.minMaxLoc` just returns
  the single best match on screen, which could be the stale copy. Pressing
  `End` before checking should avoid this in the common case, since it
  scrolls straight to the newest copy.
- Templates are tied to the exact screen resolution/scaling/theme they were
  captured at.
- Not tested end-to-end against a live Discord session yet (no way to see
  the user's screen during development) — if matching doesn't trigger, first
  suspect: templates need recapturing, or `MATCH_THRESHOLD` needs lowering.
