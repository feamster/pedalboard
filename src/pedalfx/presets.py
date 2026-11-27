"""Board presets (pedal order + every knob) and session persistence."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from .dsp import pedal_from_dict

FORMAT_VERSION = 2


REPO_ROOT = Path(__file__).resolve().parents[2]
REPO_BOARDS = REPO_ROOT / "boards"       # where saved boards used to live


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


def presets_repo() -> Path:
    """The checkout that holds saved boards (and the synth rack's racks), kept
    apart from the code: ``$GEAR_PRESETS``, else ``gear-presets`` beside this repo."""
    return Path(os.environ.get("GEAR_PRESETS") or REPO_ROOT.parent / "gear-presets").expanduser()


def boards_dir() -> Path:
    """Where saved boards live: ``pedalboard/`` in the presets checkout if this
    machine has one, else ``~/.pedalboard/boards``. ``PEDALFX_HOME`` overrides
    both. The synth rack's Pedal Loop reads boards from here too."""
    if "PEDALFX_HOME" in os.environ:
        return Path(os.environ["PEDALFX_HOME"]) / "boards"
    repo = presets_repo()
    return repo / "pedalboard" if repo.is_dir() else app_dir() / "boards"


def git_commit(paths, message: str) -> bool:
    """Record a change to saved files when their folder is a git checkout, so
    boards get history without anyone touching git. Local only; never pushes.
    Quietly does nothing anywhere else, or if git is missing or unhappy."""
    paths = [Path(p) for p in paths]
    if not paths:
        return False
    folder = paths[0].parent
    try:
        def git(*args):
            return subprocess.run(["git", "-C", str(folder), *args], capture_output=True, timeout=10)
        if git("rev-parse", "--is-inside-work-tree").returncode != 0:
            return False
        names = [str(p) for p in paths]
        git("add", "-A", "--", *names)
        return git("commit", "-q", "-m", message, "--", *names).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


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
    """Factory boards plus the user's boards (see ``boards_dir``), and the session."""

    def __init__(self, root: Path | None = None):
        if not root:
            migrate_home()
        self.root = Path(root) if root else app_dir()
        self.boards_dir = self.root / "boards" if root else boards_dir()
        self.session_path = self.root / "session.json"
        if not root and "PEDALFX_HOME" not in os.environ:
            self.adopt_boards(REPO_BOARDS, self.root / "boards")

    def adopt_boards(self, *legacy: Path) -> list:
        """Move boards saved where earlier versions kept them (``boards/`` in
        this repository, ``~/.pedalboard/boards``) into ``boards_dir``. A board
        that is already there is left alone. Returns the files that arrived."""
        moved = []
        for folder in legacy:
            if folder == self.boards_dir or not folder.is_dir():
                continue
            for path in sorted(folder.glob("*.json")):
                target = self.boards_dir / path.name
                if target.exists():
                    continue
                try:
                    self.boards_dir.mkdir(parents=True, exist_ok=True)
                    target.write_text(path.read_text())
                    path.unlink()
                    moved.append(target)
                except OSError:
                    continue
        if moved:
            git_commit(moved, "Bring in boards saved before the presets repo")
        return moved

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
        path.write_text(json.dumps(board, indent=2) + "\n")
        git_commit([path], f"Save board: {board['name']}")
        return path

    def delete(self, name: str) -> bool:
        path = self.boards_dir / f"{_slug(name)}.json"
        if path.exists():
            path.unlink()
            git_commit([path], f"Delete board: {name}")
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
