import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SR = 48000


@pytest.fixture(scope="session")
def riff():
    """Three seconds of the built-in clean guitar riff."""
    from pedalfx.sources import demo_riff

    return demo_riff(SR)[: SR * 3]


def render(pedal, mono, block=256):
    out = np.zeros((2, len(mono)), dtype=np.float32)
    for s in range(0, len(mono), block):
        seg = mono[s:s + block]
        out[:, s:s + len(seg)] = pedal.process(np.stack([seg, seg]))
    return out
