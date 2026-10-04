"""Download the FLEURS test split (Greek + English) used by the ASR evaluation.

FLEURS (Conneau et al., 2022) is CC-BY-4.0 read speech. We fetch only the test
split TSVs + audio archives and extract the WAVs into research/data/fleurs/<lang>/.
"""
import sys
import tarfile
from pathlib import Path

from huggingface_hub import hf_hub_download

OUT = Path(__file__).resolve().parent / "fleurs"
LANGS = sys.argv[1:] or ["el_gr", "en_us"]

for lang in LANGS:
    dest = OUT / lang
    dest.mkdir(parents=True, exist_ok=True)
    tsv = hf_hub_download("google/fleurs", f"data/{lang}/test.tsv", repo_type="dataset", local_dir=OUT / "_raw")
    (dest / "test.tsv").write_bytes(Path(tsv).read_bytes())
    if (dest / "audio").exists() and any((dest / "audio").iterdir()):
        print(lang, "audio already extracted")
        continue
    tgz = hf_hub_download("google/fleurs", f"data/{lang}/audio/test.tar.gz", repo_type="dataset", local_dir=OUT / "_raw")
    with tarfile.open(tgz) as tf:
        members = [m for m in tf.getmembers() if m.isfile() and m.name.endswith(".wav")]
        (dest / "audio").mkdir(exist_ok=True)
        for m in members:
            m.name = Path(m.name).name
            tf.extract(m, dest / "audio")
    print(lang, len(members), "wav files")
