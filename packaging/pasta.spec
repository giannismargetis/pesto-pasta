# PyInstaller spec for the installable PASTA app (one-folder, windowed).
#   build\venv\Scripts\pyinstaller packaging\pasta.spec --noconfirm --distpath dist --workpath build\pyi
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules, copy_metadata

ROOT = SPECPATH + "\\.."

datas = [(ROOT + "\\assets\\icon.ico", "assets")]
datas += collect_data_files("faster_whisper")  # silero_vad_v6.onnx
datas += collect_data_files("onnx_asr")
datas += collect_data_files("uiautomation")
# packages that read their own version via importlib.metadata at runtime
for pkg in ("onnx-asr", "onnxruntime-gpu", "faster-whisper", "ctranslate2", "huggingface_hub", "tokenizers", "numpy"):
    datas += copy_metadata(pkg)

binaries = []
binaries += collect_dynamic_libs("ctranslate2")
binaries += collect_dynamic_libs("onnxruntime")
# cuBLAS / cuDNN wheels: keep nvidia/<pkg>/bin so pesto.cuda finds them on sys.path
binaries += collect_dynamic_libs("nvidia")
binaries += collect_dynamic_libs("uiautomation")

# Unreferenced by CTranslate2 / onnxruntime. (cuDNN's runtime-compiled engines, nvrtc and
# nvjitlink look optional but ARE loaded for some convolution shapes — keep them.)
UNUSED = ("nvblas64", "cufftw64")
binaries = [b for b in binaries if not any(u in b[0].lower().replace("\\", "/").split("/")[-1] for u in UNUSED)]

hiddenimports = (
    collect_submodules("pesto") + collect_submodules("pasta") + collect_submodules("onnx_asr")
    + ["comtypes.stream", "sounddevice", "_sounddevice_data"]
)

excludes = ["torch", "torchaudio", "torchvision", "tkinter", "matplotlib", "scipy", "pandas", "IPython",
            "pytest", "research", "transformers", "tensorflow", "PySide6.QtWebEngineCore", "PySide6.Qt3DCore"]

a = Analysis(
    [ROOT + "\\packaging\\launcher.py"],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="PASTA",
    icon=ROOT + "\\assets\\icon.ico",
    console=False,
    version=ROOT + "\\packaging\\version_info.txt",
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="PASTA")
