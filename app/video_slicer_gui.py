#!/usr/bin/env python3
"""
video_slicer_gui.py - Simple desktop GUI for slicer_core.

Requires: Python 3.8+ with tkinter (ships with most Python installers;
on some Linux distros install it separately, e.g. `sudo apt install
python3-tk`), plus a local ffmpeg/ffprobe on your PATH.

Run with:
    python3 video_slicer_gui.py
"""

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from slicer_core import SliceOptions, SlicerError, parse_time_to_seconds, run_pipeline

PRESETS = ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"]


class VideoSlicerGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Video Slicer")
        self.geometry("640x620")
        self.minsize(560, 560)

        self._log_queue: "queue.Queue[str]" = queue.Queue()
        self._worker: Optional[threading.Thread] = None

        self._build_widgets()
        self.after(100, self._drain_log_queue)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_widgets(self):
        pad = {"padx": 8, "pady": 4}
        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, padx=10, pady=10)
        frm.columnconfigure(1, weight=1)

        row = 0
        ttk.Label(frm, text="Input video:").grid(row=row, column=0, sticky="w", **pad)
        self.input_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.input_var).grid(row=row, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="Browse...", command=self._pick_input).grid(row=row, column=2, **pad)

        row += 1
        ttk.Label(frm, text="Output folder:").grid(row=row, column=0, sticky="w", **pad)
        self.output_var = tk.StringVar(value=os.path.join(os.getcwd(), "output_parts"))
        ttk.Entry(frm, textvariable=self.output_var).grid(row=row, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="Browse...", command=self._pick_output).grid(row=row, column=2, **pad)

        row += 1
        ttk.Separator(frm).grid(row=row, column=0, columnspan=3, sticky="ew", pady=8)

        row += 1
        ttk.Label(frm, text="Part length:").grid(row=row, column=0, sticky="w", **pad)
        self.length_var = tk.StringVar(value="60")
        ttk.Entry(frm, textvariable=self.length_var, width=12).grid(row=row, column=1, sticky="w", **pad)
        ttk.Label(frm, text="seconds, or MM:SS / HH:MM:SS").grid(row=row, column=2, sticky="w", **pad)

        row += 1
        ttk.Label(frm, text="Overlap between parts:").grid(row=row, column=0, sticky="w", **pad)
        self.overlap_var = tk.StringVar(value="0")
        ttk.Entry(frm, textvariable=self.overlap_var, width=12).grid(row=row, column=1, sticky="w", **pad)
        ttk.Label(frm, text="seconds, or MM:SS / HH:MM:SS").grid(row=row, column=2, sticky="w", **pad)

        row += 1
        ttk.Separator(frm).grid(row=row, column=0, columnspan=3, sticky="ew", pady=8)

        row += 1
        ttk.Label(frm, text="Subtitles (optional):").grid(row=row, column=0, sticky="w", **pad)
        self.subs_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.subs_var).grid(row=row, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="Browse...", command=self._pick_subs).grid(row=row, column=2, **pad)

        row += 1
        ttk.Label(frm, text="Subtitle style (optional):").grid(row=row, column=0, sticky="w", **pad)
        self.sub_style_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.sub_style_var).grid(row=row, column=1, columnspan=2, sticky="ew", **pad)

        row += 1
        ttk.Separator(frm).grid(row=row, column=0, columnspan=3, sticky="ew", pady=8)

        row += 1
        opts_frame = ttk.Frame(frm)
        opts_frame.grid(row=row, column=0, columnspan=3, sticky="ew", **pad)

        self.fast_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            opts_frame, variable=self.fast_var,
            text="Fast mode (stream copy; skip this if you need exact-second cuts)",
        ).pack(side="left")

        row += 1
        prefix_frame = ttk.Frame(frm)
        prefix_frame.grid(row=row, column=0, columnspan=3, sticky="ew", **pad)
        ttk.Label(prefix_frame, text="Filename prefix:").pack(side="left")
        self.prefix_var = tk.StringVar(value="part")
        ttk.Entry(prefix_frame, textvariable=self.prefix_var, width=14).pack(side="left", padx=6)
        ttk.Label(prefix_frame, text="Encode speed:").pack(side="left", padx=(16, 0))
        self.preset_var = tk.StringVar(value="fast")
        ttk.Combobox(prefix_frame, textvariable=self.preset_var, values=PRESETS, width=10, state="readonly").pack(side="left", padx=6)

        row += 1
        self.run_btn = ttk.Button(frm, text="Slice Video", command=self._on_run)
        self.run_btn.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(10, 4))

        row += 1
        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(frm, textvariable=self.status_var).grid(row=row, column=0, columnspan=3, sticky="w", **pad)

        row += 1
        frm.rowconfigure(row, weight=1)
        log_frame = ttk.Frame(frm)
        log_frame.grid(row=row, column=0, columnspan=3, sticky="nsew", **pad)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, height=14, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scroll.set)

    # ------------------------------------------------------------------
    # File pickers
    # ------------------------------------------------------------------
    def _pick_input(self):
        path = filedialog.askopenfilename(
            title="Choose a video file",
            filetypes=[
                ("Video files", "*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.hevc *.ts *.flv"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.input_var.set(path)
            if not self.output_var.get():
                self.output_var.set(os.path.join(os.path.dirname(path), "output_parts"))

    def _pick_output(self):
        path = filedialog.askdirectory(title="Choose an output folder")
        if path:
            self.output_var.set(path)

    def _pick_subs(self):
        path = filedialog.askopenfilename(
            title="Choose a subtitle file",
            filetypes=[("Subtitle files", "*.srt *.ass *.ssa *.vtt"), ("All files", "*.*")],
        )
        if path:
            self.subs_var.set(path)

    # ------------------------------------------------------------------
    # Logging helpers (thread-safe: worker thread pushes to a queue,
    # the Tk main loop drains it on a timer)
    # ------------------------------------------------------------------
    def _log(self, msg: str):
        self._log_queue.put(msg)

    def _drain_log_queue(self):
        try:
            while True:
                msg = self._log_queue.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert("end", msg + "\n")
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._drain_log_queue)

    # ------------------------------------------------------------------
    # Run button / worker thread
    # ------------------------------------------------------------------
    def _on_run(self):
        if self._worker and self._worker.is_alive():
            return

        input_path = self.input_var.get().strip()
        output_dir = self.output_var.get().strip()
        subs_path = self.subs_var.get().strip() or None
        sub_style = self.sub_style_var.get().strip() or None

        if not input_path:
            messagebox.showerror("Missing input", "Please choose an input video.")
            return
        if not output_dir:
            messagebox.showerror("Missing output folder", "Please choose an output folder.")
            return

        try:
            length = parse_time_to_seconds(self.length_var.get().strip())
            overlap = parse_time_to_seconds(self.overlap_var.get().strip())
        except SlicerError as e:
            messagebox.showerror("Invalid time value", str(e))
            return

        opts = SliceOptions(
            input_path=input_path,
            output_dir=output_dir,
            length=length,
            overlap=overlap,
            subtitles_path=subs_path,
            subtitle_style=sub_style,
            fast_copy=self.fast_var.get(),
            prefix=self.prefix_var.get().strip() or "part",
            preset=self.preset_var.get(),
        )

        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self.status_var.set("Working...")
        self.run_btn.configure(state="disabled")

        self._worker = threading.Thread(target=self._run_worker, args=(opts,), daemon=True)
        self._worker.start()

    def _run_worker(self, opts: SliceOptions):
        try:
            out_paths = run_pipeline(opts, log=self._log)
            self._log(f"\nSuccess - {len(out_paths)} file(s) created.")
            self.status_var.set(f"Done. {len(out_paths)} file(s) written to {opts.output_dir}")
        except SlicerError as e:
            self._log(f"\nError: {e}")
            self.status_var.set("Failed - see log below.")
        except Exception as e:  # unexpected errors shouldn't crash the GUI
            self._log(f"\nUnexpected error: {e}")
            self.status_var.set("Failed - see log below.")
        finally:
            self.run_btn.configure(state="normal")


def main():
    app = VideoSlicerGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
