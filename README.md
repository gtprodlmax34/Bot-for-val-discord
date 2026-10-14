# discordlf

A screen-watching auto-clicker for a Discord server's "Social Posting" bot message
(posted by the **Valcord** app). That message shows a row of buttons — `LF text`,
`LF duo`, `LF vc`, `LF friends`, `LF <pick game>` — with a per-account cooldown
between clicks. This project cycles through four channels, scrolling each to
the bottom and clicking either `LF text` or `LF vc` when the message is found
(a few seconds apart, channel-to-channel), then starts the cycle over so
that it clicks in **social** again 3 minutes after its last click there, so the user doesn't have to babysit it.

It works purely by **reading the screen** — it finds the Discord window and
reads its text with Windows' built-in OCR — and moving the mouse. It does not
use the Discord API, a bot token, or Discord.py, and there's no network access.

**There's nothing to set up.** It finds things by their text ("social",
"Use legacy bot", "LF text"...), not by screenshots of them, so it works for
anyone, at any resolution, display scaling, theme or window size, on any
monitor.

## Why it's built this way

- Discord's ToS restricts client automation, so this intentionally does not
  touch Discord's API or any account tokens — it just simulates a human
  looking at the screen and clicking a button, the same as the user would.
- Only `LF text` and `LF vc` are targeted (not the other LF buttons) — this
  was a deliberate choice, not a missing feature.

## How it works (`main.py`)

Each cycle it finds the Discord window — the desktop app or a browser whose
selected tab is Discord, whichever is on top on screen (a minimized one only
if there's no other) — brings it to the front (restoring it if minimized), and goes
through the channels in `CHANNELS` — **social**, **social-eu-18+**,
**social-na-18+**, then **social-other-regions-18+**. For each:

1. OCRs the window and clicks the channel's name in the channel list (only
   text in the column under the server's name counts, and only lowercase —
   so not the **Social** category, the `# social` heading over the
   messages, or a chat message saying "social"), retrying if the screen
   doesn't visibly change. If the channel isn't on screen it scrolls the
   channel list to the top and then down a step at a time looking for it,
   and if that doesn't help (Discord is on a DM or another server) jumps to
   `SERVER_NAME` with the quick switcher (`Ctrl+K`, `*VALORANT LFG`,
   `Enter`) and looks again.
2. Clicks empty space on the right of the message pane to give it keyboard
   focus (then `Esc`, in case that opened anything), and presses `End`
   until the screen stops changing or `SCROLL_MAX_PRESSES` runs out.
3. Clicks the newest (lowest) **Use legacy bot** button on screen (it never
   scrolls up to look for one; if none is on screen it retries) and waits
   up to `LEGACY_POPUP_TIMEOUT_SECONDS`
   for the **lf text** / **lf vc** buttons to pop out, and clicks one at
   random. The buttons are found by their blurple color and each one's label
   is read on its own, zoomed in (reading the whole window misses short
   labels like "vc", and reads "lf" as "If").
4. Confirms success by Discord's mention highlight (gold bar + warm-tinted
   row) appearing on the bot's new post — works for any account and theme.
   Retries up to `TAB_MAX_ATTEMPTS` times if not.

After all the channels, if anything was clicked, it waits until it's time to
start the next cycle: the count starts at the click in the first channel
(**social**), and the next cycle starts early enough to click there again
3 minutes later (it takes a few seconds to get from the start of a cycle to
that click). If nothing was clicked it retries after a short poll delay.

`gui.py` is the same bot behind a start/stop button.<!-- it's what the `.exe` runs. -->

## Setup (from source)

```bash
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe main.py
```

`Ctrl+C` to stop. Or `.venv\Scripts\python.exe gui.py` for the window.

<!--
## Building / sharing the .exe

```powershell
.venv\Scripts\python.exe -m pip install pyinstaller
.\build.ps1
```

Send people just `dist\SigmaMafia.exe`. They open Discord (app or browser) on the
server with the channels and press **START** — that's it.
-->

## Tuning knobs (in `main.py`)

- `CHANNELS` — channel names to cycle through, as shown in the channel list.
- `SERVER_NAME` (default `VALORANT LFG`) — the server those channels are in.
- `CHANNEL_MATCH_RATIO` (default `0.9`) / `LABEL_MATCH_RATIO` — how closely
  OCR'd text must match, to tolerate a misread character. The channel
  setting is strict enough that `social-na-18+` doesn't count as
  `social-eu-18+`.
- `LEGACY_POPUP_TIMEOUT_SECONDS` (default `5`) — how long to wait for the LF
  buttons to pop out after clicking **Use legacy bot** before giving up on
  that channel (it presses `End` once more before giving up).
- `INTERVAL_CENTER_SECONDS` / `INTERVAL_JITTER_SECONDS` (default `180` ± `0`)
  — time from one click in **social** to the next.
- `PANE_RIGHT_MARGIN` (default `320`) — how far in from the window's right
  edge the message pane is clicked to give it keyboard focus before `End`.
- `TAB_GAP_SECONDS` (default `1.5`) — wait between channels.
- `SCROLL_*` — how `End` is repeated until the channel stops scrolling.

## Known limitations

- Works with the Discord desktop app or Discord in a browser (Chrome, Edge,
  Firefox, Opera, Brave, Vivaldi — Discord must be the selected tab). If
  both are open it uses whichever is in front. Needs Windows
  10/11, with an English OCR language (installed by default on English
  Windows; otherwise add English under Settings → Time & Language).
- The channels must be in the channel list, not in a collapsed category.
- It brings Discord to the front every cycle, so nothing should cover it
  while it's clicking.
