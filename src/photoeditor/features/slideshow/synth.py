"""The slideshow's built-in music: three short pieces made here from sine waves, plucked strings, an electric-piano voice and a little noise, so there is nothing to license. Each is a
loop that joins up with itself (the reverb tails and the last notes wrap round to the start), so it can play on and on - numpy only, no Qt.

    ambient   Drifting        60 beats a minute, slow pads on Am - F - C - G, a faint shimmer above, a long reverb
    arpeggio  Morning Light   76 beats a minute, plucked eighth notes over C - G - Am - F with a soft pad under them
    lofi      Night Reel      84 beats a minute, an electric-piano voice on Dm7 - G7 - Cmaj7 - Am7, a sine bass, brushed ticks and tape hiss, rolled off at the top

They are simple, and written to sit quietly behind photographs. The same seed gives the same sound each time."""
import numpy as np

SAMPLE_RATE = 44100
TRACKS = {
    "ambient": "Drifting (slow ambient pads)",
    "arpeggio": "Morning Light (soft plucked arpeggios)",
    "lofi": "Night Reel (warm lo-fi)",
}


def _hz(midi: float) -> float:
    return 440.0 * 2.0 ** ((midi - 69.0) / 12.0)


def _place(buf: np.ndarray, start: int, sound: np.ndarray) -> None:
    """Add a sound to the loop at `start`, wrapping past the end back to the beginning (so tails run into the start of the loop)."""
    n = buf.shape[0]
    idx = (start + np.arange(sound.shape[0])) % n
    np.add.at(buf, idx, sound)


def _stereo_place(buf: np.ndarray, start: int, sound: np.ndarray, pan: float = 0.0) -> None:
    left, right = np.sqrt(0.5 * (1.0 - pan)), np.sqrt(0.5 * (1.0 + pan))
    _place(buf[:, 0], start, sound * left)
    _place(buf[:, 1], start, sound * right)


def _pad(midis, seconds: float, attack: float, release: float, rng: np.random.Generator) -> np.ndarray:
    """Slow, slightly detuned sine and triangle-ish partials with a long fade in and out."""
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    out = np.zeros_like(t)
    for m in midis:
        for detune in (-0.07, 0.0, 0.08):
            f = _hz(m + detune)
            phase = rng.uniform(0, 2 * np.pi)
            out += np.sin(2 * np.pi * f * t + phase) + 0.25 * np.sin(2 * np.pi * 2 * f * t + phase) + 0.08 * np.sin(2 * np.pi * 3 * f * t + phase)
    env = np.minimum(1.0, t / attack) * np.minimum(1.0, (seconds - t) / release)
    return out * env * (0.6 / max(1, len(midis)))


def _pluck(midi: float, seconds: float, brightness: float = 1.0) -> np.ndarray:
    """A plucked string: harmonics that die away faster the higher they are."""
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    f = _hz(midi)
    out = np.zeros_like(t)
    for h in range(1, 9):
        out += (1.0 / h ** 1.2) * np.sin(2 * np.pi * f * h * t) * np.exp(-t * (2.2 + 2.0 * h * brightness))
    attack = np.minimum(1.0, t / 0.004)
    return out * attack


def _epiano(midi: float, seconds: float) -> np.ndarray:
    """A soft electric-piano voice: two sine operators, a bell-like one at 14 times the pitch that fades fast."""
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    f = _hz(midi)
    index = 1.6 * np.exp(-t * 5.0)
    carrier = np.sin(2 * np.pi * f * t + index * np.sin(2 * np.pi * f * t)) * np.exp(-t * 1.6)
    bell = 0.12 * np.sin(2 * np.pi * f * 14 * t) * np.exp(-t * 9.0)
    return (carrier + bell) * np.minimum(1.0, t / 0.006)


def _sine_bass(midi: float, seconds: float) -> np.ndarray:
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    f = _hz(midi)
    return (np.sin(2 * np.pi * f * t) + 0.15 * np.sin(2 * np.pi * 2 * f * t)) * np.exp(-t * 1.2) * np.minimum(1.0, t / 0.01)


def _tick(seconds: float, rng: np.random.Generator) -> np.ndarray:
    """A brushed tick: a few milliseconds of high-passed noise."""
    n = int(seconds * SAMPLE_RATE)
    noise = rng.standard_normal(n)
    noise = np.diff(noise, prepend=0.0)   # a crude high-pass
    return noise * np.exp(-np.arange(n) / SAMPLE_RATE * 90.0)


def _reverb(loop: np.ndarray, seconds: float, wet: float, rng: np.random.Generator) -> np.ndarray:
    """The loop through a synthetic room: a decaying burst of noise, a different one for each ear, multiplied in the frequency domain so the tail wraps round the loop."""
    n = loop.shape[0]
    length = min(int(seconds * SAMPLE_RATE), n // 2)
    t = np.arange(length) / SAMPLE_RATE
    out = np.empty_like(loop)
    spectrum = None
    for ch in range(2):
        ir = rng.standard_normal(length) * np.exp(-t * (6.9 / seconds))   # 60 dB down at `seconds`
        ir[0] = 0.0
        ir = np.convolve(ir, np.ones(6) / 6.0, mode="same")   # darker, like a real room
        ir /= np.sqrt(np.sum(ir ** 2)) + 1e-9
        spectrum = np.fft.rfft(ir, n)
        out[:, ch] = np.fft.irfft(np.fft.rfft(loop[:, ch]) * spectrum, n)
    return loop * (1.0 - wet) + out * wet * 1.8


def _lowpass(loop: np.ndarray, cutoff: float) -> np.ndarray:
    """Roll off everything above `cutoff` (Hz), smoothly, through the frequency domain (the loop stays a loop)."""
    n = loop.shape[0]
    freqs = np.fft.rfftfreq(n, 1.0 / SAMPLE_RATE)
    gain = 1.0 / (1.0 + (freqs / cutoff) ** 4)
    return np.stack([np.fft.irfft(np.fft.rfft(loop[:, ch]) * gain, n) for ch in range(2)], axis=1)


def _finish(loop: np.ndarray, peak: float = 0.7) -> np.ndarray:
    loop = loop - loop.mean(axis=0, keepdims=True)
    top = float(np.max(np.abs(loop))) or 1.0
    return np.tanh(loop / top * 1.4) / np.tanh(1.4) * peak


def _ambient(rng: np.random.Generator) -> np.ndarray:
    beat = 1.0
    bars = 8
    total = int(bars * 4 * beat * SAMPLE_RATE)
    loop = np.zeros((total, 2))
    chords = [([57, 60, 64, 67], 45), ([53, 57, 60, 64], 41), ([55, 60, 64, 67], 48), ([50, 55, 59, 62], 43)]
    for i, (notes, bass) in enumerate(chords):
        start = int(i * 8 * beat * SAMPLE_RATE)
        _stereo_place(loop, start, _pad(notes, 11.0, 2.5, 4.0, rng), pan=-0.2)
        _stereo_place(loop, start, _pad([n + 12 for n in notes[:3]], 11.0, 3.0, 4.5, rng) * 0.5, pan=0.25)
        _stereo_place(loop, start, _pad([bass], 11.0, 1.5, 4.0, rng) * 1.2, pan=0.0)
        t = np.arange(int(9 * SAMPLE_RATE)) / SAMPLE_RATE
        shimmer = np.sin(2 * np.pi * _hz(notes[-1] + 24) * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 0.17 * t + i)) * np.minimum(1.0, t / 3.0) * np.minimum(1.0, (9 - t) / 3.0) * 0.05
        _stereo_place(loop, start + int(1.0 * SAMPLE_RATE), shimmer, pan=0.4)
    return _finish(_reverb(loop, 4.0, 0.45, rng))


def _arpeggio(rng: np.random.Generator) -> np.ndarray:
    beat = 60.0 / 76.0
    bars = 8
    total = int(round(bars * 4 * beat * SAMPLE_RATE))
    loop = np.zeros((total, 2))
    chords = [([60, 64, 67, 72], 48), ([59, 62, 67, 71], 43), ([57, 60, 64, 69], 45), ([60, 65, 69, 72], 41)]
    pattern = (0, 1, 2, 3, 2, 1, 2, 1)   # eighth notes through the chord's four notes
    for i, (notes, bass) in enumerate(chords):
        bar0 = i * 2
        for bar in range(2):
            start_bar = (bar0 + bar) * 4 * beat
            for step, which in enumerate(pattern):
                start = int((start_bar + step * beat / 2.0) * SAMPLE_RATE)
                _stereo_place(loop, start, _pluck(notes[which] + (12 if step == 3 else 0), 2.2) * (0.5 if step % 2 else 0.7), pan=-0.35 + 0.1 * which)
            _stereo_place(loop, int(start_bar * SAMPLE_RATE), _pluck(bass, 3.0, 0.4) * 0.9, pan=0.0)
        _stereo_place(loop, int(bar0 * 4 * beat * SAMPLE_RATE), _pad(notes[:3], 8 * beat + 3.0, 2.0, 3.0, rng) * 0.35, pan=0.15)
    return _finish(_reverb(loop, 2.6, 0.32, rng))


def _lofi(rng: np.random.Generator) -> np.ndarray:
    beat = 60.0 / 84.0
    bars = 8
    total = int(round(bars * 4 * beat * SAMPLE_RATE))
    loop = np.zeros((total, 2))
    chords = [([62, 65, 69, 72], 38), ([55, 59, 62, 65], 43), ([60, 64, 67, 71], 36), ([57, 60, 64, 67], 45)]
    for i, (notes, bass) in enumerate(chords):
        for bar in range(2):
            start_bar = (i * 2 + bar) * 4 * beat
            for when, level in ((0.0, 1.0), (2.5, 0.75)):
                for k, n in enumerate(notes):
                    _stereo_place(loop, int((start_bar + when * beat + 0.012 * k) * SAMPLE_RATE), _epiano(n, 2.4) * 0.22 * level, pan=-0.3 + 0.2 * k)
            _stereo_place(loop, int(start_bar * SAMPLE_RATE), _sine_bass(bass, 1.8) * 0.9, pan=0.0)
            _stereo_place(loop, int((start_bar + 2 * beat) * SAMPLE_RATE), _sine_bass(bass + (7 if bar else 0), 1.5) * 0.7, pan=0.0)
            for step in range(8):
                if step % 2:
                    _stereo_place(loop, int((start_bar + step * beat / 2.0) * SAMPLE_RATE), _tick(0.06, rng) * 0.05, pan=0.3 if step % 4 == 1 else -0.3)
    hiss = np.diff(rng.standard_normal((total, 2)), axis=0, prepend=0.0) * 0.004
    loop = loop + hiss
    return _finish(_lowpass(_reverb(loop, 1.8, 0.2, rng), 5500.0))


_MAKERS = {"ambient": _ambient, "arpeggio": _arpeggio, "lofi": _lofi}


def make_track(track_id: str) -> np.ndarray:
    """The loop for a built-in track: float64 stereo samples (n, 2) between -1 and 1, at SAMPLE_RATE."""
    if track_id not in _MAKERS:
        raise KeyError(track_id)
    return _MAKERS[track_id](np.random.default_rng(sum(map(ord, track_id))))


def write_wav(path: str, samples: np.ndarray) -> None:
    """Write (n, 2) float samples as a 16-bit stereo WAV file."""
    import wave

    data = np.clip(np.rint(samples * 32767.0), -32768, 32767).astype("<i2")
    with wave.open(path, "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(SAMPLE_RATE)
        f.writeframes(data.tobytes())
