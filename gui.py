"""
GUI wrapper for the Discord LF-button auto-clicker.

Gives you one big power button to start/stop the bot instead of running
main.py from a terminal every time.
"""
# Build a standalone .exe with build.ps1.
import queue
import threading
import tkinter as tk
from tkinter import scrolledtext

import main as bot

IDLE_COLOR = "#2ecc71"      # green - ready to start
IDLE_COLOR_DARK = "#27ae60"
RUNNING_COLOR = "#e74c3c"   # red - click to stop
RUNNING_COLOR_DARK = "#c0392b"
STOPPING_COLOR = "#95a5a6"  # grey - stop requested, winding down
BG_COLOR = "#1e1f24"
PANEL_COLOR = "#26272e"
TEXT_COLOR = "#e8e8ea"


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Sigma Mafia")
        self.root.configure(bg=BG_COLOR)
        self.root.geometry("460x420")
        self.root.minsize(380, 340)

        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.worker: threading.Thread | None = None
        self.stopping = False

        bot.log = self._enqueue_log

        title = tk.Label(
            root,
            text="SIGMA MAFIA",
            font=("Segoe UI", 13, "bold"),
            fg=TEXT_COLOR,
            bg=BG_COLOR,
        )
        title.pack(pady=(16, 4))

        self.status_var = tk.StringVar(value="Idle")
        status = tk.Label(
            root,
            textvariable=self.status_var,
            font=("Segoe UI", 10),
            fg="#9a9aa5",
            bg=BG_COLOR,
        )
        status.pack(pady=(0, 10))

        self.canvas = tk.Canvas(
            root, width=140, height=140, bg=BG_COLOR, highlightthickness=0
        )
        self.canvas.pack(pady=4)
        self.canvas.bind("<Button-1>", self._on_button_click)
        self.canvas.bind("<Enter>", lambda e: self.canvas.config(cursor="hand2"))

        self._draw_button(IDLE_COLOR, IDLE_COLOR_DARK, "START")

        log_frame = tk.Frame(root, bg=BG_COLOR)
        log_frame.pack(fill="both", expand=True, padx=14, pady=(14, 14))

        self.log_box = scrolledtext.ScrolledText(
            log_frame,
            bg=PANEL_COLOR,
            fg=TEXT_COLOR,
            insertbackground=TEXT_COLOR,
            font=("Consolas", 9),
            relief="flat",
            wrap="word",
            state="disabled",
        )
        self.log_box.pack(fill="both", expand=True)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._drain_log_queue)

    def _draw_button(self, fill: str, shade: str, label: str) -> None:
        self.canvas.delete("all")
        self.canvas.create_oval(6, 6, 134, 134, fill=shade, outline="")
        self.canvas.create_oval(10, 10, 130, 130, fill=fill, outline="")
        self.canvas.create_oval(18, 18, 122, 60, fill="", outline="")
        self.canvas.create_text(
            70, 70, text=label, fill="white", font=("Segoe UI", 14, "bold")
        )

    def _enqueue_log(self, message: str) -> None:
        self.log_queue.put(str(message))

    def _drain_log_queue(self) -> None:
        try:
            while True:
                message = self.log_queue.get_nowait()
                self.log_box.configure(state="normal")
                self.log_box.insert("end", message + "\n")
                self.log_box.see("end")
                self.log_box.configure(state="disabled")
        except queue.Empty:
            pass

        if self.worker is not None and not self.worker.is_alive():
            self.worker = None
            self.stopping = False
            self.status_var.set("Idle")
            self._draw_button(IDLE_COLOR, IDLE_COLOR_DARK, "START")

        self.root.after(100, self._drain_log_queue)

    def _on_button_click(self, _event: object) -> None:
        if self.worker is None:
            self._start()
        elif not self.stopping:
            self._stop()

    def _start(self) -> None:
        self.status_var.set("Running - click to stop")
        self._draw_button(RUNNING_COLOR, RUNNING_COLOR_DARK, "STOP")
        self.worker = threading.Thread(target=self._run_bot, daemon=True)
        self.worker.start()

    def _run_bot(self) -> None:
        try:
            bot.main()
        except SystemExit:
            pass
        except Exception as exc:  # surface crashes in the log instead of silently dying
            self._enqueue_log(f"ERROR: {exc}")

    def _stop(self) -> None:
        self.stopping = True
        self.status_var.set("Stopping...")
        self._draw_button(STOPPING_COLOR, STOPPING_COLOR, "...")
        bot.STOP_EVENT.set()

    def _on_close(self) -> None:
        bot.STOP_EVENT.set()
        self.root.after(200, self.root.destroy)


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
