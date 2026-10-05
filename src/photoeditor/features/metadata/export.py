"""Writing the metadata into an exported file - no Qt imports."""

import os

from .models import MetadataConfig
from .resolution import Resolution
from .source_exif import read_exif_from_file
from .writer import embed_metadata


def is_blank(config: MetadataConfig) -> bool:
    return config == MetadataConfig()


def embed_into_file(dest_path: str, config: MetadataConfig, source_path: str, copy_source_exif: bool, dpi: int) -> bool:
    """Rewrite dest_path with config's metadata merged over the source photo's EXIF (when copy_source_exif),
    plus XMP. False when nothing was written: blank config, or Protect original metadata, where the export
    already carries the source's EXIF untouched. A failed embed leaves the exported file as it was."""
    if config.protect_original_metadata or is_blank(config):
        return False
    with open(dest_path, "rb") as f:
        data = f.read()
    source_exif = read_exif_from_file(source_path) if copy_source_exif else None
    out = embed_metadata(data, config, source_exif, None, Resolution.from_dpi(dpi))
    if out == data:
        return False
    tmp = dest_path + ".meta"
    try:
        with open(tmp, "wb") as f:
            f.write(out)
        os.replace(tmp, dest_path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return True
