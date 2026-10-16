"""Making the slideshow into an MP4 video - numpy, OpenCV and Pillow, with ffmpeg when it can be found; no Qt.

Each photo is fitted into the video's frame on black (nothing is cropped), its caption burned in if wanted, and held for the chosen seconds; with Crossfade the first moments of each
photo are a fade from the one before, as on screen, so the video is exactly (photos x seconds) long. Frames go to the encoder one after another, so a long show never sits in memory.

ffmpeg (found through the setting "ffmpeg_path", then the PATH, then the imageio-ffmpeg package if it is installed) makes an H.264 video with the music mixed in as AAC - looped to
the length of the show, at the chosen volume, and faded out over its last two seconds. Without ffmpeg OpenCV's own MP4 writer is used: a video with the older MPEG-4 codec and no sound."""
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass

import numpy as np

RESOLUTIONS = {"1280x720": ("HD  1280 × 720", (1280, 720)), "1920x1080": ("Full HD  1920 × 1080", (1920, 1080)),
               "2560x1440": ("QHD  2560 × 1440", (2560, 1440)), "3840x2160": ("4K  3840 × 2160", (3840, 2160))}
RESOLUTION_DEFAULT = "1920x1080"
FPS_CHOICES = (24, 25, 30)
FPS_DEFAULT = 30
MUSIC_FADE_OUT = 2.0   # seconds


@dataclass
class ExportOptions:
    size: tuple[int, int] = (1920, 1080)
    fps: int = FPS_DEFAULT
    seconds: float = 5.0          # each photo
    fade: float = 0.7             # the crossfade into a photo (0 for a cut)
    captions: bool = True
    music: str | None = None      # a .wav or .mp3 file, or None
    volume: float = 0.5           # 0-1
    ffmpeg: str | None = None     # the program to encode with, or None for OpenCV's writer


# ---------------------------------------------------------------------------------------------------------- ffmpeg
def find_ffmpeg(configured: str = "") -> str | None:
    """The ffmpeg program to use: the one the setting names (if it is there), else the one on the PATH, else the one the imageio-ffmpeg package carries."""
    if configured and os.path.isfile(configured):
        return configured
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        return exe if exe and os.path.isfile(exe) else None
    except Exception:
        return None


def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


_encoder_cache: dict[str, str] = {}


def video_codec(ffmpeg: str) -> str:
    """libx264 when this ffmpeg has it; else mpeg4, which every ffmpeg has."""
    if ffmpeg not in _encoder_cache:
        try:
            out = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=20, creationflags=_no_window()).stdout
        except (OSError, subprocess.SubprocessError):
            out = ""
        _encoder_cache[ffmpeg] = "libx264" if " libx264 " in out else "mpeg4"
    return _encoder_cache[ffmpeg]


# ---------------------------------------------------------------------------------------------------------- frames
def hold_frames(seconds: float, fps: int) -> int:
    return max(1, int(round(float(seconds) * fps)))


def slide_plan(seconds: float, fade: float, fps: int, first: bool) -> tuple[int, int]:
    """(frames of crossfade, frames held still) for one photo: together they are the photo's whole time on screen. The first photo, and a cut, have no fade."""
    total = hold_frames(seconds, fps)
    if first or fade <= 0:
        return 0, total
    fade_frames = min(int(round(fade * fps)), total - 1)
    return fade_frames, total - fade_frames


def total_seconds(photos: int, seconds: float, fps: int) -> float:
    return photos * hold_frames(seconds, fps) / float(fps)


def fit_frame(image: np.ndarray, width: int, height: int, caption: str = "") -> np.ndarray:
    """The picture (8-bit RGB) scaled to fit the frame, centred on black, with the caption burned in along the bottom when there is one."""
    import cv2

    h, w = image.shape[:2]
    scale = min(width / w, height / h)
    new_w, new_h = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    scaled = cv2.resize(np.ascontiguousarray(image[..., :3]), (new_w, new_h), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LANCZOS4)
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    y, x = (height - new_h) // 2, (width - new_w) // 2
    frame[y:y + new_h, x:x + new_w] = scaled
    return _burn_caption(frame, caption) if caption else frame


def _burn_caption(frame: np.ndarray, caption: str) -> np.ndarray:
    from PIL import Image, ImageDraw, ImageFont

    height, width = frame.shape[:2]
    size = max(14, height // 32)
    try:
        font = ImageFont.load_default(size=size)
    except TypeError:   # an older Pillow: the small built-in font
        font = ImageFont.load_default()
    base = Image.fromarray(frame).convert("RGBA")
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    pad = size // 2
    left, top, right, bottom = draw.textbbox((0, 0), caption, font=font)
    box_w, box_h = right - left + 2 * pad, bottom - top + pad
    x0, y1 = pad * 2, height - pad * 2
    draw.rectangle((x0, y1 - box_h, min(width - pad, x0 + box_w), y1), fill=(0, 0, 0, 150))
    draw.text((x0 + pad - left, y1 - box_h + pad // 2 - top), caption, font=font, fill=(235, 235, 235, 255))
    return np.asarray(Image.alpha_composite(base, layer).convert("RGB"))


def crossfade(a: np.ndarray, b: np.ndarray, alpha: float) -> np.ndarray:
    import cv2

    return cv2.addWeighted(a, 1.0 - alpha, b, alpha, 0.0)


# ---------------------------------------------------------------------------------------------------------- the encoder
class VideoEncoder:
    """Takes frames one at a time and writes an MP4. close(ok) finishes the file (or throws away the partial one) and returns an error message ("" when all went well)."""

    def __init__(self, out_path: str, options: ExportOptions, seconds: float):
        self.out_path = out_path
        self.options = options
        self._partial = os.path.join(os.path.dirname(os.path.abspath(out_path)), "." + os.path.splitext(os.path.basename(out_path))[0] + ".partial.mp4")
        self._proc: subprocess.Popen | None = None
        self._writer = None
        self._log_path = ""
        self.backend = "ffmpeg" if options.ffmpeg else "opencv"
        self.has_audio = False
        width, height = options.size
        if options.ffmpeg:
            self._start_ffmpeg(width, height, seconds)
        else:
            import cv2

            self._writer = cv2.VideoWriter(self._partial, cv2.VideoWriter_fourcc(*"mp4v"), options.fps, (width, height))
            if not self._writer.isOpened():
                raise OSError("OpenCV could not open a video file to write to.")

    def _start_ffmpeg(self, width: int, height: int, seconds: float) -> None:
        o = self.options
        cmd = [o.ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", str(o.fps), "-i", "-"]
        music = o.music if o.music and os.path.isfile(o.music) else None
        if music:
            cmd += ["-stream_loop", "-1", "-i", music, "-map", "0:v:0", "-map", "1:a:0"]
        codec = video_codec(o.ffmpeg)
        cmd += ["-c:v", codec] + (["-preset", "medium", "-crf", "20"] if codec == "libx264" else ["-q:v", "3"]) + ["-pix_fmt", "yuv420p"]
        if music:
            fade = min(MUSIC_FADE_OUT, seconds)
            cmd += ["-c:a", "aac", "-b:a", "192k", "-af", f"volume={max(0.0, min(1.0, o.volume)):.3f},afade=t=out:st={max(0.0, seconds - fade):.3f}:d={fade:.3f}", "-shortest"]
            self.has_audio = True
        cmd += ["-movflags", "+faststart", "-f", "mp4", self._partial]
        fd, self._log_path = tempfile.mkstemp(suffix=".log", prefix="efas-ffmpeg-")
        self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=fd, creationflags=_no_window())
        os.close(fd)

    def write(self, frame: np.ndarray, repeat: int = 1) -> None:
        if self._proc is not None:
            data = np.ascontiguousarray(frame).tobytes()
            try:
                for _ in range(repeat):
                    self._proc.stdin.write(data)
            except (BrokenPipeError, OSError) as exc:
                raise OSError(self._ffmpeg_error() or f"ffmpeg stopped ({exc})") from exc
        else:
            import cv2

            bgr = np.ascontiguousarray(frame[..., ::-1])
            for _ in range(repeat):
                self._writer.write(bgr)

    def _ffmpeg_error(self) -> str:
        try:
            with open(self._log_path, "r", encoding="utf-8", errors="replace") as f:
                lines = [ln.strip() for ln in f.read().splitlines() if ln.strip()]
            return lines[-1] if lines else ""
        except OSError:
            return ""

    def close(self, ok: bool = True) -> str:
        error = ""
        if self._proc is not None:
            try:
                if ok:
                    self._proc.stdin.close()
                    code = self._proc.wait(timeout=600)
                    if code != 0:
                        error = self._ffmpeg_error() or f"ffmpeg stopped with code {code}"
                        ok = False
                else:
                    self._proc.kill()
                    self._proc.wait(timeout=20)
            except (OSError, subprocess.SubprocessError) as exc:
                error, ok = error or str(exc), False
                self._proc.kill()
            if self._log_path:
                try:
                    os.remove(self._log_path)
                except OSError:
                    pass
        elif self._writer is not None:
            self._writer.release()
        if ok and os.path.isfile(self._partial):
            os.replace(self._partial, self.out_path)
        elif os.path.isfile(self._partial):
            try:
                os.remove(self._partial)
            except OSError:
                pass
        return error


# ---------------------------------------------------------------------------------------------------------- the whole export
def export_slideshow(items: list[tuple[str, str]], out_path: str, options: ExportOptions, render, progress=None, cancelled=None) -> dict:
    """Make the video. items are (path, caption) in show order; render(path) -> the picture as 8-bit RGB (the caller decides edits and size). progress(done, total, name) is called after each photo; cancelled() is polled.
    -> {"path", "slides", "failed": [(path, why)], "cancelled", "error", "backend", "audio", "seconds"}"""
    summary = {"path": None, "slides": 0, "failed": [], "cancelled": False, "error": "", "backend": "", "audio": False, "seconds": 0.0}
    width, height = options.size
    encoder = None
    previous = None
    ok = True
    try:
        seconds_total = total_seconds(len(items), options.seconds, options.fps)
        encoder = VideoEncoder(out_path, options, seconds_total)
        summary["backend"], summary["audio"] = encoder.backend, encoder.has_audio
        for done, (path, caption) in enumerate(items):
            if cancelled is not None and cancelled():
                summary["cancelled"], ok = True, False
                break
            try:
                frame = fit_frame(render(path), width, height, caption if options.captions else "")
            except Exception as exc:
                summary["failed"].append((path, f"{type(exc).__name__}: {exc}"))
                if progress is not None:
                    progress(done + 1, len(items), os.path.basename(path))
                continue
            fade_frames, still_frames = slide_plan(options.seconds, options.fade, options.fps, previous is None)
            for k in range(1, fade_frames + 1):
                encoder.write(crossfade(previous, frame, k / (fade_frames + 1.0)))
            encoder.write(frame, still_frames)
            previous = frame
            summary["slides"] += 1
            if progress is not None:
                progress(done + 1, len(items), os.path.basename(path))
        if ok and summary["slides"] == 0:
            ok = False
            summary["error"] = "None of the photos could be made into a picture."
    except Exception as exc:
        ok = False
        summary["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if encoder is not None:
            error = encoder.close(ok)
            if error and not summary["error"]:
                summary["error"] = error
            ok = ok and not error
    if ok:
        summary["path"] = out_path
        summary["seconds"] = total_seconds(summary["slides"], options.seconds, options.fps)
    return summary
