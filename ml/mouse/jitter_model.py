"""
Mouse micro-jitter model.

Captures the user's hand tremor characteristics — the tiny,
involuntary oscillations visible during slow movements and hovering.

Extracts jitter parameters (amplitude, frequency) from recorded
paths by analyzing high-frequency deviations from the smooth path.
Uses Perlin noise at inference to generate realistic biological tremor.
"""

import logging
import pickle
from pathlib import Path

import numpy as np

from ml.preprocessing.mouse_data import MouseDataset

logger = logging.getLogger(__name__)

# Minimum movements to analyze for jitter
_MIN_MOVEMENTS = 50

# Only analyze slow/hover segments where jitter is visible (px/ms)
_MAX_SPEED_FOR_JITTER = 0.5


class JitterModel:
    """
    Micro-jitter parameter model.

    Extracts amplitude and frequency characteristics of hand tremor
    from recorded mouse data. At inference, generates Perlin-like
    noise with matching parameters.
    """

    def __init__(self):
        self._amplitude_mean_px: float = 0.0
        self._amplitude_std_px: float = 0.0
        self._frequency_hz: float = 0.0
        self._trained = False

    @property
    def is_trained(self) -> bool:
        return self._trained

    def train(self, dataset: MouseDataset) -> dict:
        """
        Extract jitter parameters from slow-movement segments.

        Analyzes path deviations from a smoothed version to isolate
        the high-frequency tremor component.
        """
        logger.info("Training jitter model...")

        amplitudes = []

        for movement in dataset.movements:
            if len(movement.path_x) < 20:
                continue

            amp = self._extract_jitter_amplitude(movement)
            if amp is not None:
                amplitudes.append(amp)

        if len(amplitudes) < _MIN_MOVEMENTS:
            logger.info(
                f"  Only {len(amplitudes)} jitter samples — using defaults"
            )
            # Use reasonable defaults for human hand tremor
            self._amplitude_mean_px = 0.5
            self._amplitude_std_px = 0.3
            self._frequency_hz = 8.0  # ~8Hz physiological tremor
            self._trained = True

            return {
                "status": "trained_defaults",
                "samples": len(amplitudes),
                "amplitude_px": self._amplitude_mean_px,
            }

        amp_arr = np.array(amplitudes)
        self._amplitude_mean_px = float(np.mean(amp_arr))
        self._amplitude_std_px = float(np.std(amp_arr))
        # Human physiological tremor is typically 6-12 Hz
        self._frequency_hz = 8.0
        self._trained = True

        logger.info(
            f"  Jitter model trained from {len(amplitudes)} segments\n"
            f"  Amplitude: {self._amplitude_mean_px:.2f} ± "
            f"{self._amplitude_std_px:.2f} px"
        )

        return {
            "status": "trained",
            "samples": len(amplitudes),
            "amplitude_mean_px": self._amplitude_mean_px,
            "amplitude_std_px": self._amplitude_std_px,
            "frequency_hz": self._frequency_hz,
        }

    def generate_jitter(
        self, n_points: int, dt_us: np.ndarray,
        rng: np.random.Generator | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Generate jitter displacement for a path.

        Returns (jitter_x, jitter_y) arrays to add to path coordinates.
        Uses smoothed random noise to simulate hand tremor.
        """
        if not self._trained:
            return np.zeros(n_points), np.zeros(n_points)

        if rng is None:
            rng = np.random.default_rng()

        if n_points < 2:
            return np.zeros(n_points), np.zeros(n_points)

        # Sample amplitude for this movement
        amplitude = rng.normal(self._amplitude_mean_px, self._amplitude_std_px)
        amplitude = max(amplitude, 0.1)

        # Compute time positions (seconds) for frequency calculation
        cumulative_us = np.cumsum(dt_us)
        t_seconds = cumulative_us / 1_000_000

        # Generate two independent noise channels (x, y)
        # Use smoothed random walk to approximate Perlin noise
        phase_x = rng.uniform(0, 2 * np.pi)
        phase_y = rng.uniform(0, 2 * np.pi)

        # Multi-octave noise for more natural tremor
        freq = self._frequency_hz
        jitter_x = np.zeros(n_points)
        jitter_y = np.zeros(n_points)

        for octave, (amp_scale, freq_scale) in enumerate([
            (1.0, 1.0), (0.5, 2.0), (0.25, 4.0)
        ]):
            jitter_x += amp_scale * np.sin(
                2 * np.pi * freq * freq_scale * t_seconds + phase_x + octave * 1.7
            )
            jitter_y += amp_scale * np.sin(
                2 * np.pi * freq * freq_scale * t_seconds + phase_y + octave * 2.3
            )

        # Normalize and scale
        max_val = max(np.abs(jitter_x).max(), np.abs(jitter_y).max(), 1e-6)
        jitter_x = jitter_x / max_val * amplitude
        jitter_y = jitter_y / max_val * amplitude

        # Fade in/out: no jitter at path start/end
        fade = np.ones(n_points)
        fade_len = min(n_points // 5, 10)
        if fade_len > 0:
            fade[:fade_len] = np.linspace(0, 1, fade_len)
            fade[-fade_len:] = np.linspace(1, 0, fade_len)
        jitter_x *= fade
        jitter_y *= fade

        return jitter_x, jitter_y

    def save(self, path: Path) -> None:
        data = {
            "amplitude_mean_px": self._amplitude_mean_px,
            "amplitude_std_px": self._amplitude_std_px,
            "frequency_hz": self._frequency_hz,
        }
        with open(path, "wb") as f:
            pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
        logger.info(f"  Jitter model saved to {path}")

    @classmethod
    def load(cls, path: Path) -> "JitterModel":
        with open(path, "rb") as f:
            data = pickle.load(f)
        model = cls()
        model._amplitude_mean_px = data["amplitude_mean_px"]
        model._amplitude_std_px = data["amplitude_std_px"]
        model._frequency_hz = data["frequency_hz"]
        model._trained = True
        return model

    @staticmethod
    def _extract_jitter_amplitude(movement) -> float | None:
        """
        Extract jitter amplitude from slow segments of a movement.

        Compares the raw path to a smoothed version — the RMS
        deviation is the jitter amplitude.
        """
        px = movement.path_x.astype(np.float64)
        py = movement.path_y.astype(np.float64)
        t_ns = movement.path_t_ns.astype(np.float64)

        n = len(px)

        # Compute instantaneous speed
        dx = np.diff(px)
        dy = np.diff(py)
        dt = np.diff(t_ns)
        valid = dt > 0
        if valid.sum() < 10:
            return None

        speeds = np.sqrt(dx[valid] ** 2 + dy[valid] ** 2) / (dt[valid] / 1_000_000)

        # Only analyze slow segments
        slow_mask = speeds < _MAX_SPEED_FOR_JITTER
        if slow_mask.sum() < 5:
            return None

        # Smooth the path with a moving average
        kernel_size = min(7, n // 3)
        if kernel_size < 3:
            return None
        kernel = np.ones(kernel_size) / kernel_size
        smooth_x = np.convolve(px, kernel, mode="same")
        smooth_y = np.convolve(py, kernel, mode="same")

        # RMS deviation from smooth path
        dev_x = px - smooth_x
        dev_y = py - smooth_y
        deviations = np.sqrt(dev_x ** 2 + dev_y ** 2)

        # Use median to be robust against outliers
        amplitude = float(np.median(deviations))

        # Filter unreasonable values
        if amplitude < 0.01 or amplitude > 10.0:
            return None

        return amplitude
