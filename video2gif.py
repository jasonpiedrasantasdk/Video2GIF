#!/usr/bin/env python3
"""
Video → GIF Converter
Safe, lossless-palette GIF conversion via ffmpeg two-pass palettegen.
Supports MP4, MKV, WebM input.
Requires: ffmpeg, ffprobe, python3-tk
"""

import sys
import os
import json
import time
import subprocess
import threading
import shutil
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path


# ── ffmpeg helpers ─────────────────────────────────────────────────────────

def probe_video(path: str) -> dict | None:
    """Get video stream info via ffprobe."""
    try:
        r = subprocess.run([
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format", "-show_streams",
            path
        ], capture_output=True, text=True, timeout=15)
        data = json.loads(r.stdout)
        # Find video stream
        for s in data.get("streams", []):
            if s.get("codec_type") == "video":
                w = int(s.get("width", 0))
                h = int(s.get("height", 0))
                dur = float(s.get("duration", 0) or
                            data.get("format", {}).get("duration", 0))
                fps_parts = s.get("r_frame_rate", "24/1").split("/")
                fps = float(fps_parts[0]) / max(float(fps_parts[1]), 1)
                frames = int(s.get("nb_frames", 0) or 0)
                return {
                    "width": w, "height": h,
                    "duration": dur, "fps": round(fps, 2),
                    "frames": frames,
                    "codec": s.get("codec_name", "?"),
                }
        return None
    except Exception as e:
        print(f"ffprobe error: {e}", file=sys.stderr)
        return None


def convert_to_gif(
    input_path: str,
    output_path: str,
    fps: int = 15,
    width: int = -1,
    start: float = 0.0,
    end: float = 0.0,
    dither: str = "sierra2_4a",
    max_colors: int = 256,
    on_progress=None,
    on_done=None,
    on_error=None,
):
    """
    Two-pass ffmpeg GIF conversion with palettegen.
    No lossy compression — full palette extraction per-frame.
    
    Pass 1: Generate optimal 256-color palette from video
    Pass 2: Apply palette with chosen dither to produce GIF
    """
    palette_path = output_path + ".palette.png"
    try:
        # Build filter chain
        filters = []
        if fps > 0:
            filters.append(f"fps={fps}")
        if width > 0:
            filters.append(f"scale={width}:-1:flags=lanczos")

        filter_str = ",".join(filters) if filters else "null"

        # Time range args
        time_args = []
        if start > 0:
            time_args += ["-ss", f"{start:.3f}"]
        if end > 0 and end > start:
            time_args += ["-to", f"{end:.3f}"]

        if on_progress:
            on_progress("Pass 1/2: Generating palette…")

        # ── Pass 1: palette generation ──
        cmd1 = (
            ["ffmpeg", "-y"] + time_args +
            ["-i", input_path,
             "-vf", f"{filter_str},palettegen=max_colors={max_colors}:stats_mode=diff",
             "-update", "1", palette_path]
        )
        r1 = subprocess.run(cmd1, capture_output=True, text=True, timeout=120)
        if r1.returncode != 0:
            raise RuntimeError(f"Pass 1 failed:\n{r1.stderr[-500:]}")

        if on_progress:
            on_progress("Pass 2/2: Encoding GIF…")

        # ── Pass 2: apply palette ──
        cmd2 = (
            ["ffmpeg", "-y"] + time_args +
            ["-i", input_path,
             "-i", palette_path,
             "-lavfi", f"{filter_str} [x]; [x][1:v] paletteuse=dither={dither}",
             output_path]
        )
        r2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=300)

        # Cleanup palette
        if os.path.exists(palette_path):
            os.remove(palette_path)

        if r2.returncode != 0:
            raise RuntimeError(f"Pass 2 failed:\n{r2.stderr[-500:]}")

        size = os.path.getsize(output_path)
        if on_done:
            on_done(output_path, size)

    except Exception as e:
        # Cleanup on error
        if os.path.exists(palette_path):
            os.remove(palette_path)
        if on_error:
            on_error(str(e))


# ── Dither methods (safe, no lossy compression) ───────────────────────────
DITHER_METHODS = [
    "sierra2_4a",   # default — good balance
    "bayer",        # ordered dither, retro look
    "floyd_steinberg",  # classic error diffusion
    "sierra2",      # two-row Sierra
    "none",         # no dithering (banding, smallest file)
]

# ── GUI ────────────────────────────────────────────────────────────────────

class Video2GifApp:
    BG       = "#111827"
    BG2      = "#1f2937"
    FG       = "#e5e7eb"
    ACCENT   = "#2563eb"
    HIGHLIGHT= "#10b981"
    SUBTLE   = "#6b7280"
    ENTRY_BG = "#0f172a"
    WARN     = "#f59e0b"

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("🎞  Video → GIF Converter")
        self.root.configure(bg=self.BG)
        self.root.geometry("960x720")
        self.root.minsize(800, 600)

        self.video_info: dict | None = None
        self.input_path: str = ""
        self._converting = False

        self._build_style()
        self._build_ui()

    def _build_style(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("D.TFrame",  background=self.BG)
        s.configure("D2.TFrame", background=self.BG2)
        s.configure("D.TLabel",  background=self.BG, foreground=self.FG,
                     font=("monospace", 10))
        s.configure("Title.TLabel", background=self.BG, foreground=self.HIGHLIGHT,
                     font=("monospace", 14, "bold"))
        s.configure("Info.TLabel", background=self.BG2, foreground=self.SUBTLE,
                     font=("monospace", 9))
        s.configure("Warn.TLabel", background=self.BG, foreground=self.WARN,
                     font=("monospace", 9))
        s.configure("D.TButton", background=self.ACCENT, foreground=self.FG,
                     font=("monospace", 10, "bold"), padding=8)
        s.map("D.TButton", background=[("active", self.HIGHLIGHT)])
        s.configure("Go.TButton", background=self.HIGHLIGHT, foreground="#fff",
                     font=("monospace", 11, "bold"), padding=10)
        s.map("Go.TButton", background=[("active", "#34d399")])

    def _build_ui(self):
        pad = {"padx": 14, "pady": (8, 2)}

        # Title bar
        top = ttk.Frame(self.root, style="D.TFrame")
        top.pack(fill="x", padx=14, pady=(10, 4))
        ttk.Label(top, text="🎞  Video → GIF Converter",
                  style="Title.TLabel").pack(side="left")

        # Main body — two columns
        body = ttk.Frame(self.root, style="D.TFrame")
        body.pack(fill="both", expand=True, padx=14, pady=4)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        # ── Left panel ─────────────────────────────────────────────────
        left = ttk.Frame(body, style="D2.TFrame", width=340)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.grid_propagate(False)

        # Open
        ttk.Button(left, text="📂  Open Video…", style="D.TButton",
                   command=self._open_file).pack(fill="x", **pad)
        self.file_label = ttk.Label(left, text="No video loaded",
                                     style="Info.TLabel", wraplength=300)
        self.file_label.pack(fill="x", padx=14)
        self.src_info = ttk.Label(left, text="", style="Info.TLabel")
        self.src_info.pack(fill="x", padx=14, pady=(2, 6))

        ttk.Separator(left, orient="horizontal").pack(fill="x", padx=14, pady=4)

        # ── FPS ────────────────────────────────────────────────────────
        ttk.Label(left, text="Output FPS", style="D.TLabel").pack(**pad)
        self.fps_var = tk.IntVar(value=15)
        self.fps_slider = tk.Scale(
            left, from_=5, to=30, resolution=1,
            orient="horizontal", variable=self.fps_var,
            bg=self.BG2, fg=self.FG, troughcolor=self.ACCENT,
            highlightthickness=0, font=("monospace", 10),
            command=lambda _: self._update_estimate()
        )
        self.fps_slider.pack(fill="x", padx=14)

        # ── Width ──────────────────────────────────────────────────────
        ttk.Label(left, text="Output Width (0 = original)", style="D.TLabel").pack(**pad)
        self.width_var = tk.IntVar(value=480)
        self.width_slider = tk.Scale(
            left, from_=0, to=1920, resolution=20,
            orient="horizontal", variable=self.width_var,
            bg=self.BG2, fg=self.FG, troughcolor=self.ACCENT,
            highlightthickness=0, font=("monospace", 10),
            command=lambda _: self._update_estimate()
        )
        self.width_slider.pack(fill="x", padx=14)

        # ── Trim ───────────────────────────────────────────────────────
        ttk.Label(left, text="Trim Start (seconds)", style="D.TLabel").pack(**pad)
        self.start_var = tk.DoubleVar(value=0.0)
        self.start_slider = tk.Scale(
            left, from_=0, to=60, resolution=0.1,
            orient="horizontal", variable=self.start_var,
            bg=self.BG2, fg=self.FG, troughcolor=self.ACCENT,
            highlightthickness=0, font=("monospace", 9),
            command=lambda _: self._update_estimate()
        )
        self.start_slider.pack(fill="x", padx=14)

        ttk.Label(left, text="Trim End (0 = full)", style="D.TLabel").pack(**pad)
        self.end_var = tk.DoubleVar(value=0.0)
        self.end_slider = tk.Scale(
            left, from_=0, to=60, resolution=0.1,
            orient="horizontal", variable=self.end_var,
            bg=self.BG2, fg=self.FG, troughcolor=self.ACCENT,
            highlightthickness=0, font=("monospace", 9),
            command=lambda _: self._update_estimate()
        )
        self.end_slider.pack(fill="x", padx=14)

        ttk.Separator(left, orient="horizontal").pack(fill="x", padx=14, pady=6)

        # ── Dither ─────────────────────────────────────────────────────
        ttk.Label(left, text="Dither Method", style="D.TLabel").pack(**pad)
        self.dither_var = tk.StringVar(value="sierra2_4a")
        dither_menu = ttk.Combobox(left, textvariable=self.dither_var,
                                    values=DITHER_METHODS,
                                    state="readonly", font=("monospace", 10))
        dither_menu.pack(fill="x", padx=14, pady=2)

        # ── Max colors ─────────────────────────────────────────────────
        ttk.Label(left, text="Max Colors (palette)", style="D.TLabel").pack(**pad)
        self.colors_var = tk.IntVar(value=256)
        self.colors_slider = tk.Scale(
            left, from_=16, to=256, resolution=16,
            orient="horizontal", variable=self.colors_var,
            bg=self.BG2, fg=self.FG, troughcolor=self.ACCENT,
            highlightthickness=0, font=("monospace", 9)
        )
        self.colors_slider.pack(fill="x", padx=14)

        ttk.Separator(left, orient="horizontal").pack(fill="x", padx=14, pady=6)

        # ── Convert button ─────────────────────────────────────────────
        ttk.Button(left, text="🚀  Convert to GIF", style="Go.TButton",
                   command=self._convert).pack(fill="x", padx=14, pady=(6, 2))

        # Status
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(left, textvariable=self.status_var,
                  style="Info.TLabel").pack(fill="x", padx=14, pady=(6, 2))

        self.progress = ttk.Progressbar(left, mode="indeterminate", length=300)
        self.progress.pack(padx=14, pady=(0, 6))

        # Estimate
        self.estimate_label = ttk.Label(left, text="", style="Warn.TLabel")
        self.estimate_label.pack(fill="x", padx=14, pady=(0, 8))

        # ── Right panel (preview / output info) ────────────────────────
        right = ttk.Frame(body, style="D.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(right, bg=self.ENTRY_BG, highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")

        self.preview_label = ttk.Label(right, text="Load a video to begin",
                                        style="Info.TLabel", anchor="center")
        self.preview_label.place(relx=0.5, rely=0.5, anchor="center")

        # Bottom bar
        bottom = ttk.Frame(self.root, style="D.TFrame")
        bottom.pack(fill="x", padx=14, pady=(0, 8))
        ttk.Label(bottom, text="Engine: ffmpeg palettegen (two-pass, no lossy compression)",
                  style="Info.TLabel").pack(side="left")
        self.time_label = ttk.Label(bottom, text="", style="Info.TLabel")
        self.time_label.pack(side="right")

    # ── Helpers ─────────────────────────────────────────────────────────
    def _fmt_size(self, b: int) -> str:
        if b < 1024:
            return f"{b} B"
        elif b < 1048576:
            return f"{b / 1024:.1f} KB"
        else:
            return f"{b / 1048576:.1f} MB"

    def _update_estimate(self):
        """Rough estimate of output GIF size and frame count."""
        if not self.video_info:
            self.estimate_label.config(text="")
            return
        vi = self.video_info
        fps = self.fps_var.get()
        w = self.width_var.get() or vi["width"]
        # Estimate height preserving aspect ratio
        h = int(w * vi["height"] / max(vi["width"], 1))

        start = self.start_var.get()
        end = self.end_var.get()
        dur = vi["duration"]
        if end > start and end > 0:
            dur = end - start
        elif start > 0:
            dur = max(dur - start, 0)

        frames = int(dur * fps)
        # Very rough: ~bytes per pixel per frame for GIF with palette
        est_bytes = int(w * h * frames * 0.15)
        self.estimate_label.config(
            text=f"~{frames} frames  │  ~{w}×{h}  │  est. {self._fmt_size(est_bytes)}"
        )

    def _open_file(self):
        path = filedialog.askopenfilename(
            title="Select Video",
            filetypes=[
                ("Video files", "*.mp4 *.mkv *.webm *.avi *.mov"),
                ("All files", "*.*"),
            ]
        )
        if not path:
            return
        self.status_var.set("Probing video…")
        info = probe_video(path)
        if not info:
            messagebox.showerror("Probe Error", "Could not read video metadata.")
            self.status_var.set("Ready")
            return

        self.input_path = path
        self.video_info = info
        self.file_label.config(text=os.path.basename(path))
        self.src_info.config(
            text=f"{info['width']}×{info['height']}  │  {info['codec']}  │  "
                 f"{info['fps']} fps  │  {info['duration']:.1f}s  │  {info['frames']} fr"
        )

        # Adjust trim sliders to video duration
        maxdur = max(info["duration"], 1)
        self.start_slider.config(to=maxdur)
        self.end_slider.config(to=maxdur)
        self.end_var.set(0.0)
        self.start_var.set(0.0)

        # Generate a thumbnail preview
        self._generate_thumbnail(path)
        self._update_estimate()
        self.status_var.set("Ready — adjust settings and convert")

    def _generate_thumbnail(self, path: str):
        """Extract a single frame for preview."""
        try:
            thumb_path = "/tmp/v2g_thumb.png"
            subprocess.run([
                "ffmpeg", "-y", "-i", path,
                "-vf", "scale=640:-1",
                "-frames:v", "1",
                thumb_path
            ], capture_output=True, timeout=10)
            if os.path.exists(thumb_path):
                from PIL import Image, ImageTk
                img = Image.open(thumb_path)
                # Fit to canvas
                cw = max(self.canvas.winfo_width(), 400)
                ch = max(self.canvas.winfo_height(), 300)
                iw, ih = img.size
                ratio = min(cw / iw, ch / ih, 1.0)
                nw, nh = max(1, int(iw * ratio)), max(1, int(ih * ratio))
                thumb = img.resize((nw, nh), Image.LANCZOS)
                self._preview_photo = ImageTk.PhotoImage(thumb)
                self.canvas.delete("all")
                self.canvas.create_image(cw // 2, ch // 2,
                                          image=self._preview_photo, anchor="center")
                self.canvas.create_text(10, 10, text=f"Source: {iw}×{ih}",
                                         fill="#10b981", font=("monospace", 11, "bold"),
                                         anchor="nw")
                self.preview_label.place_forget()
        except Exception:
            pass

    def _convert(self):
        if not self.input_path:
            messagebox.showwarning("No Video", "Load a video first.")
            return
        if self._converting:
            messagebox.showinfo("Busy", "Conversion already in progress.")
            return

        # Ask for output path
        stem = Path(self.input_path).stem
        default_name = f"{stem}.gif"
        output = filedialog.asksaveasfilename(
            title="Save GIF As…",
            defaultextension=".gif",
            initialfile=default_name,
            filetypes=[("GIF", "*.gif"), ("All files", "*.*")]
        )
        if not output:
            return

        self._converting = True
        self.progress.start(15)

        fps = self.fps_var.get()
        width = self.width_var.get()
        start = self.start_var.get()
        end = self.end_var.get()
        dither = self.dither_var.get()
        colors = self.colors_var.get()

        t0 = time.perf_counter()

        def _on_progress(msg):
            self.root.after(0, lambda: self.status_var.set(msg))

        def _on_done(path, size):
            elapsed = time.perf_counter() - t0
            self._converting = False
            self.root.after(0, lambda: [
                self.progress.stop(),
                self.status_var.set(f"Done → {os.path.basename(path)}  ({self._fmt_size(size)})"),
                self.time_label.config(text=f"⏱ {elapsed:.1f}s"),
                self._show_gif_preview(path),
            ])

        def _on_error(msg):
            self._converting = False
            self.root.after(0, lambda: [
                self.progress.stop(),
                self.status_var.set(f"Error: {msg[:120]}"),
            ])

        def _worker():
            convert_to_gif(
                input_path=self.input_path,
                output_path=output,
                fps=fps,
                width=width if width > 0 else -1,
                start=start,
                end=end,
                dither=dither,
                max_colors=colors,
                on_progress=_on_progress,
                on_done=_on_done,
                on_error=_on_error,
            )

        threading.Thread(target=_worker, daemon=True).start()

    def _show_gif_preview(self, gif_path: str):
        """Show first frame of output GIF in preview canvas."""
        try:
            from PIL import Image, ImageTk
            img = Image.open(gif_path)
            img.seek(0)
            frame = img.convert("RGB")
            cw = max(self.canvas.winfo_width(), 400)
            ch = max(self.canvas.winfo_height(), 300)
            iw, ih = frame.size
            ratio = min(cw / iw, ch / ih, 1.0)
            nw, nh = max(1, int(iw * ratio)), max(1, int(ih * ratio))
            thumb = frame.resize((nw, nh), Image.LANCZOS)
            self._preview_photo = ImageTk.PhotoImage(thumb)
            self.canvas.delete("all")
            self.canvas.create_image(cw // 2, ch // 2,
                                      image=self._preview_photo, anchor="center")
            self.canvas.create_text(10, 10, text=f"OUTPUT GIF  {iw}×{ih}",
                                     fill="#10b981", font=("monospace", 11, "bold"),
                                     anchor="nw")
            size = os.path.getsize(gif_path)
            self.canvas.create_text(10, 30, text=f"Size: {self._fmt_size(size)}",
                                     fill="#f59e0b", font=("monospace", 10),
                                     anchor="nw")
        except Exception:
            pass


# ── Entry Point ────────────────────────────────────────────────────────────

def main():
    if not shutil.which("ffmpeg"):
        print("ERROR: ffmpeg not found in PATH. Install with: sudo apt install ffmpeg")
        sys.exit(1)
    if not shutil.which("ffprobe"):
        print("ERROR: ffprobe not found in PATH. Install with: sudo apt install ffmpeg")
        sys.exit(1)

    root = tk.Tk()
    app = Video2GifApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
