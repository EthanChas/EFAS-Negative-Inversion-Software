"""Pure sqlite3 I/O for persisting per-image edit state across app
restarts - no Qt imports, just a db file path and plain dicts in/out.

One row per file path (not NegPy's content-hash keying - consistent with
the simpler, mtime/size-based identity this app already uses for the
thumbnail cache; renaming a file loses its saved edits, which is an
accepted trade for not having to hash every file on open)."""

import json
import os
import sqlite3

import numpy as np

_SCHEMA = """
CREATE TABLE IF NOT EXISTS edits (
    path TEXT PRIMARY KEY,
    exposure_ev REAL NOT NULL,
    tone_curve_points TEXT NOT NULL,
    negative_inverted INTEGER NOT NULL,
    rotation_quarter_turns INTEGER NOT NULL,
    flip_h INTEGER NOT NULL,
    flip_v INTEGER NOT NULL,
    crop_rect TEXT,
    saturation REAL NOT NULL,
    temperature REAL NOT NULL,
    tint REAL NOT NULL,
    shadows REAL NOT NULL DEFAULT 0.0,
    highlights REAL NOT NULL DEFAULT 0.0,
    sharpen_amount REAL NOT NULL DEFAULT 0.0,
    sharpen_radius REAL NOT NULL DEFAULT 1.0,
    sharpen_masking REAL NOT NULL DEFAULT 0.0,
    sharpen_method TEXT NOT NULL DEFAULT 'usm',
    dust_auto INTEGER NOT NULL DEFAULT 0,
    dust_threshold REAL NOT NULL DEFAULT 0.66,
    dust_size INTEGER NOT NULL DEFAULT 4,
    scratch_lines TEXT NOT NULL DEFAULT '[]',
    scratch_sensitivity REAL NOT NULL DEFAULT 0.5,
    heal_strokes TEXT NOT NULL DEFAULT '[]',
    film_type TEXT NOT NULL DEFAULT 'auto',
    invert_r REAL NOT NULL DEFAULT 0.0,
    invert_g REAL NOT NULL DEFAULT 0.0,
    invert_b REAL NOT NULL DEFAULT 0.0,
    contrast REAL NOT NULL DEFAULT 0.0,
    fine_rotation REAL NOT NULL DEFAULT 0.0,
    distortion REAL NOT NULL DEFAULT 0.0,
    keystone_v REAL NOT NULL DEFAULT 0.0,
    keystone_h REAL NOT NULL DEFAULT 0.0,
    chroma_denoise REAL NOT NULL DEFAULT 0.0,
    wm_film TEXT NOT NULL DEFAULT 'off',
    wm_texture TEXT NOT NULL DEFAULT 'plastic',
    wm_size TEXT NOT NULL DEFAULT 'medium',
    wm_position TEXT NOT NULL DEFAULT 'bottom_right',
    wm_info INTEGER NOT NULL DEFAULT 0,
    wm_camera TEXT NOT NULL DEFAULT '',
    wm_lens TEXT NOT NULL DEFAULT '',
    metadata TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
)
"""

_FLAGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS flags (
    path TEXT PRIMARY KEY,
    flag TEXT NOT NULL
)
"""

_FLATFIELD_SCHEMA = """
CREATE TABLE IF NOT EXISTS folder_flatfield (
    folder TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL DEFAULT '',
    height INTEGER NOT NULL,
    width INTEGER NOT NULL,
    gain BLOB NOT NULL,
    method TEXT NOT NULL DEFAULT 'efas',
    reference BLOB
)
"""

_GLOBAL_FLATFIELD_SCHEMA = """
CREATE TABLE IF NOT EXISTS global_flatfield (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    enabled INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL DEFAULT '',
    height INTEGER NOT NULL,
    width INTEGER NOT NULL,
    gain BLOB NOT NULL,
    method TEXT NOT NULL DEFAULT 'efas',
    reference BLOB
)
"""

_ROLL_SCHEMA = """
CREATE TABLE IF NOT EXISTS folder_roll (
    folder TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_RATINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS ratings (
    path TEXT PRIMARY KEY,
    rating INTEGER NOT NULL
)
"""

_SHARPNESS_SCHEMA = """
CREATE TABLE IF NOT EXISTS sharpness_grades (
    path TEXT PRIMARY KEY,
    severity TEXT NOT NULL,
    score REAL NOT NULL,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL
)
"""

_TAGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS tags (
    path TEXT NOT NULL,
    tag TEXT NOT NULL COLLATE NOCASE,
    PRIMARY KEY (path, tag)
)
"""
_TAGS_INDEX = "CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags (tag)"
# tags that exist whether or not any photo carries them (made in the Tagging panel, or imported from a keyword file)
_TAG_DICT_SCHEMA = "CREATE TABLE IF NOT EXISTS tag_dictionary (tag TEXT PRIMARY KEY COLLATE NOCASE)"

_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS edit_history (
    path TEXT NOT NULL,
    seq INTEGER NOT NULL,
    description TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (path, seq)
)
"""

_PHOTO_BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS photo_film_base (
    path TEXT PRIMARY KEY,
    r INTEGER NOT NULL,
    g INTEGER NOT NULL,
    b INTEGER NOT NULL
)
"""

_HIDDEN_SCHEMA = """
CREATE TABLE IF NOT EXISTS hidden_photos (
    path TEXT PRIMARY KEY,
    hidden_at TEXT NOT NULL
)
"""

# Virtual copies ("versions"). The photo's row in `edits` always holds the version being edited (named in photo_active_version, "Original" when there
# is none); every other version is kept here.
_VERSIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS photo_versions (
    path TEXT NOT NULL,
    name TEXT NOT NULL COLLATE NOCASE,
    state TEXT NOT NULL,
    created TEXT NOT NULL,
    PRIMARY KEY (path, name)
)
"""
_ACTIVE_VERSION_SCHEMA = """
CREATE TABLE IF NOT EXISTS photo_active_version (
    path TEXT PRIMARY KEY,
    name TEXT NOT NULL
)
"""

_COLLECTIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS smart_collections (
    name TEXT PRIMARY KEY COLLATE NOCASE,
    data TEXT NOT NULL,
    created TEXT NOT NULL
)
"""

_SNAPSHOTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    path TEXT NOT NULL,
    name TEXT NOT NULL COLLATE NOCASE,
    state TEXT NOT NULL,
    created TEXT NOT NULL,
    PRIMARY KEY (path, name)
)
"""

_BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS folder_base (
    folder TEXT PRIMARY KEY,
    r INTEGER NOT NULL,
    g INTEGER NOT NULL,
    b INTEGER NOT NULL
)
"""

_LINEAR_REF_SCHEMA = """
CREATE TABLE IF NOT EXISTS folder_linear_ref (
    folder TEXT NOT NULL,
    kind TEXT NOT NULL,
    r REAL NOT NULL,
    g REAL NOT NULL,
    b REAL NOT NULL,
    pixels INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (folder, kind)
)
"""
LINEAR_REF_KINDS = ("base", "clear")

_INVERSION_SCHEMA = """
CREATE TABLE IF NOT EXISTS photo_inversion (
    path TEXT PRIMARY KEY,
    engine TEXT NOT NULL,
    profile_id TEXT NOT NULL DEFAULT '',
    setup_id TEXT NOT NULL DEFAULT '',
    white TEXT NOT NULL DEFAULT '[]'
)
"""
INVERSION_ENGINES = ("classic", "curve")

FLAG_KEEPER = "keeper"
FLAG_REJECTED = "rejected"

_MIGRATIONS = (
    ("shadows", "REAL", "0.0"),
    ("highlights", "REAL", "0.0"),
    ("sharpen_amount", "REAL", "0.0"),
    ("sharpen_radius", "REAL", "1.0"),
    ("sharpen_masking", "REAL", "0.0"),
    ("sharpen_method", "TEXT", "'usm'"),
    ("dust_auto", "INTEGER", "0"),
    ("dust_threshold", "REAL", "0.66"),
    ("dust_size", "INTEGER", "4"),
    ("scratch_lines", "TEXT", "'[]'"),
    ("scratch_sensitivity", "REAL", "0.5"),
    ("heal_strokes", "TEXT", "'[]'"),
    ("clone_strokes", "TEXT", "'[]'"),
    ("ai_dust", "INTEGER", "0"),
    ("ai_threshold", "REAL", "0.3"),
    ("ai_grow", "INTEGER", "1"),
    ("marks", "TEXT", "'{}'"),
    ("film_type", "TEXT", "'auto'"),
    ("invert_r", "REAL", "0.0"),
    ("invert_g", "REAL", "0.0"),
    ("invert_b", "REAL", "0.0"),
    ("contrast", "REAL", "0.0"),
    ("fine_rotation", "REAL", "0.0"),
    ("distortion", "REAL", "0.0"),
    ("keystone_v", "REAL", "0.0"),
    ("keystone_h", "REAL", "0.0"),
    ("chroma_denoise", "REAL", "0.0"),
    ("local_contrast", "REAL", "0.0"),
    ("print_snap", "REAL", "0.0"),
    ("print_toe", "REAL", "0.0"),
    ("print_toe_width", "REAL", "2.5"),
    ("print_shoulder", "REAL", "0.0"),
    ("print_shoulder_width", "REAL", "2.5"),
    ("lab_fade", "REAL", "0.0"),
    ("lab_glow", "REAL", "0.0"),
    ("lab_by_shadows", "REAL", "0.0"),
    ("lab_by_mids", "REAL", "0.0"),
    ("lab_by_highs", "REAL", "0.0"),
    ("lab_gm_shadows", "REAL", "0.0"),
    ("lab_gm_mids", "REAL", "0.0"),
    ("lab_gm_highs", "REAL", "0.0"),
    ("lab_response", "TEXT", "'none'"),
    ("tone_curve_red", "TEXT", "'[[0, 0], [255, 255]]'"),
    ("tone_curve_green", "TEXT", "'[[0, 0], [255, 255]]'"),
    ("tone_curve_blue", "TEXT", "'[[0, 0], [255, 255]]'"),
    ("lab_response_amount", "REAL", "1.0"),
    ("vibrance", "REAL", "0.0"),
    ("mix_hue_red", "REAL", "0.0"),
    ("mix_sat_red", "REAL", "0.0"),
    ("mix_lum_red", "REAL", "0.0"),
    ("mix_hue_orange", "REAL", "0.0"),
    ("mix_sat_orange", "REAL", "0.0"),
    ("mix_lum_orange", "REAL", "0.0"),
    ("mix_hue_yellow", "REAL", "0.0"),
    ("mix_sat_yellow", "REAL", "0.0"),
    ("mix_lum_yellow", "REAL", "0.0"),
    ("mix_hue_green", "REAL", "0.0"),
    ("mix_sat_green", "REAL", "0.0"),
    ("mix_lum_green", "REAL", "0.0"),
    ("mix_hue_aqua", "REAL", "0.0"),
    ("mix_sat_aqua", "REAL", "0.0"),
    ("mix_lum_aqua", "REAL", "0.0"),
    ("mix_hue_blue", "REAL", "0.0"),
    ("mix_sat_blue", "REAL", "0.0"),
    ("mix_lum_blue", "REAL", "0.0"),
    ("mix_hue_purple", "REAL", "0.0"),
    ("mix_sat_purple", "REAL", "0.0"),
    ("mix_lum_purple", "REAL", "0.0"),
    ("mix_hue_magenta", "REAL", "0.0"),
    ("mix_sat_magenta", "REAL", "0.0"),
    ("mix_lum_magenta", "REAL", "0.0"),
    ("tone_hue_shadows", "REAL", "0.0"),
    ("tone_amt_shadows", "REAL", "0.0"),
    ("tone_hue_mids", "REAL", "0.0"),
    ("tone_amt_mids", "REAL", "0.0"),
    ("tone_hue_highs", "REAL", "0.0"),
    ("tone_amt_highs", "REAL", "0.0"),
    ("edge_holder", "REAL", "0.0"),
    ("edge_bleed", "REAL", "0.0"),
    ("edge_dodge", "REAL", "0.0"),
    ("edge_reach", "REAL", "0.08"),
    ("edge_mask", "REAL", "0.0"),
    ("edge_feather", "REAL", "0.5"),
    ("edge_mask_color", "TEXT", "'black'"),
    ("edge_mask_meter", "INTEGER", "1"),
    ("ec_tint", "REAL", "0.0"),
    ("ec_warmth", "REAL", "0.0"),
    ("ec_light", "REAL", "0.0"),
    ("ec_size", "REAL", "0.5"),
    ("ec_shape", "REAL", "0.0"),
    ("hal_amount", "REAL", "0.0"),
    ("hal_radius", "REAL", "0.4"),
    ("hal_threshold", "REAL", "0.7"),
    ("hal_warmth", "REAL", "0.8"),
    ("carrier_width", "REAL", "0.0"),
    ("carrier_rough", "REAL", "0.25"),
    ("carrier_corner", "REAL", "0.25"),
    ("carrier_flare", "REAL", "0.5"),
    ("gs_amount", "REAL", "0.0"),
    ("gs_size", "REAL", "1.2"),
    ("gs_midtones", "REAL", "0.5"),
    ("dif_iterations", "REAL", "1.0"),
    ("dif_radius_center", "REAL", "0.0"),
    ("dif_radius", "REAL", "8.0"),
    ("dif_first", "REAL", "0.0"),
    ("dif_second", "REAL", "0.0"),
    ("dif_third", "REAL", "0.0"),
    ("dif_fourth", "REAL", "0.0"),
    ("dif_aniso_first", "REAL", "0.0"),
    ("dif_aniso_second", "REAL", "0.0"),
    ("dif_aniso_third", "REAL", "0.0"),
    ("dif_aniso_fourth", "REAL", "0.0"),
    ("dif_sharpness", "REAL", "0.0"),
    ("dif_regularization", "REAL", "0.0"),
    ("dif_variance_threshold", "REAL", "0.0"),
    ("dif_threshold", "REAL", "0.0"),
    ("teq_band0", "REAL", "0.0"),
    ("teq_band1", "REAL", "0.0"),
    ("teq_band2", "REAL", "0.0"),
    ("teq_band3", "REAL", "0.0"),
    ("teq_band4", "REAL", "0.0"),
    ("teq_band5", "REAL", "0.0"),
    ("teq_band6", "REAL", "0.0"),
    ("teq_band7", "REAL", "0.0"),
    ("teq_band8", "REAL", "0.0"),
    ("teq_smoothing", "REAL", "0.0"),
    ("teq_exposure_boost", "REAL", "0.0"),
    ("teq_contrast_boost", "REAL", "0.0"),
    ("teq_method", "REAL", "4.0"),
    ("teq_details", "REAL", "4.0"),
    ("teq_iterations", "REAL", "1.0"),
    ("teq_blending", "REAL", "5.0"),
    ("teq_feathering", "REAL", "1.0"),
    ("teq_quantization", "REAL", "0.0"),
    ("cbr_shadows_Y", "REAL", "0.0"),
    ("cbr_shadows_C", "REAL", "0.0"),
    ("cbr_shadows_H", "REAL", "0.0"),
    ("cbr_midtones_Y", "REAL", "0.0"),
    ("cbr_midtones_C", "REAL", "0.0"),
    ("cbr_midtones_H", "REAL", "0.0"),
    ("cbr_highlights_Y", "REAL", "0.0"),
    ("cbr_highlights_C", "REAL", "0.0"),
    ("cbr_highlights_H", "REAL", "0.0"),
    ("cbr_global_Y", "REAL", "0.0"),
    ("cbr_global_C", "REAL", "0.0"),
    ("cbr_global_H", "REAL", "0.0"),
    ("cbr_shadows_weight", "REAL", "1.0"),
    ("cbr_white_fulcrum", "REAL", "0.0"),
    ("cbr_highlights_weight", "REAL", "1.0"),
    ("cbr_chroma_shadows", "REAL", "0.0"),
    ("cbr_chroma_highlights", "REAL", "0.0"),
    ("cbr_chroma_global", "REAL", "0.0"),
    ("cbr_chroma_midtones", "REAL", "0.0"),
    ("cbr_saturation_global", "REAL", "0.0"),
    ("cbr_saturation_highlights", "REAL", "0.0"),
    ("cbr_saturation_midtones", "REAL", "0.0"),
    ("cbr_saturation_shadows", "REAL", "0.0"),
    ("cbr_hue_angle", "REAL", "0.0"),
    ("cbr_brilliance_global", "REAL", "0.0"),
    ("cbr_brilliance_highlights", "REAL", "0.0"),
    ("cbr_brilliance_midtones", "REAL", "0.0"),
    ("cbr_brilliance_shadows", "REAL", "0.0"),
    ("cbr_mask_grey_fulcrum", "REAL", "0.1845"),
    ("cbr_vibrance", "REAL", "0.0"),
    ("cbr_grey_fulcrum", "REAL", "0.1845"),
    ("cbr_contrast", "REAL", "0.0"),
    ("cbr_formula", "REAL", "1.0"),
    ("vignette", "REAL", "0.0"),
    ("vignette_size", "REAL", "0.5"),
    ("border", "REAL", "0.0"),
    ("border_color", "TEXT", "'white'"),
    ("carrier", "INTEGER", "0"),
    ("metering", "TEXT", "'{}'"),
    ("wm_film", "TEXT", "'off'"),
    ("wm_texture", "TEXT", "'plastic'"),
    ("wm_size", "TEXT", "'medium'"),
    ("wm_position", "TEXT", "'bottom_right'"),
    ("wm_info", "INTEGER", "0"),
    ("wm_camera", "TEXT", "''"),
    ("wm_lens", "TEXT", "''"),
    ("metadata", "TEXT", "'{}'"),
    ("module_presets", "TEXT", "'{}'"),
    ("dust_excluded", "TEXT", "'[]'"),
    ("error_marks", "TEXT", "'[]'"),
    ("modules_off", "TEXT", "'[]'"),
    ("masks", "TEXT", "'{}'"),
    ("blends", "TEXT", "'{}'"),
    ("retouch", "TEXT", "'{}'"),
    ("instances", "TEXT", "'{}'"),
    ("lens_corr", "TEXT", "'{}'"),
)

_FIELDS = (
    ("exposure_ev", "plain"),
    ("tone_curve_points", "json"),
    ("negative_inverted", "bool"),
    ("rotation_quarter_turns", "plain"),
    ("flip_h", "bool"),
    ("flip_v", "bool"),
    ("crop_rect", "json_null"),
    ("saturation", "plain"),
    ("temperature", "plain"),
    ("tint", "plain"),
    ("shadows", "plain"),
    ("highlights", "plain"),
    ("sharpen_amount", "plain"),
    ("sharpen_radius", "plain"),
    ("sharpen_masking", "plain"),
    ("sharpen_method", "plain"),
    ("dust_auto", "bool"),
    ("dust_threshold", "plain"),
    ("dust_size", "plain"),
    ("scratch_lines", "json"),
    ("scratch_sensitivity", "plain"),
    ("heal_strokes", "json"),
    ("clone_strokes", "json"),
    ("ai_dust", "bool"),
    ("ai_threshold", "plain"),
    ("ai_grow", "plain"),
    ("marks", "json"),
    ("film_type", "plain"),
    ("invert_r", "plain"),
    ("invert_g", "plain"),
    ("invert_b", "plain"),
    ("contrast", "plain"),
    ("fine_rotation", "plain"),
    ("distortion", "plain"),
    ("keystone_v", "plain"),
    ("keystone_h", "plain"),
    ("chroma_denoise", "plain"),
    ("local_contrast", "plain"),
    ("print_snap", "plain"),
    ("print_toe", "plain"),
    ("print_toe_width", "plain"),
    ("print_shoulder", "plain"),
    ("print_shoulder_width", "plain"),
    ("lab_fade", "plain"),
    ("lab_glow", "plain"),
    ("lab_by_shadows", "plain"),
    ("lab_by_mids", "plain"),
    ("lab_by_highs", "plain"),
    ("lab_gm_shadows", "plain"),
    ("lab_gm_mids", "plain"),
    ("lab_gm_highs", "plain"),
    ("lab_response", "plain"),
    ("tone_curve_red", "json"),
    ("tone_curve_green", "json"),
    ("tone_curve_blue", "json"),
    ("lab_response_amount", "plain"),
    ("vibrance", "plain"),
    ("mix_hue_red", "plain"),
    ("mix_sat_red", "plain"),
    ("mix_lum_red", "plain"),
    ("mix_hue_orange", "plain"),
    ("mix_sat_orange", "plain"),
    ("mix_lum_orange", "plain"),
    ("mix_hue_yellow", "plain"),
    ("mix_sat_yellow", "plain"),
    ("mix_lum_yellow", "plain"),
    ("mix_hue_green", "plain"),
    ("mix_sat_green", "plain"),
    ("mix_lum_green", "plain"),
    ("mix_hue_aqua", "plain"),
    ("mix_sat_aqua", "plain"),
    ("mix_lum_aqua", "plain"),
    ("mix_hue_blue", "plain"),
    ("mix_sat_blue", "plain"),
    ("mix_lum_blue", "plain"),
    ("mix_hue_purple", "plain"),
    ("mix_sat_purple", "plain"),
    ("mix_lum_purple", "plain"),
    ("mix_hue_magenta", "plain"),
    ("mix_sat_magenta", "plain"),
    ("mix_lum_magenta", "plain"),
    ("tone_hue_shadows", "plain"),
    ("tone_amt_shadows", "plain"),
    ("tone_hue_mids", "plain"),
    ("tone_amt_mids", "plain"),
    ("tone_hue_highs", "plain"),
    ("tone_amt_highs", "plain"),
    ("edge_holder", "plain"),
    ("edge_bleed", "plain"),
    ("edge_dodge", "plain"),
    ("edge_reach", "plain"),
    ("edge_mask", "plain"),
    ("edge_feather", "plain"),
    ("edge_mask_color", "plain"),
    ("edge_mask_meter", "bool"),
    ("ec_tint", "plain"),
    ("ec_warmth", "plain"),
    ("ec_light", "plain"),
    ("ec_size", "plain"),
    ("ec_shape", "plain"),
    ("hal_amount", "plain"),
    ("hal_radius", "plain"),
    ("hal_threshold", "plain"),
    ("hal_warmth", "plain"),
    ("carrier_width", "plain"),
    ("carrier_rough", "plain"),
    ("carrier_corner", "plain"),
    ("carrier_flare", "plain"),
    ("gs_amount", "plain"),
    ("gs_size", "plain"),
    ("gs_midtones", "plain"),
    ("dif_iterations", "plain"),
    ("dif_radius_center", "plain"),
    ("dif_radius", "plain"),
    ("dif_first", "plain"),
    ("dif_second", "plain"),
    ("dif_third", "plain"),
    ("dif_fourth", "plain"),
    ("dif_aniso_first", "plain"),
    ("dif_aniso_second", "plain"),
    ("dif_aniso_third", "plain"),
    ("dif_aniso_fourth", "plain"),
    ("dif_sharpness", "plain"),
    ("dif_regularization", "plain"),
    ("dif_variance_threshold", "plain"),
    ("dif_threshold", "plain"),
    ("teq_band0", "plain"),
    ("teq_band1", "plain"),
    ("teq_band2", "plain"),
    ("teq_band3", "plain"),
    ("teq_band4", "plain"),
    ("teq_band5", "plain"),
    ("teq_band6", "plain"),
    ("teq_band7", "plain"),
    ("teq_band8", "plain"),
    ("teq_smoothing", "plain"),
    ("teq_exposure_boost", "plain"),
    ("teq_contrast_boost", "plain"),
    ("teq_method", "plain"),
    ("teq_details", "plain"),
    ("teq_iterations", "plain"),
    ("teq_blending", "plain"),
    ("teq_feathering", "plain"),
    ("teq_quantization", "plain"),
    ("cbr_shadows_Y", "plain"),
    ("cbr_shadows_C", "plain"),
    ("cbr_shadows_H", "plain"),
    ("cbr_midtones_Y", "plain"),
    ("cbr_midtones_C", "plain"),
    ("cbr_midtones_H", "plain"),
    ("cbr_highlights_Y", "plain"),
    ("cbr_highlights_C", "plain"),
    ("cbr_highlights_H", "plain"),
    ("cbr_global_Y", "plain"),
    ("cbr_global_C", "plain"),
    ("cbr_global_H", "plain"),
    ("cbr_shadows_weight", "plain"),
    ("cbr_white_fulcrum", "plain"),
    ("cbr_highlights_weight", "plain"),
    ("cbr_chroma_shadows", "plain"),
    ("cbr_chroma_highlights", "plain"),
    ("cbr_chroma_global", "plain"),
    ("cbr_chroma_midtones", "plain"),
    ("cbr_saturation_global", "plain"),
    ("cbr_saturation_highlights", "plain"),
    ("cbr_saturation_midtones", "plain"),
    ("cbr_saturation_shadows", "plain"),
    ("cbr_hue_angle", "plain"),
    ("cbr_brilliance_global", "plain"),
    ("cbr_brilliance_highlights", "plain"),
    ("cbr_brilliance_midtones", "plain"),
    ("cbr_brilliance_shadows", "plain"),
    ("cbr_mask_grey_fulcrum", "plain"),
    ("cbr_vibrance", "plain"),
    ("cbr_grey_fulcrum", "plain"),
    ("cbr_contrast", "plain"),
    ("cbr_formula", "plain"),
    ("vignette", "plain"),
    ("vignette_size", "plain"),
    ("border", "plain"),
    ("border_color", "plain"),
    ("metering", "json"),
    ("wm_film", "plain"),
    ("wm_texture", "plain"),
    ("wm_size", "plain"),
    ("wm_position", "plain"),
    ("wm_info", "bool"),
    ("wm_camera", "plain"),
    ("wm_lens", "plain"),
    ("metadata", "json"),
    ("module_presets", "json"),
    ("dust_excluded", "json"),
    ("error_marks", "json"),
    ("modules_off", "json"),
    ("masks", "json"),
    ("blends", "json"),
    ("retouch", "json"),
    ("instances", "json"),
    ("lens_corr", "json"),
)


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute(_SCHEMA)
    conn.execute(_FLAGS_SCHEMA)
    conn.execute(_FLATFIELD_SCHEMA)
    conn.execute(_GLOBAL_FLATFIELD_SCHEMA)
    conn.execute(_ROLL_SCHEMA)
    conn.execute(_RATINGS_SCHEMA)
    conn.execute(_SHARPNESS_SCHEMA)
    conn.execute(_BASE_SCHEMA)
    conn.execute(_LINEAR_REF_SCHEMA)
    conn.execute(_INVERSION_SCHEMA)
    conn.execute(_TAGS_SCHEMA)
    conn.execute(_TAGS_INDEX)
    conn.execute(_TAG_DICT_SCHEMA)
    conn.execute(_HISTORY_SCHEMA)
    conn.execute(_SNAPSHOTS_SCHEMA)
    conn.execute(_HIDDEN_SCHEMA)
    conn.execute(_PHOTO_BASE_SCHEMA)
    conn.execute(_COLLECTIONS_SCHEMA)
    conn.execute(_VERSIONS_SCHEMA)
    conn.execute(_ACTIVE_VERSION_SCHEMA)
    _migrate(conn)
    conn.commit()
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    for table in ("folder_flatfield", "global_flatfield"):   # flat fields made before the methods existed keep the gain they have (built the EFAS way) and have no reference to rebuild from
        have = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if "method" not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN method TEXT NOT NULL DEFAULT 'efas'")
        if "reference" not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN reference BLOB")
    existing = {row[1] for row in conn.execute("PRAGMA table_info(edits)")}
    for column, sql_type, default in _MIGRATIONS:
        if column not in existing:
            conn.execute(f"ALTER TABLE edits ADD COLUMN {column} {sql_type} NOT NULL DEFAULT {default}")


def _encode(value, kind: str):
    if kind == "bool":
        return int(value)
    if kind == "json":
        return json.dumps(value)
    if kind == "json_null":
        return json.dumps(value) if value is not None else None
    return value


def _decode(value, kind: str, field: str):
    if kind == "bool":
        return bool(value)
    if kind == "json_null":
        return tuple(json.loads(value)) if value else None
    if kind == "json":
        data = json.loads(value)
        if field == "tone_curve_points" or field in ("tone_curve_red", "tone_curve_green", "tone_curve_blue"):
            return [tuple(p) for p in data]
        if field == "scratch_lines":
            return [tuple(line) for line in data]
        return data
    return value


def save_edit_state(conn: sqlite3.Connection, path: str, state: dict) -> None:
    names = [name for name, _ in _FIELDS]
    state = {"module_presets": {}, "dust_excluded": [], "error_marks": [], "modules_off": [], "masks": {}, "blends": {}, "retouch": {}, "instances": {}, "lens_corr": {}, **state}
    values = [_encode(state[name], kind) for name, kind in _FIELDS]
    marks = ", ".join("?" * (len(names) + 1))
    updates = ", ".join(f"{name}=excluded.{name}" for name in names)
    conn.execute(
        f"""
        INSERT INTO edits (path, {", ".join(names)}, updated_at)
        VALUES ({marks}, datetime('now'))
        ON CONFLICT(path) DO UPDATE SET {updates}, updated_at=excluded.updated_at
        """,
        [path, *values],
    )
    conn.commit()


def load_edit_state(conn: sqlite3.Connection, path: str) -> dict | None:
    names = [name for name, _ in _FIELDS]
    row = conn.execute(f"SELECT {', '.join(names)} FROM edits WHERE path = ?", (path,)).fetchone()
    if row is None:
        return None
    state = {name: _decode(value, kind, name) for (name, kind), value in zip(_FIELDS, row)}
    if state.get("metering") == {}:
        from ..tonecurve.logic import DEFAULT_POINTS

        if is_untouched(state, DEFAULT_POINTS):
            state["metering"] = {"engine": "print"}   # opened once and never edited: it takes today's default conversion, not the one it was opened under
    return state


def edited_paths(conn: sqlite3.Connection, paths: list[str]) -> set[str]:
    """Which of paths have a saved edit row (queried in chunks to stay under SQLite's variable limit)."""
    found: set[str] = set()
    for i in range(0, len(paths), 500):
        chunk = paths[i : i + 500]
        marks = ",".join("?" * len(chunk))
        found.update(row[0] for row in conn.execute(f"SELECT path FROM edits WHERE path IN ({marks})", chunk))
    return found


def set_flag(conn: sqlite3.Connection, path: str, flag: str | None) -> None:
    """flag is FLAG_KEEPER, FLAG_REJECTED, or None to clear the mark."""
    if flag is None:
        conn.execute("DELETE FROM flags WHERE path = ?", (path,))
    else:
        conn.execute(
            "INSERT INTO flags (path, flag) VALUES (?, ?) ON CONFLICT(path) DO UPDATE SET flag=excluded.flag",
            (path, flag),
        )
    conn.commit()


def get_flag(conn: sqlite3.Connection, path: str) -> str | None:
    row = conn.execute("SELECT flag FROM flags WHERE path = ?", (path,)).fetchone()
    return row[0] if row else None


def get_flags(conn: sqlite3.Connection, paths: list[str]) -> dict[str, str]:
    """{path: flag} for whichever of paths are marked (queried in chunks)."""
    found: dict[str, str] = {}
    for i in range(0, len(paths), 500):
        chunk = paths[i : i + 500]
        marks = ",".join("?" * len(chunk))
        found.update(conn.execute(f"SELECT path, flag FROM flags WHERE path IN ({marks})", chunk).fetchall())
    return found


def folder_key(path_or_folder: str, is_file: bool = True) -> str:
    """Normalized key for a folder (case-insensitive, like Windows paths)."""
    folder = os.path.dirname(path_or_folder) if is_file else path_or_folder
    return os.path.normcase(os.path.abspath(folder))


def _reference_blob(reference) -> bytes | None:
    return None if reference is None else np.ascontiguousarray(reference, dtype=np.float32).tobytes()


def _read_flatfield(row) -> dict | None:
    enabled, source, h, w, blob, method, ref_blob = row
    try:
        gain = np.frombuffer(blob, dtype=np.float32).reshape(h, w, 3).copy()
    except ValueError:
        return None
    reference = None
    if ref_blob is not None:
        try:
            reference = np.frombuffer(ref_blob, dtype=np.float32).reshape(h, w, 3).copy()
        except ValueError:
            reference = None
    return {"gain": gain, "enabled": bool(enabled), "source": source, "method": method or "efas", "reference": reference}


def set_folder_flatfield(conn: sqlite3.Connection, folder: str, gain: np.ndarray, source: str = "", enabled: bool = True, method: str = "efas", reference=None) -> None:
    """Save a folder's flat field: its gain map, the method that made it and (so the method can be changed later) the small linear reference map it was made from."""
    gain = np.ascontiguousarray(gain, dtype=np.float32)
    h, w = gain.shape[:2]
    conn.execute(
        """
        INSERT INTO folder_flatfield (folder, enabled, source, height, width, gain, method, reference) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(folder) DO UPDATE SET enabled=excluded.enabled, source=excluded.source,
            height=excluded.height, width=excluded.width, gain=excluded.gain, method=excluded.method, reference=excluded.reference
        """,
        (folder, int(enabled), source, h, w, gain.tobytes(), method, _reference_blob(reference)),
    )
    conn.commit()


def get_folder_flatfield(conn: sqlite3.Connection, folder: str) -> dict | None:
    """{"gain": (h, w, 3) float32, "enabled": bool, "source": str, "method": str, "reference": (h, w, 3) float32 or None} or None."""
    row = conn.execute(
        "SELECT enabled, source, height, width, gain, method, reference FROM folder_flatfield WHERE folder = ?", (folder,)
    ).fetchone()
    return None if row is None else _read_flatfield(row)


def update_folder_flatfield_gain(conn: sqlite3.Connection, folder: str, gain: np.ndarray, method: str) -> None:
    """Replace a folder's gain map with one made from its stored reference by another method."""
    conn.execute("UPDATE folder_flatfield SET gain = ?, method = ? WHERE folder = ?", (np.ascontiguousarray(gain, dtype=np.float32).tobytes(), method, folder))
    conn.commit()


def set_folder_flatfield_enabled(conn: sqlite3.Connection, folder: str, enabled: bool) -> None:
    conn.execute("UPDATE folder_flatfield SET enabled = ? WHERE folder = ?", (int(enabled), folder))
    conn.commit()


def delete_folder_flatfield(conn: sqlite3.Connection, folder: str) -> None:
    conn.execute("DELETE FROM folder_flatfield WHERE folder = ?", (folder,))
    conn.commit()


def set_global_flatfield(conn: sqlite3.Connection, gain: np.ndarray, source: str = "", enabled: bool = True, method: str = "efas", reference=None) -> None:
    """The one permanent flat field: it applies to every photo that has no flat field of its own folder's."""
    gain = np.ascontiguousarray(gain, dtype=np.float32)
    h, w = gain.shape[:2]
    conn.execute(
        """
        INSERT INTO global_flatfield (id, enabled, source, height, width, gain, method, reference) VALUES (1, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET enabled=excluded.enabled, source=excluded.source,
            height=excluded.height, width=excluded.width, gain=excluded.gain, method=excluded.method, reference=excluded.reference
        """,
        (int(enabled), source, h, w, gain.tobytes(), method, _reference_blob(reference)),
    )
    conn.commit()


def get_global_flatfield(conn: sqlite3.Connection) -> dict | None:
    """{"gain": (h, w, 3) float32, "enabled": bool, "source": str, "method": str, "reference": (h, w, 3) float32 or None} or None."""
    row = conn.execute("SELECT enabled, source, height, width, gain, method, reference FROM global_flatfield WHERE id = 1").fetchone()
    return None if row is None else _read_flatfield(row)


def update_global_flatfield_gain(conn: sqlite3.Connection, gain: np.ndarray, method: str) -> None:
    conn.execute("UPDATE global_flatfield SET gain = ?, method = ? WHERE id = 1", (np.ascontiguousarray(gain, dtype=np.float32).tobytes(), method))
    conn.commit()


def set_global_flatfield_enabled(conn: sqlite3.Connection, enabled: bool) -> None:
    conn.execute("UPDATE global_flatfield SET enabled = ? WHERE id = 1", (int(enabled),))
    conn.commit()


def delete_global_flatfield(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM global_flatfield WHERE id = 1")
    conn.commit()


def effective_flatfield(conn: sqlite3.Connection, path: str) -> dict | None:
    """The flat field a photo is rendered with: its folder's own when that is switched on (it was measured with the lighting of that session, the permanent
    one's falloff included, so the two are never stacked), else the permanent one when that is on. {"gain", "source", "scope": "folder" | "permanent"} or None."""
    row = get_folder_flatfield(conn, folder_key(path))
    if row is not None and row["enabled"]:
        return {"gain": row["gain"], "source": row["source"], "scope": "folder"}
    row = get_global_flatfield(conn)
    if row is not None and row["enabled"]:
        return {"gain": row["gain"], "source": row["source"], "scope": "permanent"}
    return None


def get_folder_roll(conn: sqlite3.Connection, folder: str) -> dict | None:
    """The folder's Roll Card as a plain dict (see features/metadata/roll.py), or None."""
    row = conn.execute("SELECT data FROM folder_roll WHERE folder = ?", (folder,)).fetchone()
    if row is None:
        return None
    try:
        data = json.loads(row[0])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def set_folder_roll(conn: sqlite3.Connection, folder: str, data: dict) -> None:
    conn.execute(
        "INSERT INTO folder_roll (folder, data, updated_at) VALUES (?, ?, datetime('now')) "
        "ON CONFLICT(folder) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
        (folder, json.dumps(data, ensure_ascii=False)),
    )
    conn.commit()


def delete_folder_roll(conn: sqlite3.Connection, folder: str) -> None:
    conn.execute("DELETE FROM folder_roll WHERE folder = ?", (folder,))
    conn.commit()


def list_folder_rolls(conn: sqlite3.Connection) -> list[tuple[str, dict]]:
    """Every saved Roll Card as (folder, dict), most recently changed first - for copying one onto another roll."""
    out = []
    for folder, raw in conn.execute("SELECT folder, data FROM folder_roll ORDER BY updated_at DESC"):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            out.append((folder, data))
    return out


def set_rating(conn: sqlite3.Connection, path: str, rating: int) -> None:
    """rating 1-5; 0 clears it."""
    if rating <= 0:
        conn.execute("DELETE FROM ratings WHERE path = ?", (path,))
    else:
        conn.execute(
            "INSERT INTO ratings (path, rating) VALUES (?, ?) ON CONFLICT(path) DO UPDATE SET rating=excluded.rating",
            (path, min(5, int(rating))),
        )
    conn.commit()


def get_rating(conn: sqlite3.Connection, path: str) -> int:
    row = conn.execute("SELECT rating FROM ratings WHERE path = ?", (path,)).fetchone()
    return int(row[0]) if row else 0


def get_ratings(conn: sqlite3.Connection, paths: list[str]) -> dict[str, int]:
    found: dict[str, int] = {}
    for i in range(0, len(paths), 500):
        chunk = paths[i : i + 500]
        marks = ",".join("?" * len(chunk))
        found.update(conn.execute(f"SELECT path, rating FROM ratings WHERE path IN ({marks})", chunk).fetchall())
    return found


def set_sharpness_grade(conn: sqlite3.Connection, path: str, severity: str, score: float) -> None:
    """Keep a frame's sharpness grade (features/sharpgrade). It is tied to the file as it is now (size and time), so a file that is changed or replaced is graded afresh."""
    try:
        st = os.stat(path)
    except OSError:
        return
    conn.execute(
        "INSERT INTO sharpness_grades (path, severity, score, size, mtime_ns) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(path) DO UPDATE SET severity=excluded.severity, score=excluded.score, size=excluded.size, mtime_ns=excluded.mtime_ns",
        (path, severity, float(score), st.st_size, st.st_mtime_ns),
    )
    conn.commit()


def get_sharpness_grades(conn: sqlite3.Connection, paths: list[str]) -> dict[str, tuple[str, float]]:
    """{path: (severity, score)} for whichever of paths were graded and have not changed since."""
    found: dict[str, tuple[str, float]] = {}
    for i in range(0, len(paths), 500):
        chunk = paths[i : i + 500]
        marks = ",".join("?" * len(chunk))
        for path, severity, score, size, mtime_ns in conn.execute(f"SELECT path, severity, score, size, mtime_ns FROM sharpness_grades WHERE path IN ({marks})", chunk).fetchall():
            try:
                st = os.stat(path)
            except OSError:
                continue
            if st.st_size == size and st.st_mtime_ns == mtime_ns:
                found[path] = (severity, float(score))
    return found


def forget_sharpness_grades(conn: sqlite3.Connection, paths: list[str]) -> None:
    for i in range(0, len(paths), 500):
        chunk = paths[i : i + 500]
        conn.execute(f"DELETE FROM sharpness_grades WHERE path IN ({','.join('?' * len(chunk))})", chunk)
    conn.commit()


def state_to_json(state: dict) -> str:
    """An edit state (as AppController._edit_state_dict builds it) as one JSON text, each field encoded the way its column is."""
    state = {"module_presets": {}, "dust_excluded": [], "error_marks": [], "modules_off": [], "masks": {}, "blends": {}, "retouch": {}, "instances": {}, "lens_corr": {}, **state}
    return json.dumps({name: _encode(state[name], kind) for name, kind in _FIELDS if name in state})


def state_from_json(text: str) -> dict:
    """The edit state a snapshot holds; a field it does not have (it was taken before the field existed) is simply missing."""
    raw = json.loads(text)
    return {name: _decode(raw[name], kind, name) for name, kind in _FIELDS if name in raw}


def save_snapshot(conn: sqlite3.Connection, path: str, name: str, state: dict) -> None:
    conn.execute(
        "INSERT INTO snapshots (path, name, state, created) VALUES (?, ?, ?, datetime('now', 'localtime')) "
        "ON CONFLICT(path, name) DO UPDATE SET state=excluded.state, created=excluded.created",
        (path, name, state_to_json(state)),
    )
    conn.commit()


def list_snapshots(conn: sqlite3.Connection, path: str) -> list[tuple[str, str]]:
    """(name, when taken) of a photo's snapshots, newest first."""
    return [(n, c) for n, c in conn.execute("SELECT name, created FROM snapshots WHERE path = ? ORDER BY created DESC, rowid DESC", (path,))]


def get_snapshot(conn: sqlite3.Connection, path: str, name: str) -> dict | None:
    row = conn.execute("SELECT state FROM snapshots WHERE path = ? AND name = ?", (path, name)).fetchone()
    return state_from_json(row[0]) if row else None


def delete_snapshot(conn: sqlite3.Connection, path: str, name: str) -> bool:
    cur = conn.execute("DELETE FROM snapshots WHERE path = ? AND name = ?", (path, name))
    conn.commit()
    return cur.rowcount > 0


def load_history(conn: sqlite3.Connection, path: str) -> list[tuple[str, str]]:
    """The saved edit history of a photo, oldest first, as (description, entry text)."""
    return [(d, data) for d, data in conn.execute("SELECT description, data FROM edit_history WHERE path = ? ORDER BY seq", (path,))]


def put_history_entry(conn: sqlite3.Connection, path: str, seq: int, description: str, data: str) -> None:
    conn.execute("INSERT OR REPLACE INTO edit_history (path, seq, description, data) VALUES (?, ?, ?, ?)", (path, seq, description, data))
    conn.commit()


def truncate_history(conn: sqlite3.Connection, path: str, keep: int) -> None:
    """Forget every saved step from number `keep` on (the first `keep` stay)."""
    conn.execute("DELETE FROM edit_history WHERE path = ? AND seq >= ?", (path, keep))
    conn.commit()


def replace_history(conn: sqlite3.Connection, path: str, rows: list[tuple[int, str, str]]) -> None:
    """Save a photo's whole history again: rows are (step number, description, entry text)."""
    conn.execute("DELETE FROM edit_history WHERE path = ?", (path,))
    conn.executemany("INSERT INTO edit_history (path, seq, description, data) VALUES (?, ?, ?, ?)", [(path, *r) for r in rows])
    conn.commit()


def clear_history(conn: sqlite3.Connection, path: str) -> None:
    conn.execute("DELETE FROM edit_history WHERE path = ?", (path,))
    conn.commit()


def get_tags(conn: sqlite3.Connection, paths: list[str]) -> dict[str, list[str]]:
    """{path: its tags, A-Z} for the photos that have any."""
    found: dict[str, list[str]] = {}
    for i in range(0, len(paths), 500):
        chunk = paths[i : i + 500]
        marks = ",".join("?" * len(chunk))
        for path, tag in conn.execute(f"SELECT path, tag FROM tags WHERE path IN ({marks}) ORDER BY tag COLLATE NOCASE", chunk):
            found.setdefault(path, []).append(tag)
    return found


def all_tagged(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """Every tagged photo's tags - for the Workbench, which shows the whole library at once."""
    found: dict[str, list[str]] = {}
    for path, tag in conn.execute("SELECT path, tag FROM tags ORDER BY tag COLLATE NOCASE"):
        found.setdefault(path, []).append(tag)
    return found


def set_tags(conn: sqlite3.Connection, path: str, tags: list[str]) -> None:
    conn.execute("DELETE FROM tags WHERE path = ?", (path,))
    conn.executemany("INSERT OR IGNORE INTO tags (path, tag) VALUES (?, ?)", [(path, t) for t in tags])
    conn.commit()


def add_tags(conn: sqlite3.Connection, paths: list[str], tags: list[str]) -> None:
    conn.executemany("INSERT OR IGNORE INTO tags (path, tag) VALUES (?, ?)", [(p, t) for p in paths for t in tags])
    conn.commit()


def remove_tags(conn: sqlite3.Connection, paths: list[str], tags: list[str]) -> None:
    conn.executemany("DELETE FROM tags WHERE path = ? AND tag = ?", [(p, t) for p in paths for t in tags])
    conn.commit()


def define_tags(conn: sqlite3.Connection, tags: list[str]) -> None:
    """Make tags exist in the dictionary without putting them on any photo."""
    conn.executemany("INSERT OR IGNORE INTO tag_dictionary (tag) VALUES (?)", [(t,) for t in tags])
    conn.commit()


def defined_tags(conn: sqlite3.Connection) -> list[str]:
    return [t for (t,) in conn.execute("SELECT tag FROM tag_dictionary ORDER BY tag COLLATE NOCASE")]


def dictionary_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Every tag there is -> how many photos carry it (0 for one that exists but is on no photo)."""
    counts = {t: 0 for t in defined_tags(conn)}
    used = {t.casefold(): t for t in counts}
    for tag, n in tag_counts(conn):
        counts.pop(used.get(tag.casefold(), ""), None)
        counts[tag] = n
    return counts


def _like_inside(tag: str) -> str:
    return tag.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "/%"


def tag_paths(conn: sqlite3.Connection, tag: str, with_children: bool = False) -> list[str]:
    """The photos that carry a tag (and, with with_children, anything inside it)."""
    if with_children:
        rows = conn.execute("SELECT DISTINCT path FROM tags WHERE tag = ? COLLATE NOCASE OR tag LIKE ? ESCAPE '\\'", (tag, _like_inside(tag)))
    else:
        rows = conn.execute("SELECT DISTINCT path FROM tags WHERE tag = ? COLLATE NOCASE", (tag,))
    return [p for (p,) in rows]


def rename_tag(conn: sqlite3.Connection, old: str, new: str, with_children: bool = True) -> list[str]:
    """Rename a tag everywhere - and, with with_children, everything inside it moves along (People -> Family moves People/Kids to Family/Kids). A tag
    renamed onto one that already exists merges with it. Returns the photos whose tags changed."""
    pattern = "tag = ? COLLATE NOCASE OR tag LIKE ? ESCAPE '\\'" if with_children else "tag = ? COLLATE NOCASE"
    args = (old, _like_inside(old)) if with_children else (old,)
    affected: set[str] = set()
    for path, tag in conn.execute(f"SELECT path, tag FROM tags WHERE {pattern}", args).fetchall():
        target = new + tag[len(old):]
        if target.casefold() == tag.casefold():
            conn.execute("UPDATE tags SET tag = ? WHERE path = ? AND tag = ?", (target, path, tag))
        else:
            conn.execute("INSERT OR IGNORE INTO tags (path, tag) VALUES (?, ?)", (path, target))
            conn.execute("DELETE FROM tags WHERE path = ? AND tag = ?", (path, tag))
        affected.add(path)
    for (tag,) in conn.execute(f"SELECT tag FROM tag_dictionary WHERE {pattern}", args).fetchall():
        target = new + tag[len(old):]
        if target.casefold() == tag.casefold():
            conn.execute("UPDATE tag_dictionary SET tag = ? WHERE tag = ?", (target, tag))
        else:
            conn.execute("INSERT OR IGNORE INTO tag_dictionary (tag) VALUES (?)", (target,))
            conn.execute("DELETE FROM tag_dictionary WHERE tag = ?", (tag,))
    conn.commit()
    return sorted(affected)


def delete_tag(conn: sqlite3.Connection, tag: str, with_children: bool = False) -> list[str]:
    """Delete a tag from the dictionary and take it off every photo (with with_children, everything inside it too). Returns the photos that changed."""
    affected = tag_paths(conn, tag, with_children)
    pattern = "tag = ? COLLATE NOCASE OR tag LIKE ? ESCAPE '\\'" if with_children else "tag = ? COLLATE NOCASE"
    args = (tag, _like_inside(tag)) if with_children else (tag,)
    conn.execute(f"DELETE FROM tags WHERE {pattern}", args)
    conn.execute(f"DELETE FROM tag_dictionary WHERE {pattern}", args)
    conn.commit()
    return sorted(affected)


def save_collection(conn: sqlite3.Connection, name: str, state: dict) -> None:
    """Keep the Workbench's filters under a name (replacing a collection of that name)."""
    conn.execute(
        "INSERT INTO smart_collections (name, data, created) VALUES (?, ?, datetime('now', 'localtime')) ON CONFLICT(name) DO UPDATE SET data = excluded.data",
        (name, json.dumps(state)),
    )
    conn.commit()


def list_collections(conn: sqlite3.Connection) -> list[tuple[str, dict]]:
    out = []
    for name, data in conn.execute("SELECT name, data FROM smart_collections ORDER BY name COLLATE NOCASE"):
        try:
            out.append((name, json.loads(data)))
        except ValueError:
            continue
    return out


def delete_collection(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute("DELETE FROM smart_collections WHERE name = ?", (name,))
    conn.commit()
    return cur.rowcount > 0


def rename_collection(conn: sqlite3.Connection, old: str, new: str) -> bool:
    try:
        cur = conn.execute("UPDATE smart_collections SET name = ? WHERE name = ?", (new, old))
    except sqlite3.IntegrityError:
        return False
    conn.commit()
    return cur.rowcount > 0


ORIGINAL_VERSION = "Original"


def active_version(conn: sqlite3.Connection, path: str) -> str:
    row = conn.execute("SELECT name FROM photo_active_version WHERE path = ?", (path,)).fetchone()
    return row[0] if row else ORIGINAL_VERSION


def set_active_version(conn: sqlite3.Connection, path: str, name: str) -> None:
    if name.casefold() == ORIGINAL_VERSION.casefold():
        conn.execute("DELETE FROM photo_active_version WHERE path = ?", (path,))
    else:
        conn.execute("INSERT INTO photo_active_version (path, name) VALUES (?, ?) ON CONFLICT(path) DO UPDATE SET name = excluded.name", (path, name))
    conn.commit()


def stored_versions(conn: sqlite3.Connection, path: str) -> list[tuple[str, str]]:
    """The versions of a photo that are not being edited: (name, created), oldest first."""
    return conn.execute("SELECT name, created FROM photo_versions WHERE path = ? ORDER BY created, name COLLATE NOCASE", (path,)).fetchall()


def version_names(conn: sqlite3.Connection, path: str) -> list[str]:
    """Every version of a photo, the one being edited included, in a steady order: Original first, then the others by name."""
    names = {n for n, _c in stored_versions(conn, path)} | {active_version(conn, path)}
    return sorted(names, key=lambda n: (n.casefold() != ORIGINAL_VERSION.casefold(), n.casefold()))


def version_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """For every photo that has virtual copies, how many versions it has in all."""
    return {p: n + 1 for p, n in conn.execute("SELECT path, COUNT(*) FROM photo_versions GROUP BY path")}


def get_version_state(conn: sqlite3.Connection, path: str, name: str) -> dict | None:
    row = conn.execute("SELECT state FROM photo_versions WHERE path = ? AND name = ?", (path, name)).fetchone()
    return state_from_json(row[0]) if row else None


def put_version(conn: sqlite3.Connection, path: str, name: str, state: dict) -> None:
    conn.execute(
        "INSERT INTO photo_versions (path, name, state, created) VALUES (?, ?, ?, datetime('now', 'localtime')) "
        "ON CONFLICT(path, name) DO UPDATE SET state = excluded.state",
        (path, name, state_to_json(state)),
    )
    conn.commit()


def delete_version(conn: sqlite3.Connection, path: str, name: str) -> bool:
    cur = conn.execute("DELETE FROM photo_versions WHERE path = ? AND name = ?", (path, name))
    conn.commit()
    return cur.rowcount > 0


def rename_version(conn: sqlite3.Connection, path: str, old: str, new: str) -> bool:
    """Rename a stored version, or the one being edited (only its name changes)."""
    if old.casefold() == active_version(conn, path).casefold():
        set_active_version(conn, path, new)
        return True
    cur = conn.execute("UPDATE photo_versions SET name = ? WHERE path = ? AND name = ?", (new, path, old))
    conn.commit()
    return cur.rowcount > 0


def hide_photos(conn: sqlite3.Connection, paths: list[str]) -> None:
    """Take photos out of the Workbench and the filmstrip. Only the path is recorded; the files and their edits are untouched."""
    conn.executemany("INSERT OR IGNORE INTO hidden_photos (path, hidden_at) VALUES (?, datetime('now', 'localtime'))", [(p,) for p in paths])
    conn.commit()


def unhide_photos(conn: sqlite3.Connection, paths: list[str]) -> None:
    conn.executemany("DELETE FROM hidden_photos WHERE path = ?", [(p,) for p in paths])
    conn.commit()


def hidden_paths(conn: sqlite3.Connection) -> list[str]:
    return [p for (p,) in conn.execute("SELECT path FROM hidden_photos ORDER BY hidden_at DESC, path")]


def hidden_keys(conn: sqlite3.Connection) -> set[str]:
    """The hidden photos spelled one way (case and slashes folded) for comparing with any other spelling of a path."""
    return {os.path.normcase(os.path.abspath(p)) for p in hidden_paths(conn)}


def _tables_with(conn: sqlite3.Connection, column: str) -> list[tuple[str, list[str]]]:
    """The tables that have a column of this name, with all their columns (so a table added later is covered too)."""
    out = []
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'").fetchall():
        columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{name}")')]
        if column in columns:
            out.append((name, columns))
    return out


def move_photo_records(conn: sqlite3.Connection, old: str, new: str) -> None:
    """A photo file has another path now: everything saved for it (edits and their history, versions, snapshots, rating, flag, tags, film base, hidden state) follows it."""
    if old == new:
        return
    for name, _columns in _tables_with(conn, "path"):
        conn.execute(f'UPDATE OR REPLACE "{name}" SET path = ? WHERE path = ?', (new, old))
    conn.commit()


def copy_photo_records(conn: sqlite3.Connection, old: str, new: str) -> None:
    """Everything saved for a photo, saved again for another path (the original keeps its own)."""
    for name, columns in _tables_with(conn, "path"):
        names = ", ".join(f'"{c}"' for c in columns)
        picks = ", ".join("?" if c == "path" else f'"{c}"' for c in columns)
        conn.execute(f'INSERT OR REPLACE INTO "{name}" ({names}) SELECT {picks} FROM "{name}" WHERE path = ?', (new, old))
    conn.commit()


def forget_judgement(conn: sqlite3.Connection, path: str) -> None:
    """A photo's rating and flag are dropped (they judged another photo that was in its place)."""
    conn.execute("DELETE FROM flags WHERE path = ?", (path,))
    conn.execute("DELETE FROM ratings WHERE path = ?", (path,))
    conn.commit()


def copy_folder_records(conn: sqlite3.Connection, old_folder: str, new_folder: str) -> None:
    """A folder's own settings (its flat field, Roll Card, film base and light references) are given to a folder that photos were moved into - unless that folder has its own.
    Both folders are spelled as folder_key() spells them."""
    if old_folder == new_folder:
        return
    for name, columns in _tables_with(conn, "folder"):
        names = ", ".join(f'"{c}"' for c in columns)
        picks = ", ".join("?" if c == "folder" else f'"{c}"' for c in columns)
        conn.execute(f'INSERT OR IGNORE INTO "{name}" ({names}) SELECT {picks} FROM "{name}" WHERE folder = ?', (new_folder, old_folder))
    conn.commit()


def move_folder_records(conn: sqlite3.Connection, remap_path, old_folder: str, new_folder: str) -> None:
    """A whole folder was renamed (or moved): every photo in it has another path, so everything saved for those photos follows them (the same tables move_photo_records covers),
    and the settings kept for the folders themselves (flat field, Roll Card, film base, light references - those of its sub-folders too) are filed under the new names.
    `remap_path` gives the new path of a path (see features/library/folders.remap); a path outside the folder must come back as it was."""
    for name, _columns in _tables_with(conn, "path"):
        for (path,) in conn.execute(f'SELECT DISTINCT path FROM "{name}"').fetchall():
            moved = remap_path(path)
            if moved != path:
                conn.execute(f'UPDATE OR REPLACE "{name}" SET path = ? WHERE path = ?', (moved, path))
    for name, data in conn.execute("SELECT name, data FROM smart_collections").fetchall():   # a smart collection that looks in the folder looks in it under its new name
        try:
            state = json.loads(data)
        except ValueError:
            continue
        under = state.get("under") if isinstance(state, dict) else ""
        if under and remap_path(under) != under:
            state["under"] = remap_path(under)
            conn.execute("UPDATE smart_collections SET data = ? WHERE name = ?", (json.dumps(state), name))
    old_key, new_key = folder_key(old_folder, False), folder_key(new_folder, False)
    if old_key != new_key:
        inside = old_key.rstrip("\\/") + os.sep
        for name, _columns in _tables_with(conn, "folder"):
            for (key,) in conn.execute(f'SELECT DISTINCT folder FROM "{name}"').fetchall():
                if key == old_key or key.startswith(inside):
                    conn.execute(f'UPDATE OR REPLACE "{name}" SET folder = ? WHERE folder = ?', (new_key + key[len(old_key):], key))
    conn.commit()


def tag_counts(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    """Every tag in use with how many photos carry it, most used first."""
    return [(t, n) for t, n in conn.execute("SELECT tag, COUNT(*) FROM tags GROUP BY tag COLLATE NOCASE ORDER BY COUNT(*) DESC, tag COLLATE NOCASE")]


_UNTOUCHED = {
    "exposure_ev": 0.0, "rotation_quarter_turns": 0, "flip_h": False, "flip_v": False, "crop_rect": None, "saturation": 0.0,
    "temperature": 0.0, "tint": 0.0, "shadows": 0.0, "highlights": 0.0, "sharpen_amount": 0.0, "dust_auto": False,
    "scratch_lines": [], "heal_strokes": [], "clone_strokes": [], "dust_excluded": [], "error_marks": [], "modules_off": [], "masks": {}, "blends": {}, "retouch": {}, "instances": {}, "lens_corr": {}, "ai_dust": False, "marks": {}, "film_type": "auto", "invert_r": 0.0, "invert_g": 0.0, "invert_b": 0.0, "contrast": 0.0,
    "fine_rotation": 0.0, "distortion": 0.0, "keystone_v": 0.0, "keystone_h": 0.0, "chroma_denoise": 0.0, "local_contrast": 0.0, "print_snap": 0.0, "print_toe": 0.0, "print_toe_width": 2.5, "print_shoulder": 0.0, "print_shoulder_width": 2.5, "lab_fade": 0.0, "lab_glow": 0.0, "lab_by_shadows": 0.0, "lab_by_mids": 0.0, "lab_by_highs": 0.0, "lab_gm_shadows": 0.0, "lab_gm_mids": 0.0, "lab_gm_highs": 0.0, "lab_response": "none", "lab_response_amount": 1.0, "tone_curve_red": [(0, 0), (255, 255)], "tone_curve_green": [(0, 0), (255, 255)], "tone_curve_blue": [(0, 0), (255, 255)], "vibrance": 0.0, "mix_hue_red": 0.0, "mix_sat_red": 0.0, "mix_lum_red": 0.0, "mix_hue_orange": 0.0, "mix_sat_orange": 0.0, "mix_lum_orange": 0.0, "mix_hue_yellow": 0.0, "mix_sat_yellow": 0.0, "mix_lum_yellow": 0.0, "mix_hue_green": 0.0, "mix_sat_green": 0.0, "mix_lum_green": 0.0, "mix_hue_aqua": 0.0, "mix_sat_aqua": 0.0, "mix_lum_aqua": 0.0, "mix_hue_blue": 0.0, "mix_sat_blue": 0.0, "mix_lum_blue": 0.0, "mix_hue_purple": 0.0, "mix_sat_purple": 0.0, "mix_lum_purple": 0.0, "mix_hue_magenta": 0.0, "mix_sat_magenta": 0.0, "mix_lum_magenta": 0.0, "tone_hue_shadows": 0.0, "tone_amt_shadows": 0.0, "tone_hue_mids": 0.0, "tone_amt_mids": 0.0, "tone_hue_highs": 0.0, "tone_amt_highs": 0.0, "edge_holder": 0.0, "edge_bleed": 0.0, "edge_dodge": 0.0, "edge_reach": 0.08, "edge_mask": 0.0, "edge_feather": 0.5, "edge_mask_color": "black", "edge_mask_meter": True, "ec_tint": 0.0, "ec_warmth": 0.0, "ec_light": 0.0, "ec_size": 0.5, "ec_shape": 0.0, "hal_amount": 0.0, "carrier_width": 0.0, "gs_amount": 0.0, "dif_first": 0.0, "dif_second": 0.0, "dif_third": 0.0, "dif_fourth": 0.0, "dif_sharpness": 0.0, "dif_threshold": 0.0, "teq_band0": 0.0, "teq_band1": 0.0, "teq_band2": 0.0, "teq_band3": 0.0, "teq_band4": 0.0, "teq_band5": 0.0, "teq_band6": 0.0, "teq_band7": 0.0, "teq_band8": 0.0, "cbr_shadows_Y": 0.0, "cbr_shadows_C": 0.0, "cbr_shadows_H": 0.0, "cbr_midtones_Y": 0.0, "cbr_midtones_C": 0.0, "cbr_midtones_H": 0.0, "cbr_highlights_Y": 0.0, "cbr_highlights_C": 0.0, "cbr_highlights_H": 0.0, "cbr_global_Y": 0.0, "cbr_global_C": 0.0, "cbr_global_H": 0.0, "cbr_white_fulcrum": 0.0, "cbr_chroma_shadows": 0.0, "cbr_chroma_highlights": 0.0, "cbr_chroma_global": 0.0, "cbr_chroma_midtones": 0.0, "cbr_saturation_global": 0.0, "cbr_saturation_highlights": 0.0, "cbr_saturation_midtones": 0.0, "cbr_saturation_shadows": 0.0, "cbr_hue_angle": 0.0, "cbr_brilliance_global": 0.0, "cbr_brilliance_highlights": 0.0, "cbr_brilliance_midtones": 0.0, "cbr_brilliance_shadows": 0.0, "cbr_vibrance": 0.0, "cbr_contrast": 0.0, "wm_film": "off",
    "vignette": 0.0, "border": 0.0,
}


def is_untouched(state: dict, default_curve) -> bool:
    """True when a saved edit state is still what opening the photo gave it - nothing was changed."""
    if [tuple(p) for p in state["tone_curve_points"]] != [tuple(p) for p in default_curve]:
        return False
    if state.get("metering") not in (None, {}, {"engine": "print"}):
        return False
    return all(state[k] == v for k, v in _UNTOUCHED.items() if k in state)


def touched_paths(conn: sqlite3.Connection, paths: list[str], default_curve) -> set[str]:
    """Which of paths have edits that changed something (opening a photo saves a row, so a row alone does not mean it was edited)."""
    found: set[str] = set()
    for p in paths:
        state = load_edit_state(conn, p)
        if state is not None and not is_untouched(state, default_curve):
            found.add(p)
    return found


def get_photo_film_base(conn: sqlite3.Connection, path: str) -> tuple[int, int, int] | None:
    """A film base measured for this one photo (display RGB), if it has its own; otherwise it uses its roll's."""
    row = conn.execute("SELECT r, g, b FROM photo_film_base WHERE path = ?", (path,)).fetchone()
    return (int(row[0]), int(row[1]), int(row[2])) if row else None


def set_photo_film_base(conn: sqlite3.Connection, path: str, rgb) -> None:
    """Give a photo its own film base, or None to go back to its roll's."""
    if rgb is None:
        conn.execute("DELETE FROM photo_film_base WHERE path = ?", (path,))
    else:
        conn.execute("INSERT INTO photo_film_base (path, r, g, b) VALUES (?, ?, ?, ?) ON CONFLICT(path) DO UPDATE SET r=excluded.r, g=excluded.g, b=excluded.b",
                     (path, int(rgb[0]), int(rgb[1]), int(rgb[2])))
    conn.commit()


def effective_film_base(conn: sqlite3.Connection, path: str) -> tuple[int, int, int] | None:
    """The film base a photo is converted with: its own if it has one, else its roll's."""
    return get_photo_film_base(conn, path) or get_folder_base(conn, folder_key(path))


def get_folder_base(conn: sqlite3.Connection, folder: str) -> tuple[int, int, int] | None:
    row = conn.execute("SELECT r, g, b FROM folder_base WHERE folder = ?", (folder,)).fetchone()
    return (int(row[0]), int(row[1]), int(row[2])) if row else None


def set_folder_base(conn: sqlite3.Connection, folder: str, rgb: tuple[int, int, int]) -> None:
    conn.execute(
        "INSERT INTO folder_base (folder, r, g, b) VALUES (?, ?, ?, ?) ON CONFLICT(folder) DO UPDATE SET r=excluded.r, g=excluded.g, b=excluded.b",
        (folder, int(rgb[0]), int(rgb[1]), int(rgb[2])),
    )
    conn.commit()


def get_linear_ref(conn: sqlite3.Connection, folder: str, kind: str) -> tuple[tuple[float, float, float], int] | None:
    """A roll's sampled film base ("base") or clear backlight ("clear") in linear sensor units, with the pixel count it came from."""
    row = conn.execute("SELECT r, g, b, pixels FROM folder_linear_ref WHERE folder = ? AND kind = ?", (folder, kind)).fetchone()
    return ((float(row[0]), float(row[1]), float(row[2])), int(row[3])) if row else None


def set_linear_ref(conn: sqlite3.Connection, folder: str, kind: str, rgb, pixels: int = 0) -> None:
    if kind not in LINEAR_REF_KINDS:
        raise ValueError(f"unknown reference kind: {kind}")
    conn.execute(
        "INSERT INTO folder_linear_ref (folder, kind, r, g, b, pixels) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(folder, kind) DO UPDATE SET r=excluded.r, g=excluded.g, b=excluded.b, pixels=excluded.pixels",
        (folder, kind, float(rgb[0]), float(rgb[1]), float(rgb[2]), int(pixels)),
    )
    conn.commit()


def delete_linear_ref(conn: sqlite3.Connection, folder: str, kind: str) -> None:
    conn.execute("DELETE FROM folder_linear_ref WHERE folder = ? AND kind = ?", (folder, kind))
    conn.commit()


def get_inversion(conn: sqlite3.Connection, path: str) -> dict | None:
    """Which inversion method a photo uses. Kept apart from the edit state so presets, snapshots, history and sidecars are never touched by it;
    a photo with no row uses the standard method."""
    row = conn.execute("SELECT engine, profile_id, setup_id, white FROM photo_inversion WHERE path = ?", (path,)).fetchone()
    if row is None:
        return None
    try:
        white = [float(x) for x in json.loads(row[3])]
    except (ValueError, TypeError):
        white = []
    return {"engine": row[0], "profile_id": row[1], "setup_id": row[2], "white": white}


def set_inversion(conn: sqlite3.Connection, path: str, engine: str, profile_id: str = "", setup_id: str = "", white=()) -> None:
    if engine not in INVERSION_ENGINES:
        raise ValueError(f"unknown inversion engine: {engine}")
    conn.execute(
        "INSERT INTO photo_inversion (path, engine, profile_id, setup_id, white) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(path) DO UPDATE SET engine=excluded.engine, profile_id=excluded.profile_id, setup_id=excluded.setup_id, white=excluded.white",
        (path, engine, profile_id, setup_id, json.dumps([float(x) for x in white])),
    )
    conn.commit()


def delete_inversion(conn: sqlite3.Connection, path: str) -> None:
    conn.execute("DELETE FROM photo_inversion WHERE path = ?", (path,))
    conn.commit()


def delete_folder_base(conn: sqlite3.Connection, folder: str) -> None:
    conn.execute("DELETE FROM folder_base WHERE folder = ?", (folder,))
    conn.commit()
