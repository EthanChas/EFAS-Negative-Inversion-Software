"""Cutting an object out of a picture with a Segment Anything model (SAM 2.1), the way darktable's AI object mask does - onnxruntime + numpy + OpenCV, no Qt.

The model comes as two ONNX files (features/aimask/models.py): the *encoder* looks at the whole picture once and makes its embeddings (the slow part, a few seconds on the processor), and the
*decoder* turns them and a few clicks into a mask (fast, so every click can answer at once). A click is a point that is part of the object (label 1) or not (label 0). Giving the decoder
the previous answer back (`mask_input`) lets each click refine the cut instead of starting again.

The picture goes in as darktable sends it: the long side made 1024 pixels, the short side padded with zeros to a 1024 square, the colours scaled to 0..1 and normalised with the ImageNet
mean and spread. The decoder answers with three candidate masks at a quarter of that size (256 x 256, as logits) and a predicted overlap for each; the best is cropped back to the picture,
brought up to its size and turned into a probability.
"""

import os
import threading
from dataclasses import dataclass

import cv2
import numpy as np

SIDE = 1024                      # the square the picture is fitted into
LOW = 256                        # the size of the decoder's masks (a quarter of SIDE)
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
THRESHOLD = 0.5                  # a probability above this is part of the object


@dataclass
class Cut:
    """What the decoder made for a set of clicks: the probability of each picture pixel being the object, and the low-resolution mask to hand back for the next click."""

    probability: np.ndarray      # (h, w) float32, 0..1
    low_res: np.ndarray          # (1, 1, 256, 256) float32 logits
    score: float                 # the model's own estimate of how well the mask fits (its best predicted overlap)


def _session(path: str):
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.log_severity_level = 3
    return ort.InferenceSession(path, sess_options=options, providers=["CPUExecutionProvider"])


class ObjectSegmenter:
    """One SAM 2.1 model (a folder with encoder.onnx and decoder.onnx) and the picture it has looked at. Safe to call from one thread at a time (the caller serialises)."""

    def __init__(self, model_dir: str):
        self._dir = model_dir
        self._encoder = None
        self._decoder = None
        self._lock = threading.Lock()
        self._embeddings: list | None = None
        self._size: tuple[int, int] | None = None      # the picture's (height, width)
        self._scale = 1.0

    # ------------------------------------------------------------ loading
    def _load(self) -> None:
        with self._lock:
            if self._encoder is None:
                self._encoder = _session(os.path.join(self._dir, "encoder.onnx"))
                self._decoder = _session(os.path.join(self._dir, "decoder.onnx"))

    @property
    def ready(self) -> bool:
        return self._embeddings is not None

    @property
    def size(self) -> tuple[int, int] | None:
        return self._size

    # ------------------------------------------------------------ looking at the picture
    @staticmethod
    def prepare(rgb: np.ndarray) -> tuple[np.ndarray, float]:
        """(the encoder's input, the scale from picture pixels to its pixels) for an RGB uint8 picture."""
        h, w = rgb.shape[:2]
        scale = SIDE / max(h, w)
        nh, nw = max(1, round(h * scale)), max(1, round(w * scale))
        small = cv2.resize(np.ascontiguousarray(rgb[..., :3]), (nw, nh), interpolation=cv2.INTER_LINEAR).astype(np.float32) / 255.0
        small = (small - _MEAN) / _STD
        canvas = np.zeros((SIDE, SIDE, 3), dtype=np.float32)
        canvas[:nh, :nw] = small
        return np.ascontiguousarray(canvas.transpose(2, 0, 1)[None]), scale

    def encode(self, rgb: np.ndarray) -> None:
        """Look at a picture (RGB uint8): the slow step, once per picture."""
        self._load()
        data, scale = self.prepare(rgb)
        names = [o.name for o in self._encoder.get_outputs()]
        outputs = self._encoder.run(names, {self._encoder.get_inputs()[0].name: data})
        self._embeddings = dict(zip(names, outputs))
        self._size = (int(rgb.shape[0]), int(rgb.shape[1]))
        self._scale = scale

    def forget(self) -> None:
        self._embeddings = None
        self._size = None

    # ------------------------------------------------------------ answering clicks
    def cut(self, points: list[tuple[float, float]], labels: list[int], previous: Cut | None = None) -> Cut:
        """The mask for these clicks (picture pixels; label 1 is the object, 0 is not). `previous` is the answer to the clicks before, to refine."""
        if self._embeddings is None or self._size is None:
            raise RuntimeError("the picture has not been looked at yet")
        h, w = self._size
        coords = np.array([[x * self._scale, y * self._scale] for x, y in points] + [[0.0, 0.0]], dtype=np.float32)[None]      # (the decoder wants one padding point, label -1, at the end)
        tags = np.array([float(v) for v in labels] + [-1.0], dtype=np.float32)[None]
        low = previous.low_res if previous is not None else np.zeros((1, 1, LOW, LOW), dtype=np.float32)
        feeds = {"point_coords": coords, "point_labels": tags, "mask_input": low.astype(np.float32), "has_mask_input": np.array([1.0 if previous is not None else 0.0], dtype=np.float32)}
        for spec in self._decoder.get_inputs():
            if spec.name in self._embeddings:
                feeds[spec.name] = self._embeddings[spec.name]
        masks, scores = self._decoder.run(["masks", "iou_predictions"], feeds)
        best = int(np.argmax(scores[0]))
        logits = np.ascontiguousarray(masks[0, best], dtype=np.float32)                 # (256, 256) logits in the padded square
        full = cv2.resize(logits, (SIDE, SIDE), interpolation=cv2.INTER_LINEAR)
        nh, nw = max(1, round(h * self._scale)), max(1, round(w * self._scale))
        cropped = cv2.resize(full[:nh, :nw], (w, h), interpolation=cv2.INTER_LINEAR)
        probability = (1.0 / (1.0 + np.exp(-np.clip(cropped, -30.0, 30.0)))).astype(np.float32)
        return Cut(probability, np.ascontiguousarray(masks[0, best][None, None], dtype=np.float32), float(scores[0][best]))
