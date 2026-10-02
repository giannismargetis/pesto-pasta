"""Download Decider GGUF model weights from Hugging Face."""

from pathlib import Path
import sys

from huggingface_hub import hf_hub_download

from pasta.config import CACHE_DIR

MODEL_REPO = "Mapika/decider-2b-GGUF"
MODEL_FILE = "decider-2b-v11-Q4_K_M.gguf"


def main():
    target_dir = CACHE_DIR / "models"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / MODEL_FILE

    if target_path.exists():
        print(f"Model already exists at: {target_path} ({target_path.stat().st_size / (1024*1024):.1f} MB)")
        return 0

    print(f"Downloading {MODEL_FILE} from {MODEL_REPO}...")
    print(f"Target directory: {target_dir}")
    try:
        downloaded = hf_hub_download(
            repo_id=MODEL_REPO,
            filename=MODEL_FILE,
            local_dir=str(target_dir),
            local_dir_use_symlinks=False,
        )
        print(f"Download complete: {downloaded}")
        return 0
    except Exception as exc:
        print(f"Download failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
