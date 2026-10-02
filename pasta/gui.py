import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import numpy as np

from .config import ENGINES, LANGUAGE_MODES, Config, load_config
from .history_db import get_history_db
from .logging_setup import get_logger
from .startup import disable_startup, enable_startup, is_startup_enabled

log = get_logger("gui")

COLOR_BG = "#09120e"
COLOR_CARD = "#0f1c16"
COLOR_CARD_BORDER = "#1b3327"
COLOR_TEXT = "#f0fdf4"
COLOR_MUTED = "#86a695"
COLOR_ACCENT = "#10b981"
COLOR_ACCENT_HOVER = "#059669"
COLOR_GREEN = "#22c55e"
COLOR_CARD_ALT = "#162820"

WHISPER_MODELS = [
    "large-v3-turbo",
    "large-v3",
    "medium",
    "small",
    "base",
]


class DashboardApp:
    def __init__(self, cfg: Config | None = None, pipeline=None) -> None:
        self.cfg = cfg or load_config()
        self.pipeline = pipeline

        self.root = tk.Tk()
        self.root.title("PASTA V2 — Settings & Dashboard")
        self.root.configure(bg=COLOR_BG)
        self.root.geometry("740x720")
        self.root.minsize(680, 600)

        # Set taskbar icon if available
        self._setup_window_icon()

        # Center window on screen
        self._center_window()

        self._meter_running = False
        self._meter_thread = None

        self._build_ui()
        self._start_audio_meter()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_window_icon(self) -> None:
        try:
            from pathlib import Path

            from PIL import Image, ImageTk

            icon_path = Path(__file__).resolve().parent.parent / "icon.ico"
            if icon_path.exists():
                icon_img = ImageTk.PhotoImage(Image.open(icon_path))
                self.root.iconphoto(True, icon_img)
        except Exception:
            pass

    def _center_window(self) -> None:
        self.root.update_idletasks()
        w = 740
        h = 720
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _build_ui(self) -> None:
        # Style configuration
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=COLOR_CARD_ALT, background=COLOR_CARD_ALT, foreground=COLOR_TEXT)

        main_canvas = tk.Canvas(self.root, bg=COLOR_BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=main_canvas.yview)
        self.scrollable_frame = tk.Frame(main_canvas, bg=COLOR_BG)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: main_canvas.configure(scrollregion=main_canvas.bbox("all")),
        )
        main_canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw", width=720)
        main_canvas.configure(yscrollcommand=scrollbar.set)

        main_canvas.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        scrollbar.pack(side="right", fill="y", pady=10, padx=(0, 5))

        # Header Section
        self._build_header(self.scrollable_frame)

        # Card 1: Engine & Model
        self._build_engine_card(self.scrollable_frame)

        # Card 2: System & Startup
        self._build_system_card(self.scrollable_frame)

        # Card 3: Live Microphone Meter
        self._build_meter_card(self.scrollable_frame)

        # Card 4: Dictation History
        self._build_history_card(self.scrollable_frame)

        # Bottom Actions
        self._build_footer(self.scrollable_frame)

    def _build_header(self, parent: tk.Widget) -> None:
        header_frame = tk.Frame(parent, bg=COLOR_BG)
        header_frame.pack(fill="x", padx=15, pady=(5, 12))

        # Title & Subtitle
        title_frame = tk.Frame(header_frame, bg=COLOR_BG)
        title_frame.pack(side="left")

        title_lbl = tk.Label(
            title_frame,
            text="🌿 PESTO",
            font=("Segoe UI", 18, "bold"),
            fg=COLOR_TEXT,
            bg=COLOR_BG,
        )
        title_lbl.pack(anchor="w")

        sub_lbl = tk.Label(
            title_frame,
            text="Local Push-to-Talk Speech-to-Text · 100% Private · Greek & English",
            font=("Segoe UI", 9),
            fg=COLOR_MUTED,
            bg=COLOR_BG,
        )
        sub_lbl.pack(anchor="w")

        # GPU / CUDA Badge
        cuda_ok = False
        try:
            import ctranslate2

            cuda_ok = ctranslate2.get_cuda_device_count() > 0
        except Exception:
            pass

        badge_text = "⚡ NVIDIA CUDA (Active)" if cuda_ok else "💻 CPU Mode"
        badge_fg = COLOR_GREEN if cuda_ok else COLOR_MUTED
        badge_bg = "#064e3b" if cuda_ok else "#1e293b"

        badge = tk.Label(
            header_frame,
            text=f"  {badge_text}  ",
            font=("Segoe UI", 9, "bold"),
            fg=badge_fg,
            bg=badge_bg,
            relief="flat",
            padx=6,
            pady=4,
        )
        badge.pack(side="right", pady=5)

    def _create_card(self, parent: tk.Widget, title: str) -> tk.Frame:
        container = tk.Frame(parent, bg=COLOR_CARD, highlightbackground=COLOR_CARD_BORDER, highlightthickness=1, padx=16, pady=12)
        container.pack(fill="x", padx=15, pady=8)

        card_title = tk.Label(
            container,
            text=title,
            font=("Segoe UI", 11, "bold"),
            fg=COLOR_ACCENT,
            bg=COLOR_CARD,
        )
        card_title.pack(anchor="w", pady=(0, 10))
        return container

    def _build_engine_card(self, parent: tk.Widget) -> None:
        card = self._create_card(parent, "⚡ ASR Engine & Speech Model")

        # Engine selection
        eng_frame = tk.Frame(card, bg=COLOR_CARD)
        eng_frame.pack(fill="x", pady=4)

        tk.Label(
            eng_frame,
            text="Active Engine:",
            font=("Segoe UI", 10),
            fg=COLOR_TEXT,
            bg=COLOR_CARD,
            width=18,
            anchor="w",
        ).pack(side="left")

        self.engine_var = tk.StringVar(value=self.cfg.engine)
        for eng in ENGINES:
            desc = " (Whisper - High Accuracy)" if eng == "whisper" else " (Parakeet - Ultra Fast)"
            rb = tk.Radiobutton(
                eng_frame,
                text=eng.capitalize() + desc,
                variable=self.engine_var,
                value=eng,
                font=("Segoe UI", 9),
                fg=COLOR_TEXT,
                bg=COLOR_CARD,
                selectcolor=COLOR_CARD_ALT,
                activebackground=COLOR_CARD,
                activeforeground=COLOR_ACCENT,
            )
            rb.pack(side="left", padx=8)

        # Whisper Model selection
        model_frame = tk.Frame(card, bg=COLOR_CARD)
        model_frame.pack(fill="x", pady=4)

        tk.Label(
            model_frame,
            text="Whisper Model:",
            font=("Segoe UI", 10),
            fg=COLOR_TEXT,
            bg=COLOR_CARD,
            width=18,
            anchor="w",
        ).pack(side="left")

        self.model_var = tk.StringVar(value=self.cfg.whisper_model)
        model_combo = ttk.Combobox(
            model_frame,
            textvariable=self.model_var,
            values=WHISPER_MODELS,
            state="readonly",
            width=22,
        )
        model_combo.pack(side="left", padx=8)

        tk.Label(
            model_frame,
            text="(large-v3-turbo recommended for accuracy + speed)",
            font=("Segoe UI", 8),
            fg=COLOR_MUTED,
            bg=COLOR_CARD,
        ).pack(side="left", padx=6)

        # Language selection
        lang_frame = tk.Frame(card, bg=COLOR_CARD)
        lang_frame.pack(fill="x", pady=4)

        tk.Label(
            lang_frame,
            text="Language Mode:",
            font=("Segoe UI", 10),
            fg=COLOR_TEXT,
            bg=COLOR_CARD,
            width=18,
            anchor="w",
        ).pack(side="left")

        self.lang_var = tk.StringVar(value=self.cfg.language)
        lang_labels = {
            "auto": "Auto (Greek + English)",
            "el": "Greek (locked)",
            "en": "English (locked)",
        }
        for code in LANGUAGE_MODES:
            rb = tk.Radiobutton(
                lang_frame,
                text=lang_labels.get(code, code),
                variable=self.lang_var,
                value=code,
                font=("Segoe UI", 9),
                fg=COLOR_TEXT,
                bg=COLOR_CARD,
                selectcolor=COLOR_CARD_ALT,
                activebackground=COLOR_CARD,
                activeforeground=COLOR_ACCENT,
            )
            rb.pack(side="left", padx=8)

    def _build_system_card(self, parent: tk.Widget) -> None:
        card = self._create_card(parent, "⚙️ Windows Integration & Hotkeys")

        # Startup Toggle
        startup_frame = tk.Frame(card, bg=COLOR_CARD)
        startup_frame.pack(fill="x", pady=6)

        tk.Label(
            startup_frame,
            text="Run on Windows Startup:",
            font=("Segoe UI", 10),
            fg=COLOR_TEXT,
            bg=COLOR_CARD,
            width=22,
            anchor="w",
        ).pack(side="left")

        initial_startup = is_startup_enabled() or self.cfg.run_on_startup
        self.startup_var = tk.BooleanVar(value=initial_startup)

        self.startup_status_lbl = tk.Label(
            startup_frame,
            text="[ENABLED]" if initial_startup else "[DISABLED]",
            font=("Segoe UI", 9, "bold"),
            fg=COLOR_GREEN if initial_startup else COLOR_MUTED,
            bg=COLOR_CARD,
            width=12,
            anchor="w",
        )

        def _on_startup_toggle():
            val = self.startup_var.get()
            if val:
                enable_startup()
                self.startup_status_lbl.configure(text="[ENABLED]", fg=COLOR_GREEN)
            else:
                disable_startup()
                self.startup_status_lbl.configure(text="[DISABLED]", fg=COLOR_MUTED)

        startup_cb = tk.Checkbutton(
            startup_frame,
            text="Start Voice Typer silently in background on Windows login",
            variable=self.startup_var,
            command=_on_startup_toggle,
            font=("Segoe UI", 9),
            fg=COLOR_TEXT,
            bg=COLOR_CARD,
            selectcolor=COLOR_CARD_ALT,
            activebackground=COLOR_CARD,
        )
        startup_cb.pack(side="left", padx=4)
        self.startup_status_lbl.pack(side="left", padx=4)

        # Hotkey Info
        hk_frame = tk.Frame(card, bg=COLOR_CARD)
        hk_frame.pack(fill="x", pady=4)

        tk.Label(
            hk_frame,
            text="Push-to-Talk Hotkey:",
            font=("Segoe UI", 10),
            fg=COLOR_TEXT,
            bg=COLOR_CARD,
            width=22,
            anchor="w",
        ).pack(side="left")

        tk.Label(
            hk_frame,
            text=f"Hold [{self.cfg.hotkey.upper()}] to record · Release to type",
            font=("Segoe UI", 9, "bold"),
            fg=COLOR_ACCENT,
            bg=COLOR_CARD,
        ).pack(side="left")

        # Shortcuts Info
        sc_frame = tk.Frame(card, bg=COLOR_CARD)
        sc_frame.pack(fill="x", pady=2)

        tk.Label(
            sc_frame,
            text="Quick Toggles:",
            font=("Segoe UI", 10),
            fg=COLOR_TEXT,
            bg=COLOR_CARD,
            width=22,
            anchor="w",
        ).pack(side="left")

        tk.Label(
            sc_frame,
            text=f"[{self.cfg.toggle_lang_key.upper()}] Cycle Language  |  [{self.cfg.toggle_engine_key.upper()}] Cycle Engine",
            font=("Segoe UI", 9),
            fg=COLOR_MUTED,
            bg=COLOR_CARD,
        ).pack(side="left")

        # Checkboxes for Audio Beep & Overlay
        cb_frame = tk.Frame(card, bg=COLOR_CARD)
        cb_frame.pack(fill="x", pady=(8, 2))

        self.beep_var = tk.BooleanVar(value=self.cfg.beep_enabled)
        tk.Checkbutton(
            cb_frame,
            text="Chime sounds on recording start / paste",
            variable=self.beep_var,
            font=("Segoe UI", 9),
            fg=COLOR_TEXT,
            bg=COLOR_CARD,
            selectcolor=COLOR_CARD_ALT,
            activebackground=COLOR_CARD,
        ).pack(side="left", padx=(0, 16))

        self.overlay_var = tk.BooleanVar(value=self.cfg.overlay_enabled)
        tk.Checkbutton(
            cb_frame,
            text="Show floating Overlay HUD during dictation",
            variable=self.overlay_var,
            font=("Segoe UI", 9),
            fg=COLOR_TEXT,
            bg=COLOR_CARD,
            selectcolor=COLOR_CARD_ALT,
            activebackground=COLOR_CARD,
        ).pack(side="left")

    def _build_meter_card(self, parent: tk.Widget) -> None:
        card = self._create_card(parent, "🎤 Microphone Test & Input Level")

        meter_frame = tk.Frame(card, bg=COLOR_CARD)
        meter_frame.pack(fill="x", pady=4)

        tk.Label(
            meter_frame,
            text="Input Volume:",
            font=("Segoe UI", 10),
            fg=COLOR_TEXT,
            bg=COLOR_CARD,
            width=14,
            anchor="w",
        ).pack(side="left")

        self.meter_canvas = tk.Canvas(meter_frame, width=420, height=18, bg="#0f172a", highlightthickness=0)
        self.meter_canvas.pack(side="left", padx=8)

        self.meter_val_lbl = tk.Label(
            meter_frame,
            text="0%",
            font=("Segoe UI", 9),
            fg=COLOR_MUTED,
            bg=COLOR_CARD,
            width=6,
        )
        self.meter_val_lbl.pack(side="left")

    def _build_history_card(self, parent: tk.Widget) -> None:
        card = self._create_card(parent, "📊 Dictation Cadence & Transcription History")

        self.db = get_history_db()

        # Stats Header Grid
        stats_frame = tk.Frame(card, bg=COLOR_CARD_ALT, padx=10, pady=8)
        stats_frame.pack(fill="x", pady=(2, 8))

        self.stats_lbl_total = tk.Label(stats_frame, text="0", font=("Segoe UI", 12, "bold"), fg=COLOR_TEXT, bg=COLOR_CARD_ALT)
        self.stats_lbl_words = tk.Label(stats_frame, text="0", font=("Segoe UI", 12, "bold"), fg=COLOR_ACCENT, bg=COLOR_CARD_ALT)
        self.stats_lbl_wpm = tk.Label(stats_frame, text="0", font=("Segoe UI", 12, "bold"), fg=COLOR_GREEN, bg=COLOR_CARD_ALT)
        self.stats_lbl_storage = tk.Label(stats_frame, text="0.0 MB / 1 GB", font=("Segoe UI", 10), fg=COLOR_MUTED, bg=COLOR_CARD_ALT)

        col1 = tk.Frame(stats_frame, bg=COLOR_CARD_ALT)
        col1.pack(side="left", expand=True)
        tk.Label(col1, text="Total Dictations", font=("Segoe UI", 8), fg=COLOR_MUTED, bg=COLOR_CARD_ALT).pack()
        self.stats_lbl_total.pack()

        col2 = tk.Frame(stats_frame, bg=COLOR_CARD_ALT)
        col2.pack(side="left", expand=True)
        tk.Label(col2, text="Total Words", font=("Segoe UI", 8), fg=COLOR_MUTED, bg=COLOR_CARD_ALT).pack()
        self.stats_lbl_words.pack()

        col3 = tk.Frame(stats_frame, bg=COLOR_CARD_ALT)
        col3.pack(side="left", expand=True)
        tk.Label(col3, text="Avg Cadence (WPM)", font=("Segoe UI", 8), fg=COLOR_MUTED, bg=COLOR_CARD_ALT).pack()
        self.stats_lbl_wpm.pack()

        col4 = tk.Frame(stats_frame, bg=COLOR_CARD_ALT)
        col4.pack(side="left", expand=True)
        tk.Label(col4, text="Local Storage Cap", font=("Segoe UI", 8), fg=COLOR_MUTED, bg=COLOR_CARD_ALT).pack()
        self.stats_lbl_storage.pack()

        # Search & Action Toolbar
        toolbar = tk.Frame(card, bg=COLOR_CARD)
        toolbar.pack(fill="x", pady=(4, 6))

        tk.Label(toolbar, text="🔍 Search:", font=("Segoe UI", 9), fg=COLOR_TEXT, bg=COLOR_CARD).pack(side="left", padx=(0, 6))
        self.search_var = tk.StringVar()
        search_entry = tk.Entry(
            toolbar,
            textvariable=self.search_var,
            font=("Segoe UI", 9),
            bg=COLOR_CARD_ALT,
            fg=COLOR_TEXT,
            insertbackground=COLOR_TEXT,
            relief="flat",
            width=28,
        )
        search_entry.pack(side="left", padx=(0, 8), ipady=3)
        search_entry.bind("<KeyRelease>", lambda e: self._refresh_history_list())

        tk.Button(
            toolbar,
            text="🔄 Refresh",
            command=self._refresh_history_list,
            font=("Segoe UI", 8),
            fg=COLOR_TEXT,
            bg=COLOR_CARD_ALT,
            relief="flat",
            padx=8,
            pady=2,
        ).pack(side="left", padx=4)

        tk.Button(
            toolbar,
            text="🗑️ Clear History",
            command=self._on_clear_history,
            font=("Segoe UI", 8),
            fg="#f87171",
            bg=COLOR_CARD_ALT,
            relief="flat",
            padx=8,
            pady=2,
        ).pack(side="right")

        self.history_frame = tk.Frame(card, bg=COLOR_CARD)
        self.history_frame.pack(fill="x", pady=4)

        self._refresh_history_list()

    def _on_clear_history(self) -> None:
        if messagebox.askyesno("Confirm Clear", "Are you sure you want to clear your local transcription history?"):
            self.db.clear_all()
            self._refresh_history_list()

    def _refresh_history_list(self) -> None:
        # Update statistics banner
        stats = self.db.get_statistics()
        self.stats_lbl_total.config(text=f"{stats['total_count']:,}")
        self.stats_lbl_words.config(text=f"{stats['total_words']:,}")
        self.stats_lbl_wpm.config(text=f"{stats['avg_wpm']}")
        self.stats_lbl_storage.config(text=f"{stats['db_size_mb']:.1f} MB / {stats['max_storage_mb']:.0f} MB")

        for child in self.history_frame.winfo_children():
            child.destroy()

        query = self.search_var.get() if hasattr(self, "search_var") else None
        entries = self.db.get_entries(limit=15, search_query=query)

        if not entries:
            tk.Label(
                self.history_frame,
                text="No transcriptions found. Hold Right Ctrl to start speaking!",
                font=("Segoe UI", 9, "italic"),
                fg=COLOR_MUTED,
                bg=COLOR_CARD,
            ).pack(anchor="w", pady=8)
            return

        import pyperclip

        for item in entries:
            text = item.get("text", "")
            created_at = str(item.get("created_at", "")).split()[-1][:8]
            eng = str(item.get("engine", "whisper")).upper()
            wpm = item.get("wpm", 0.0)
            dur = item.get("duration_seconds", 0.0)

            row = tk.Frame(self.history_frame, bg=COLOR_CARD_ALT, padx=8, pady=5)
            row.pack(fill="x", pady=3)

            meta_lbl = tk.Label(
                row,
                text=f"[{created_at}] {eng}",
                font=("Segoe UI", 8, "bold"),
                fg=COLOR_ACCENT,
                bg=COLOR_CARD_ALT,
                width=15,
                anchor="w",
            )
            meta_lbl.pack(side="left")

            wpm_lbl = tk.Label(
                row,
                text=f"{wpm:.0f} WPM · {dur:.1f}s",
                font=("Segoe UI", 8),
                fg=COLOR_GREEN if wpm > 100 else COLOR_MUTED,
                bg=COLOR_CARD_ALT,
                width=12,
                anchor="w",
            )
            wpm_lbl.pack(side="left")

            display_text = text if len(text) <= 50 else text[:47] + "..."
            text_lbl = tk.Label(
                row,
                text=display_text,
                font=("Segoe UI", 9),
                fg=COLOR_TEXT,
                bg=COLOR_CARD_ALT,
                anchor="w",
            )
            text_lbl.pack(side="left", fill="x", expand=True, padx=6)

            def _copy(t=text):
                try:
                    pyperclip.copy(t)
                    messagebox.showinfo("Copied", "Copied transcription to clipboard!")
                except Exception:
                    pass

            copy_btn = tk.Button(
                row,
                text="📋 Copy",
                command=_copy,
                font=("Segoe UI", 8),
                fg=COLOR_TEXT,
                bg="#1a3325",
                activebackground=COLOR_ACCENT_HOVER,
                relief="flat",
                padx=6,
                pady=1,
            )
            copy_btn.pack(side="right")

    def _build_footer(self, parent: tk.Widget) -> None:
        footer = tk.Frame(parent, bg=COLOR_BG)
        footer.pack(fill="x", padx=15, pady=(15, 25))

        save_btn = tk.Button(
            footer,
            text="💾 Save & Apply Settings",
            command=self._save_settings,
            font=("Segoe UI", 10, "bold"),
            fg="#0b0f19",
            bg=COLOR_ACCENT,
            activebackground=COLOR_ACCENT_HOVER,
            relief="flat",
            padx=16,
            pady=8,
            cursor="hand2",
        )
        save_btn.pack(side="right", padx=6)

        refresh_btn = tk.Button(
            footer,
            text="🔄 Refresh History",
            command=self._refresh_history_list,
            font=("Segoe UI", 9),
            fg=COLOR_TEXT,
            bg=COLOR_CARD_ALT,
            relief="flat",
            padx=12,
            pady=8,
        )
        refresh_btn.pack(side="right", padx=6)

    def _save_settings(self) -> None:
        try:
            self.cfg.engine = self.engine_var.get()
            self.cfg.whisper_model = self.model_var.get()
            self.cfg.language = self.lang_var.get()
            self.cfg.run_on_startup = self.startup_var.get()
            self.cfg.beep_enabled = self.beep_var.get()
            self.cfg.overlay_enabled = self.overlay_var.get()

            # Save to config.json
            self.cfg.save()

            # Sync startup
            if self.cfg.run_on_startup:
                enable_startup()
            else:
                disable_startup()

            # Update running pipeline if attached
            if self.pipeline:
                self.pipeline.set_engine(self.cfg.engine)
                self.pipeline.switch_language(self.cfg.language)
                if hasattr(self.pipeline, "overlay"):
                    self.pipeline.overlay.set_engine_and_language(self.cfg.engine, self.cfg.language)

            messagebox.showinfo("Settings Saved", "Voice Typer settings have been successfully applied!")
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to save settings: {exc}")

    def _start_audio_meter(self) -> None:
        self._meter_running = True

        def _meter_loop():
            try:
                import sounddevice as sd

                def _cb(indata, frames, time_info, status):
                    if not self._meter_running:
                        return
                    rms = float(np.sqrt(np.mean(indata**2)))
                    # Scale to percentage
                    pct = min(1.0, rms * 15.0)
                    self.root.after(0, self._update_meter, pct)

                with sd.InputStream(channels=1, samplerate=16000, callback=_cb, blocksize=1024):
                    while self._meter_running:
                        time.sleep(0.08)
            except Exception:
                pass

        self._meter_thread = threading.Thread(target=_meter_loop, daemon=True)
        self._meter_thread.start()

    def _update_meter(self, pct: float) -> None:
        try:
            if not self.root.winfo_exists():
                return
            self.meter_canvas.delete("level")
            w = int(420 * pct)
            if w > 0:
                color = COLOR_GREEN if pct < 0.75 else "#f59e0b"
                self.meter_canvas.create_rectangle(0, 0, w, 18, fill=color, outline="", tags=("level",))
            self.meter_val_lbl.configure(text=f"{int(pct * 100)}%")
        except Exception:
            pass

    def _on_close(self) -> None:
        self._meter_running = False
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def open_dashboard(cfg: Config | None = None, pipeline=None) -> None:
    """Opens Dashboard GUI in a background thread or runs event loop."""
    def _launch():
        app = DashboardApp(cfg, pipeline)
        app.run()

    thread = threading.Thread(target=_launch, name="DashboardGUI", daemon=True)
    thread.start()
