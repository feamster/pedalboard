"""Board presets (pedal order + every knob) and session persistence."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .dsp import pedal_from_dict

FORMAT_VERSION = 2


REPO_BOARDS = Path(__file__).resolve().parents[2] / "boards"


def app_dir() -> Path:
    """Per-machine state (the session file): ``~/.pedalboard``."""
    return Path(os.environ.get("PEDALFX_HOME", Path.home() / ".pedalboard"))


def migrate_home() -> None:
    """Move state from ``~/.pedalboard-effects`` (the repo's old name) to ``~/.pedalboard``.

    Nothing already in the new folder is overwritten - v1 kept a ``presets/``
    folder there, which v2 still leaves alone - and the old folder is removed
    once it is empty. Does nothing when ``PEDALFX_HOME`` is set.
    """
    if "PEDALFX_HOME" in os.environ:
        return
    old, new = Path.home() / ".pedalboard-effects", Path.home() / ".pedalboard"
    if not old.is_dir():
        return
    try:
        new.mkdir(parents=True, exist_ok=True)
        for item in old.iterdir():
            if not (new / item.name).exists():
                item.rename(new / item.name)
        if not any(old.iterdir()):
            old.rmdir()
    except OSError:
        pass   # read-only home, a file in the way: keep going with whatever is there


def boards_dir() -> Path:
    """Where saved boards live: ``boards/`` in the repository, so they are
    versioned and pushed with the code. ``PEDALFX_HOME`` moves them too."""
    if "PEDALFX_HOME" in os.environ:
        return Path(os.environ["PEDALFX_HOME"]) / "boards"
    return REPO_BOARDS


def _p(type_name: str, enabled: bool = True, **params) -> dict:
    return {"type": type_name, "enabled": enabled, "params": params}


FACTORY_BOARDS = [
    {"name": "Welcome Board", "skin": "walnut", "pedals": [
        _p("tuner"),
        _p("compressor", sustain=0.4),
        _p("distortion", False, drive=0.45, tone=0.55, level=0.5),
        _p("chorus", rate=0.7, depth=0.45, mix=0.4),
        _p("delay", time=380, feedback=0.35, mix=0.25),
        _p("reverb", size=0.55, mix=0.28),
    ]},
    {"name": "Edge of Breakup", "skin": "tolex", "pedals": [
        _p("tuner"),
        _p("compressor", sustain=0.3),
        _p("boost", gain=5, treble=2),
        _p("distortion", drive=0.28, tone=0.6, level=0.55, mode=0),
        _p("reverb", size=0.4, mix=0.18),
    ]},
    {"name": "Shoegaze Wash", "skin": "stage", "pedals": [
        _p("tuner"),
        _p("distortion", drive=0.75, tone=0.45, level=0.4, mode=2),
        _p("phaser", rate=0.25, depth=0.8, feedback=0.5, mix=0.5),
        _p("chorus", rate=0.5, depth=0.7, mix=0.5),
        _p("delay", time=520, feedback=0.6, mix=0.4, tone=0.4, mode=1),
        _p("reverb", size=0.92, tone=0.6, mix=0.6, predelay=30),
    ]},
    {"name": "Slapback Twang", "skin": "walnut", "pedals": [
        _p("tuner"),
        _p("compressor", sustain=0.55, attack=20),
        _p("tremolo", False, rate=6, depth=0.5),
        _p("delay", time=115, feedback=0.12, mix=0.4, tone=0.5, mode=1),
        _p("reverb", size=0.3, mix=0.15),
    ]},
    {"name": "Lo-Fi Cassette", "skin": "aluminum", "pedals": [
        _p("tuner"),
        _p("compressor", sustain=0.35),
        {"type": "console", "enabled": True, "console_preset": "Worn Tape",
         "params": {"char_fx": 2, "char_amt": 0.35, "move_fx": 2, "move_amt": 0.3,
                    "diff_fx": 2, "diff_amt": 0.35, "text_fx": 3, "text_amt": 0.6,
                    "rate": 0.8, "time": 0.36, "tilt": -0.15}},
    ]},
    {"name": "Reverse Dream", "skin": "stage", "pedals": [
        _p("tuner"),
        {"type": "console", "enabled": True, "console_preset": "Backwards Bloom",
         "params": {"char_fx": 5, "char_amt": 0.5, "move_fx": 3, "move_amt": 0.35,
                    "diff_fx": 5, "diff_amt": 0.75, "text_fx": 1, "text_amt": 0.3,
                    "time": 0.7, "rate": 0.35}},
        _p("reverb", size=0.8, mix=0.4),
    ]},
    {"name": "Ping-Pong Clean", "skin": "aluminum", "pedals": [
        _p("tuner"),
        _p("chorus", rate=0.9, depth=0.35, mix=0.35),
        _p("delay", time=330, feedback=0.5, mix=0.4, mode=2),
        _p("reverb", size=0.5, mix=0.2),
    ]},
    {"name": "Looper Rig", "skin": "walnut", "pedals": [
        _p("tuner"),
        _p("compressor", sustain=0.4),
        _p("delay", time=380, feedback=0.3, mix=0.22),
        _p("reverb", size=0.5, mix=0.22),
        _p("looper"),
    ]},
]


def with_tuner_first(board: dict) -> dict:
    """Copy of ``board`` with a tuner at the front of the chain, unless it has one."""
    pedals = list(board.get("pedals", []))
    if any(entry.get("type") == "tuner" for entry in pedals):
        return board
    return {**board, "pedals": [_p("tuner"), *pedals]}


def board_to_dict(name: str, pedals, skin: str) -> dict:
    return {"version": FORMAT_VERSION, "name": name, "skin": skin,
            "pedals": [p.to_dict() for p in pedals]}


def pedals_from_board(data: dict, sr: float = 48000.0) -> list:
    pedals = []
    for entry in data.get("pedals", []):
        try:
            pedals.append(pedal_from_dict(entry, sr))
        except (KeyError, TypeError):
            continue  # a pedal type this version doesn't know about
    return pedals


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "board"


class PresetStore:
    """Factory boards plus the user's boards (``boards/*.json`` in the repo)."""

    def __init__(self, root: Path | None = None):
        if not root:
            migrate_home()
        self.root = Path(root) if root else app_dir()
        self.boards_dir = self.root / "boards" if root else boards_dir()
        self.session_path = self.root / "session.json"
        if not root:
            self._adopt_home_boards()

    def _adopt_home_boards(self) -> None:
        """Copy boards saved by earlier versions in ``~/.pedalboard/boards``."""
        legacy = self.root / "boards"
        if legacy == self.boards_dir or not legacy.is_dir():
            return
        for path in legacy.glob("*.json"):
            target = self.boards_dir / path.name
            if not target.exists():
                self.boards_dir.mkdir(parents=True, exist_ok=True)
                target.write_text(path.read_text())

    # boards ----------------------------------------------------------
    def _user_boards(self) -> dict:
        boards = {}
        if self.boards_dir.is_dir():
            for path in sorted(self.boards_dir.glob("*.json")):
                try:
                    data = json.loads(path.read_text())
                    boards[data["name"]] = data
                except (OSError, ValueError, KeyError, TypeError):
                    continue
        return boards

    def factory_names(self) -> list[str]:
        return [b["name"] for b in FACTORY_BOARDS]

    def user_names(self) -> list[str]:
        return sorted(self._user_boards())

    def is_user(self, name: str) -> bool:
        return name in self._user_boards()

    def load(self, name: str) -> dict:
        user = self._user_boards()
        if name in user:
            return user[name]
        for board in FACTORY_BOARDS:
            if board["name"] == name:
                return board
        raise KeyError(name)

    def save(self, board: dict) -> Path:
        self.boards_dir.mkdir(parents=True, exist_ok=True)
        path = self.boards_dir / f"{_slug(board['name'])}.json"
        path.write_text(json.dumps(board, indent=2))
        return path

    def delete(self, name: str) -> bool:
        path = self.boards_dir / f"{_slug(name)}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    # session ---------------------------------------------------------
    def load_session(self) -> dict:
        try:
            return json.loads(self.session_path.read_text())
        except (OSError, ValueError):
            return {}

    def save_session(self, session: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.session_path.write_text(json.dumps(session, indent=2))
