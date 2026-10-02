import math
import textwrap
import threading
import time

from .config import Config
from .logging_setup import get_logger

log = get_logger("overlay")

BG_KEY = "#010204"
PILL_BG = (12, 16, 22)  # Obsidian night
PILL_BORDER_NORMAL = (24, 54, 38)  # Basil / Pesto green
PILL_BORDER_AGENT = (30, 64, 120)  # Electric Agent Sapphire
PILL_BORDER_AUTO = (88, 44, 130)   # Modern Violet / Hybrid

# Gradient color schemes
GRAD_WHISPER = [
    (0.0, (52, 211, 153)),   # Crisp emerald / mint
    (0.5, (16, 185, 129)),   # Rich basil
    (1.0, (132, 204, 22)),   # Vibrant lime
]

GRAD_PARAKEET = [
    (0.0, (163, 230, 53)),   # Bright lime
    (0.5, (234, 179, 8)),    # Warm gold
    (1.0, (245, 158, 11)),   # Amber accent
]

GRAD_AGENT = [
    (0.0, (56, 189, 248)),   # Sky blue
    (0.5, (99, 102, 241)),   # Indigo
    (1.0, (168, 85, 247)),   # Purple
]

NUM_BARS = 19
BAR_W = 4
BAR_GAP = 6
BAR_MAX_H = 32
BAR_MIN_H = 4
BARS_CY = 50

WIDTH = 560
HEIGHT = 152
TEXT_Y = 96
TELEMETRY_Y = 132


def _blend(c0, c1, a):
    return tuple(int(c0[k] + (c1[k] - c0[k]) * a) for k in range(3))


def _hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(*rgb)


class Overlay:
    def __init__(self, cfg: Config) -> None:
        self.enabled = cfg.overlay_enabled
        self.visible = False
        self._energy_target = 0.0
        self._partial_text = ""
        self._status_text = "LISTENING"
        self._engine_label = cfg.engine.upper()
        self._language_label = cfg.language.upper()

        # Mode & Mode Toggle
        self._operation_mode = getattr(cfg, "mode", "auto").upper()
        self._on_mode_toggle_callback = None

        # GPU and inference telemetry
        self._vram_pct = 0.0
        self._vram_used_gb = 0.0
        self._vram_total_gb = 0.0
        self._last_latency_ms = 0.0
        self._last_rtf = 0.0

        # Agent mode overlay properties
        self._is_agent_mode = False
        self._agent_goal = ""
        self._agent_action = ""
        self._agent_confidence = 0.0
        self._agent_step = 0
        self._agent_max_steps = 30
        self._agent_hide_deadline = 0.0

        # Toast notification system
        self._toast_active = False
        self._toast_title = ""
        self._toast_msg = ""
        self._toast_expire = 0.0

        self._phases = [i * (2 * math.pi / NUM_BARS) for i in range(NUM_BARS)]
        self._bar_heights = [float(BAR_MIN_H)] * NUM_BARS
        self._tick_n = 0
        self._energy = 0.0
        self._lock = threading.Lock()

        if not self.enabled:
            return
        self._thread = threading.Thread(target=self._run, name="Overlay", daemon=True)

    def start(self) -> None:
        if not self.enabled:
            return
        self._thread.start()

    def show(self) -> None:
        with self._lock:
            self._toast_active = False
            self._is_agent_mode = False
            self._status_text = "LISTENING"
            self.visible = True

    def hide(self) -> None:
        with self._lock:
            self.visible = False
            self._is_agent_mode = False
            self._partial_text = ""
            self._energy_target = 0.0

    def set_engine_and_language(self, engine: str, language: str) -> None:
        with self._lock:
            self._engine_label = engine.upper()
            self._language_label = language.upper()

    def set_status(self, status: str) -> None:
        with self._lock:
            self._status_text = status

    def set_energy(self, energy: float) -> None:
        with self._lock:
            self._energy_target = min(1.0, max(0.0, energy * 8.0))

    def set_partial(self, text: str) -> None:
        with self._lock:
            self._partial_text = text

    def set_mode_toggle_callback(self, cb) -> None:
        self._on_mode_toggle_callback = cb

    def set_operation_mode(self, mode: str) -> None:
        with self._lock:
            self._operation_mode = mode.upper()

    def update_telemetry(
        self,
        vram_pct: float,
        used_gb: float,
        total_gb: float,
        latency_ms: float,
        rtf: float = 0.0,
    ) -> None:
        with self._lock:
            self._vram_pct = vram_pct
            self._vram_used_gb = used_gb
            self._vram_total_gb = total_gb
            self._last_latency_ms = latency_ms
            self._last_rtf = rtf

    def show_toast(self, title: str, msg: str, duration: float = 1.6) -> None:
        with self._lock:
            self._toast_title = title
            self._toast_msg = msg
            self._toast_expire = time.monotonic() + duration
            self._toast_active = True

    def set_agent_status(
        self,
        status: str,
        goal: str,
        confidence: float = 0.0,
        step: int = 1,
        max_steps: int = 30,
        keep_visible_seconds: float = 2.0,
    ) -> None:
        """Called by AgentLoop to reflect agent state in the floating HUD."""
        with self._lock:
            self._is_agent_mode = True
            self._status_text = status
            self._agent_goal = goal
            self._agent_action = status
            self._agent_confidence = confidence
            self._agent_step = step
            self._agent_max_steps = max_steps
            self._agent_hide_deadline = time.monotonic() + keep_visible_seconds
            self.visible = True

    def _run(self) -> None:
        try:
            import tkinter as tk

            root = tk.Tk()
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            root.attributes("-alpha", 0.0)
            root.config(bg=BG_KEY)
            root.wm_attributes("-transparentcolor", BG_KEY)

            screen_w = root.winfo_screenwidth()
            screen_h = root.winfo_screenheight()
            x = (screen_w - WIDTH) // 2
            y = screen_h - HEIGHT - 48
            root.geometry(f"{WIDTH}x{HEIGHT}+{x}+{y}")

            canvas = tk.Canvas(
                root,
                width=WIDTH,
                height=HEIGHT,
                bg=BG_KEY,
                highlightthickness=0,
                bd=0,
            )
            canvas.pack(fill="both", expand=True)

            state = {"alpha": 0.0, "shown": False}

            def draw_pill(is_agent: bool = False):
                canvas.delete("pill")
                pad = 4
                r = 18
                x0, y0 = pad, pad
                x1, y1 = WIDTH - pad, HEIGHT - pad
                bg_color = _hex(PILL_BG)

                with self._lock:
                    mode = self._operation_mode

                if is_agent or mode == "AGENT":
                    border_color = _hex(PILL_BORDER_AGENT)
                elif mode == "DICTATION":
                    border_color = _hex(PILL_BORDER_NORMAL)
                else:
                    border_color = _hex(PILL_BORDER_AUTO)

                canvas.create_polygon(
                    x0 + r, y0, x1 - r, y0,
                    x1, y0, x1, y0 + r,
                    x1, y1 - r, x1, y1,
                    x1 - r, y1, x0 + r, y1,
                    x0, y1, x0, y1 - r,
                    x0, y0 + r, x0, y0,
                    smooth=True,
                    fill=bg_color,
                    outline=border_color,
                    width=1.5,
                    tags=("pill",),
                )

            def on_canvas_click(event):
                if self._on_mode_toggle_callback:
                    self._on_mode_toggle_callback()

            canvas.bind("<Button-1>", on_canvas_click)

            def render_header(is_agent: bool = False):
                canvas.delete("header")
                with self._lock:
                    st = self._status_text
                    eng = self._engine_label
                    lng = self._language_label
                    conf = self._agent_confidence
                    step = self._agent_step
                    max_s = self._agent_max_steps
                    mode = self._operation_mode

                if is_agent:
                    tag_color = "#38bdf8"
                    header_left = "⚡ AGENT RUN"
                    header_right = f"STEP {step}/{max_s}"
                    if conf > 0:
                        header_right += f" ({int(conf * 100)}%)"
                else:
                    if mode == "AGENT":
                        tag_color = "#38bdf8"
                        header_left = "🔵 AGENT (F10)"
                    elif mode == "DICTATION":
                        tag_color = "#34d399"
                        header_left = "🟢 DICTATION (F10)"
                    else:
                        tag_color = "#c084fc"
                        header_left = "🟣 AUTO (F10)"
                    header_right = f"{eng} (F11) • {lng} (F12)"

                canvas.create_text(
                    28,
                    22,
                    text=header_left,
                    font=("Segoe UI", 9, "bold"),
                    fill=tag_color,
                    anchor="w",
                    tags=("header",),
                )
                canvas.create_text(
                    WIDTH // 2,
                    22,
                    text=st,
                    font=("Segoe UI", 9, "bold"),
                    fill="#f8fafc",
                    anchor="center",
                    tags=("header",),
                )
                canvas.create_text(
                    WIDTH - 28,
                    22,
                    text=header_right,
                    font=("Segoe UI", 8),
                    fill="#94a3b8",
                    anchor="e",
                    tags=("header",),
                )

            def render_telemetry():
                canvas.delete("telemetry")
                with self._lock:
                    vram_pct = self._vram_pct
                    vram_used = self._vram_used_gb
                    vram_total = self._vram_total_gb
                    lat = self._last_latency_ms
                    rtf = self._last_rtf
                    eng = self._engine_label

                if vram_total > 0:
                    telemetry_str = f"🎮 GPU: {vram_pct:.1f}% VRAM ({vram_used:.2f}/{vram_total:.1f} GB)  •  ⏱️ {lat:.0f}ms (RTF {rtf:.2f}x)  •  {eng}"
                elif lat > 0:
                    telemetry_str = f"⏱️ {lat:.0f}ms (RTF {rtf:.2f}x)  •  {eng}  •  Click to switch Mode"
                else:
                    telemetry_str = f"Click to switch Mode (F10)  •  Engine: {eng} (F11)"

                canvas.create_text(
                    WIDTH // 2,
                    TELEMETRY_Y,
                    text=telemetry_str,
                    font=("Segoe UI", 8),
                    fill="#94a3b8",
                    anchor="center",
                    tags=("telemetry",),
                )

            def render_bars():
                canvas.delete("bar")
                with self._lock:
                    eng = self._engine_label
                    is_agent = self._is_agent_mode

                if is_agent:
                    grad = GRAD_AGENT
                else:
                    grad = GRAD_WHISPER if eng == "WHISPER" else GRAD_PARAKEET

                total_w = NUM_BARS * BAR_W + (NUM_BARS - 1) * BAR_GAP
                start_x = (WIDTH - total_w) // 2

                for i in range(NUM_BARS):
                    ph = self._phases[i]
                    wave = 0.5 + 0.5 * math.sin(self._tick_n * 0.18 + ph)
                    h_target = BAR_MIN_H + (BAR_MAX_H - BAR_MIN_H) * (self._energy * 0.75 + wave * self._energy * 0.25)
                    self._bar_heights[i] += (h_target - self._bar_heights[i]) * 0.35
                    h = self._bar_heights[i]

                    t = i / max(1, NUM_BARS - 1)
                    if t <= grad[1][0]:
                        seg_t = t / grad[1][0] if grad[1][0] > 0 else 0
                        c = _blend(grad[0][1], grad[1][1], seg_t)
                    else:
                        seg_t = (t - grad[1][0]) / (1.0 - grad[1][0]) if (1.0 - grad[1][0]) > 0 else 0
                        c = _blend(grad[1][1], grad[2][1], seg_t)

                    bx = start_x + i * (BAR_W + BAR_GAP)
                    y0 = BARS_CY - h / 2
                    y1 = BARS_CY + h / 2
                    canvas.create_line(bx, y0, bx, y1, width=BAR_W, fill=_hex(c), capstyle="round", tags=("bar",))

            def render_text(is_agent: bool = False):
                canvas.delete("ptext")
                with self._lock:
                    text = self._partial_text
                    goal = self._agent_goal
                    status = self._status_text

                if is_agent:
                    display_text = f"Goal: {goal}" if goal else status
                    canvas.create_text(
                        WIDTH // 2,
                        TEXT_Y,
                        text=display_text[:60],
                        font=("Segoe UI", 11, "bold"),
                        fill="#f8fafc",
                        width=WIDTH - 64,
                        justify="center",
                        tags=("ptext",),
                    )
                    return

                if not text:
                    canvas.create_text(
                        WIDTH // 2,
                        TEXT_Y,
                        text="Speak now...",
                        font=("Segoe UI", 11, "italic"),
                        fill="#64748b",
                        justify="center",
                        tags=("ptext",),
                    )
                    return

                lines = textwrap.wrap(text, width=54)
                if len(lines) > 2:
                    text = "... " + " ".join(lines[-2:])
                else:
                    text = " ".join(lines)
                canvas.create_text(
                    WIDTH // 2,
                    TEXT_Y,
                    text=text,
                    font=("Segoe UI", 11, "bold"),
                    fill="#f1f5f9",
                    width=WIDTH - 64,
                    justify="center",
                    tags=("ptext",),
                )

            def render_toast():
                canvas.delete("bar")
                canvas.delete("ptext")
                canvas.delete("header")
                with self._lock:
                    title = self._toast_title
                    msg = self._toast_msg

                canvas.create_text(
                    WIDTH // 2,
                    48,
                    text=title,
                    font=("Segoe UI", 12, "bold"),
                    fill="#38bdf8",
                    justify="center",
                    tags=("toast",),
                )
                canvas.create_text(
                    WIDTH // 2,
                    84,
                    text=msg,
                    font=("Segoe UI", 10),
                    fill="#e2e8f0",
                    justify="center",
                    tags=("toast",),
                )

            def tick():
                try:
                    now = time.monotonic()
                    with self._lock:
                        if self._toast_active and now >= self._toast_expire:
                            self._toast_active = False

                        if self._is_agent_mode and ("DONE" in self._status_text or "CANCEL" in self._status_text):
                            if now >= self._agent_hide_deadline:
                                self.visible = False
                                self._is_agent_mode = False

                        should_show = self.visible or self._toast_active
                        is_agent = self._is_agent_mode
                        is_toast = self._toast_active

                    target_alpha = 0.96 if should_show else 0.0
                    alpha = state["alpha"]
                    diff = target_alpha - alpha
                    if abs(diff) > 0.005:
                        ease = 0.22 if should_show else 0.26
                        alpha += diff * ease
                        state["alpha"] = alpha
                        root.attributes("-alpha", min(0.96, max(0.0, alpha)))
                    elif should_show and alpha < 0.96:
                        alpha = 0.96
                        state["alpha"] = alpha
                        root.attributes("-alpha", alpha)

                    if should_show and not state["shown"]:
                        draw_pill(is_agent=is_agent)
                        root.deiconify()
                        state["shown"] = True
                    elif not should_show and state["shown"] and state["alpha"] <= 0.03:
                        root.withdraw()
                        state["shown"] = False

                    lp = 0.55 if self._energy_target > self._energy else 0.25
                    self._energy += (self._energy_target - self._energy) * lp

                    if state["shown"]:
                        self._tick_n += 1
                        if is_toast:
                            render_toast()
                        else:
                            canvas.delete("toast")
                            render_header(is_agent=is_agent)
                            render_bars()
                            render_text(is_agent=is_agent)
                            render_telemetry()
                except Exception:
                    pass
                root.after(16, tick)

            draw_pill()
            root.withdraw()
            tick()
            root.mainloop()
        except Exception as exc:
            log.error("Overlay crashed: %s", exc)
