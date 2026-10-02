import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


def home_dir() -> Path:
    override = os.environ.get("PASTA_HOME") or os.environ.get("VOICETYPER_HOME")
    if override:
        return Path(override).expanduser().resolve()
    source_root = Path(__file__).resolve().parent.parent
    if (source_root / ".git").exists() or (source_root / "pyproject.toml").exists():
        return source_root
    return Path.home() / ".pasta"


HOME = home_dir()
CACHE_DIR = HOME / "cache"
LOG_DIR = HOME / "logs"
CONFIG_PATH = HOME / "config.json"

os.environ["HF_HOME"] = str(CACHE_DIR / "huggingface")
os.environ["HUGGINGFACE_HUB_CACHE"] = str(CACHE_DIR / "huggingface")
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["OMP_NUM_THREADS"] = os.environ.get("OMP_NUM_THREADS", "4")

LANGUAGE_MODES = ("auto", "el", "en")
ENGINES = ("whisper", "parakeet")


@dataclass
class AgentConfig:
    enabled: bool = True
    model: str = "decider-2b"
    model_runtime: str = "gpu"  # "gpu", "gguf", or "mock"
    model_revision: str = "v11"
    model_quantization: str = "Q4_K_M"
    confidence_threshold: float = 0.72
    confirmation_threshold: float = 0.55
    max_steps: int = 30
    loop_timeout_seconds: float = 120.0
    max_retries: int = 2
    max_same_state_repeats: int = 3
    allow_shell_commands: bool = True
    headless_browser: bool = False
    wake_names: list[str] = field(default_factory=lambda: [
        "pasta", "jarvis", "computer", "system",
        "πάστα", "παστά", "τζάρβις", "τζαρβις", "κομπιούτερ", "κομπιούτα", "υπολογιστή"
    ])


@dataclass
class PermissionConfig:
    browser: bool = True
    filesystem_read: bool = True
    filesystem_write: bool = False
    shell: str = "allowlist"
    process_termination: bool = False
    email_send: bool = False
    destructive_actions: str = "confirm"


@dataclass
class Config:
    engine: str = "whisper"
    language: str = "auto"
    mode: str = "auto"  # "auto", "agent", "dictation"
    hotkey: str = "right ctrl"
    toggle_lang_key: str = "f12"
    toggle_engine_key: str = "f11"
    toggle_mode_key: str = "f10"
    cancel_key: str = "esc"
    beep_enabled: bool = True
    overlay_enabled: bool = True
    start_minimized: bool = False
    run_on_startup: bool = False
    partial_chunk_seconds: float = 2.0
    silence_flush_seconds: float = 0.7
    max_recording_seconds: int = 60
    idle_unload_minutes: int = 15
    whisper_model: str = "large-v3-turbo"
    whisper_compute_cuda: str = "int8_float16"
    whisper_compute_cpu: str = "int8"
    whisper_beam_size: int = 2
    whisper_vad_filter: bool = True
    parakeet_model: str = "nemo-parakeet-tdt-0.6b-v3"
    parakeet_quantization: str = "int8"
    parakeet_provider: str = ""
    sample_rate: int = 16000
    agent: AgentConfig = field(default_factory=AgentConfig)
    permissions: PermissionConfig = field(default_factory=PermissionConfig)

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: Path = CONFIG_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    def normalized_language(self) -> str | None:
        return None if self.language not in LANGUAGE_MODES or self.language == "auto" else self.language


def load_config(path: Path = CONFIG_PATH) -> Config:
    cfg = Config()
    if not path.exists():
        cfg.save(path)
        return cfg
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return cfg

    known = {f.name for f in type(cfg).__dataclass_fields__.values()}
    for key, value in raw.items():
        if key == "agent" and isinstance(value, dict):
            agent_cfg = AgentConfig()
            for ak, av in value.items():
                if hasattr(agent_cfg, ak):
                    setattr(agent_cfg, ak, av)
            cfg.agent = agent_cfg
        elif key == "permissions" and isinstance(value, dict):
            perm_cfg = PermissionConfig()
            for pk, pv in value.items():
                if hasattr(perm_cfg, pk):
                    setattr(perm_cfg, pk, pv)
            cfg.permissions = perm_cfg
        elif key in known:
            setattr(cfg, key, value)

    if cfg.engine not in ENGINES:
        cfg.engine = "whisper"
    if cfg.language not in LANGUAGE_MODES:
        cfg.language = "auto"
    return cfg
