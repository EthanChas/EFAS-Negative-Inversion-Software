"""The AI models for the object mask: which ones there are, installing one from a .dtmodel package, which is in use. No Qt.

EFAS uses darktable's own models (darktable-org/darktable-ai, GPL-3.0 for the project, each model with its own licence in its model card): Segment Anything 2.1 from Meta (the weights are
Apache-2.0; the research data it was trained on, SA-1B, is research-only, which darktable also says). A model is a .dtmodel file, which is a zip holding a folder with config.json,
encoder.onnx and decoder.onnx. EFAS cannot ship them (they are 140 to 300 MB): the person chooses to download one (features/aimask via desktop/view/ai_models_dialog.py) and EFAS then
keeps it in its own data folder. Nothing is downloaded unless asked for.
"""

import json
import os
import shutil
import zipfile
from dataclasses import dataclass

from .. import datadir
from ..settings import logic as app_settings

RELEASE_URL = "https://github.com/darktable-org/darktable-ai/releases/download/release-5.6.0/"
ARCH = "sam2"                     # the architecture of the models EFAS can run (SegNext, which darktable also offers, has different inputs and is not supported yet)


@dataclass(frozen=True)
class ModelInfo:
    id: str
    name: str
    size_mb: int
    note: str

    @property
    def file(self) -> str:
        return self.id + ".dtmodel"

    @property
    def url(self) -> str:
        return RELEASE_URL + self.file


CATALOG: tuple[ModelInfo, ...] = (
    ModelInfo("mask-object-sam21-tiny", "SAM 2.1 Tiny", 136, "The smallest and fastest. Good for a first try."),
    ModelInfo("mask-object-sam21-small", "SAM 2.1 Small", 161, "darktable's own default: a little more accurate than Tiny."),
    ModelInfo("mask-object-sam21-base-plus", "SAM 2.1 Base Plus", 294, "The most accurate of the three, and the slowest."),
)
_BY_ID = {m.id: m for m in CATALOG}
_NEEDED = ("config.json", "encoder.onnx", "decoder.onnx")


def info(model_id: str) -> ModelInfo | None:
    return _BY_ID.get(model_id)


def models_dir() -> str:
    return os.path.join(datadir.app_data_dir(), datadir.AI_MODELS_DIR)


def model_dir(model_id: str) -> str:
    return os.path.join(models_dir(), model_id)


def is_installed(model_id: str) -> bool:
    folder = model_dir(model_id)
    return all(os.path.isfile(os.path.join(folder, name)) for name in _NEEDED)


def installed() -> list[str]:
    """The ids of the models that are installed (the catalogue's first, in its order, then any other package the person installed by hand)."""
    ids = [m.id for m in CATALOG if is_installed(m.id)]
    try:
        for name in sorted(os.listdir(models_dir())):
            if name not in _BY_ID and is_installed(name):
                ids.append(name)
    except OSError:
        pass
    return ids


def size_on_disk(model_id: str) -> int:
    folder = model_dir(model_id)
    try:
        return sum(os.path.getsize(os.path.join(folder, n)) for n in os.listdir(folder))
    except OSError:
        return 0


def active() -> str:
    """The model that is used: the one chosen when it is installed, else the first that is installed, else ""."""
    chosen = app_settings.get("ai_mask_model")
    have = installed()
    return chosen if chosen in have else (have[0] if have else "")


def set_active(model_id: str) -> None:
    app_settings.save({"ai_mask_model": model_id if model_id in installed() else ""})


def name_of(model_id: str) -> str:
    known = _BY_ID.get(model_id)
    return known.name if known else model_id


# ---------------------------------------------------------------- a .dtmodel package
def _safe(name: str) -> bool:
    parts = name.replace("\\", "/").split("/")
    return not name.startswith(("/", "\\")) and ".." not in parts and ":" not in parts[0]


def check_package(path: str) -> tuple[str, str]:
    """(the model's id, the folder inside the zip that holds its files) for a .dtmodel package EFAS can use; ValueError, saying what is wrong, when it cannot."""
    try:
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if _safe(n)]
            configs = [n for n in names if n.replace("\\", "/").split("/")[-1] == "config.json"]
            if not configs:
                raise ValueError("This is not a darktable model package: it has no config.json.")
            config_name = sorted(configs, key=len)[0]
            prefix = config_name[: -len("config.json")]
            try:
                config = json.loads(z.read(config_name).decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as exc:
                raise ValueError("The model's config.json cannot be read.") from exc
            if not isinstance(config, dict) or config.get("task") != "mask":
                raise ValueError("This model is not for masks (its task is " + repr(config.get("task") if isinstance(config, dict) else None) + ").")
            if config.get("arch") != ARCH:
                raise ValueError(f"EFAS can run Segment Anything 2.1 models; this one is '{config.get('arch')}'.")
            for needed in ("encoder.onnx", "decoder.onnx"):
                if prefix + needed not in names:
                    raise ValueError(f"The package has no {needed}.")
            model_id = str(config.get("id") or "").strip()
            if not model_id or not _safe(model_id) or "/" in model_id or "\\" in model_id:
                raise ValueError("The package gives no usable model id.")
            return model_id, prefix
    except zipfile.BadZipFile as exc:
        raise ValueError("This file is not a model package (it is not a zip file).") from exc


def install_package(path: str) -> str:
    """Unpack a .dtmodel package into EFAS's own folder (replacing an older copy of the same model) and return its id; ValueError when it cannot be used."""
    model_id, prefix = check_package(path)
    os.makedirs(models_dir(), exist_ok=True)
    target, temp = model_dir(model_id), model_dir(model_id) + ".installing"
    shutil.rmtree(temp, ignore_errors=True)
    os.makedirs(temp)
    try:
        with zipfile.ZipFile(path) as z:
            for name in _NEEDED:
                with z.open(prefix + name) as src, open(os.path.join(temp, name), "wb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
        shutil.rmtree(target, ignore_errors=True)
        os.replace(temp, target)
    except (OSError, KeyError) as exc:
        shutil.rmtree(temp, ignore_errors=True)
        raise ValueError(f"The model could not be installed: {exc}") from exc
    return model_id


def remove(model_id: str) -> None:
    if _safe(model_id) and "/" not in model_id:
        shutil.rmtree(model_dir(model_id), ignore_errors=True)
    if app_settings.get("ai_mask_model") == model_id:
        app_settings.save({"ai_mask_model": ""})
