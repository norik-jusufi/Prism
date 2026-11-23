"""PRISM sound effects: key clicks and digital blips for the boot intro.

Nothing is shipped as audio files: each effect is synthesized here (a few
milliseconds of noise and square waves) into a small WAV in the data dir the
first time, then played with Qt's QSoundEffect. Without Qt Multimedia, or
without an audio device, every call is a silent no-op.

Off: "introSound": false in settings.json (or press M during the intro).
"""

from __future__ import annotations

import math
import random
import struct
import wave
from pathlib import Path

from PyQt6.QtCore import QObject, QUrl

try:
    from PyQt6.QtMultimedia import QSoundEffect
except ImportError:          # Qt Multimedia missing (some Linux installs): no sound
    QSoundEffect = None

RATE = 22050
VERSION = 1                  # bump to regenerate the WAVs after changing a sound


# ------------------------------------------------------------ synthesis
def _tone(freq: float, t: float) -> float:
    """Soft square wave: fundamental plus a little of the 3rd and 5th."""
    x = 2 * math.pi * freq * t
    return math.sin(x) + math.sin(3 * x) / 5 + math.sin(5 * x) / 12


def _click(seed: int, pitch: float) -> list[float]:
    """A mechanical key: a sharp filtered noise tick and a short body thump."""
    rnd = random.Random(seed)
    n = int(RATE * 0.045)
    out, lp = [], 0.0
    for i in range(n):
        t = i / RATE
        noise = rnd.uniform(-1, 1)
        lp += (noise - lp) * 0.55                        # one-pole low-pass: less hiss
        tick = lp * math.exp(-t * 260)
        body = math.sin(2 * math.pi * pitch * t) * math.exp(-t * 90) * 0.55
        out.append((tick + body) * 0.55)
    return out


def _enter() -> list[float]:
    """The return key: a deeper, longer clack."""
    rnd = random.Random(7)
    n = int(RATE * 0.09)
    out, lp = [], 0.0
    for i in range(n):
        t = i / RATE
        lp += (rnd.uniform(-1, 1) - lp) * 0.35
        out.append((lp * math.exp(-t * 120) + math.sin(2 * math.pi * 120 * t) * math.exp(-t * 45) * 0.8) * 0.6)
    return out


def _blip(f0: float, f1: float, dur: float, vol: float = 0.22) -> list[float]:
    """A short digital chirp gliding from f0 to f1."""
    n = int(RATE * dur)
    out, phase = [], 0.0
    for i in range(n):
        k = i / n
        phase += (f0 + (f1 - f0) * k) / RATE
        env = min(1.0, i / (RATE * 0.002)) * (1 - k) ** 2
        out.append(_tone(1, phase) * env * vol)
    return out


def _data(seed: int, dur: float = 0.11) -> list[float]:
    """Modem-like burst: a random tone every few milliseconds."""
    rnd = random.Random(seed)
    n = int(RATE * dur)
    step = int(RATE * 0.009)
    out, phase, f = [], 0.0, 1000.0
    for i in range(n):
        if i % step == 0:
            f = rnd.choice((660, 880, 990, 1320, 1480, 1760, 2093))
        phase += f / RATE
        env = min(1.0, i / 40) * (1 - i / n)
        out.append(_tone(1, phase) * env * 0.12)
    return out


def _notes(freqs: list[float], each: float, vol: float, tail: float = 0.0) -> list[float]:
    """Notes one after another (an arpeggio); the last one rings for `tail` more seconds."""
    out: list[float] = []
    for j, f in enumerate(freqs):
        dur = each + (tail if j == len(freqs) - 1 else 0)
        n = int(RATE * dur)
        for i in range(n):
            t = i / RATE
            env = min(1.0, i / (RATE * 0.003)) * math.exp(-t * (5 if j == len(freqs) - 1 and tail else 28))
            out.append((math.sin(2 * math.pi * f * t) * 0.8 + _tone(f, t) * 0.2) * env * vol)
    return out


def _chord(freqs: list[float], dur: float, vol: float) -> list[float]:
    """Soft swell and decay: the "ready" chime."""
    n = int(RATE * dur)
    out = []
    for i in range(n):
        t = i / RATE
        env = min(1.0, t / 0.03) * math.exp(-t * 4.2)
        s = sum(math.sin(2 * math.pi * f * t) + 0.25 * math.sin(4 * math.pi * f * t) for f in freqs)
        out.append(s / len(freqs) * env * vol)
    return out


SOUNDS = {
    "key1": lambda: _click(1, 190),
    "key2": lambda: _click(2, 230),
    "key3": lambda: _click(3, 170),
    "key4": lambda: _click(4, 210),
    "enter": _enter,
    "blip": lambda: _blip(1500, 1100, 0.045),
    "blip2": lambda: _blip(900, 1400, 0.05, 0.18),
    "data": lambda: _data(11),
    "ok": lambda: _notes([1319, 1760], 0.035, 0.16),
    "warn": lambda: _notes([440, 330], 0.06, 0.18),
    "tick": lambda: _blip(2400, 2200, 0.018, 0.12),
    "ready": lambda: _chord([523.25, 783.99, 1046.5, 1567.98], 0.9, 0.3),
}
KEYS = ("key1", "key2", "key3", "key4")
POOL = {"key1": 2, "key2": 2, "key3": 2, "key4": 2, "tick": 3, "blip": 2, "data": 2}


def _write(path: Path, samples: list[float]) -> None:
    frames = b"".join(struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767)) for s in samples)
    tmp = path.with_suffix(".tmp")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(frames)
    tmp.replace(path)


def sound_files(folder: Path) -> dict[str, Path]:
    """Synthesize any missing WAV into `folder`; returns name -> path."""
    folder.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, make in SOUNDS.items():
        path = folder / f"v{VERSION}-{name}.wav"
        if not path.exists():
            _write(path, make())
        files[name] = path
    return files


# ------------------------------------------------------------- playback
class Sfx(QObject):
    """Plays the effects above. Every method is safe to call when sound is
    unavailable or off; then nothing happens."""

    def __init__(self, folder: Path, enabled: bool = True, parent: QObject | None = None):
        super().__init__(parent)
        self.enabled = enabled
        self._fx: dict[str, list] = {}
        self._next: dict[str, int] = {}
        self._rnd = random.Random(42)
        if QSoundEffect is None or not enabled:
            return
        try:
            files = sound_files(folder)
        except OSError:
            return
        for name, path in files.items():
            effects = []
            for _ in range(POOL.get(name, 1)):    # several copies so quick repeats overlap
                fx = QSoundEffect(self)
                fx.setSource(QUrl.fromLocalFile(str(path)))
                fx.setVolume(0.6)
                effects.append(fx)
            self._fx[name] = effects
            self._next[name] = 0

    @property
    def available(self) -> bool:
        return bool(self._fx)

    def play(self, name: str, volume: float = 1.0) -> None:
        if not self.enabled or name not in self._fx:
            return
        effects = self._fx[name]
        i = self._next[name]
        self._next[name] = (i + 1) % len(effects)
        fx = effects[i]
        fx.setVolume(0.6 * volume)
        fx.play()

    def key(self) -> None:
        """One key press: a random one of four clicks at a slightly random volume."""
        self.play(self._rnd.choice(KEYS), self._rnd.uniform(0.7, 1.0))

    def stop(self) -> None:
        for effects in self._fx.values():
            for fx in effects:
                fx.stop()
