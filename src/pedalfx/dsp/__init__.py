"""Pedal registry."""

from __future__ import annotations

from .console import PrismConsole
from .core import Param, Pedal
from .looper import Looper
from .pedals import (
    Boost,
    Chorus,
    Compressor,
    Delay,
    Distortion,
    Phaser,
    Reverb,
    Tremolo,
)
from .tuner import Tuner

# Browser order, roughly the order you would wire them on a real board.
PEDAL_CLASSES = (Tuner, Compressor, Boost, Distortion, Phaser, Chorus, Tremolo,
                 Delay, Reverb, PrismConsole, Looper)
REGISTRY = {cls.TYPE: cls for cls in PEDAL_CLASSES}


def create_pedal(type_name: str, sr: float = 48000.0) -> Pedal:
    return REGISTRY[type_name](sr)


def pedal_from_dict(data: dict, sr: float = 48000.0) -> Pedal:
    pedal = create_pedal(data["type"], sr)
    pedal.load_dict(data)
    return pedal


__all__ = ["PEDAL_CLASSES", "REGISTRY", "Looper", "Param", "Pedal", "PrismConsole",
           "Tuner", "create_pedal", "pedal_from_dict"]
