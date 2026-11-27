import json

import pytest

from conftest import SR
from pedalfx.dsp import REGISTRY, create_pedal
from pedalfx.presets import (
    FACTORY_BOARDS,
    PresetStore,
    board_to_dict,
    pedals_from_board,
)


@pytest.mark.parametrize("board", FACTORY_BOARDS, ids=lambda b: b["name"])
def test_factory_boards_are_valid(board):
    pedals = pedals_from_board(board, SR)
    assert len(pedals) == len(board["pedals"])
    for entry, pedal in zip(board["pedals"], pedals):
        assert entry["type"] in REGISTRY
        for key, value in entry["params"].items():
            assert pedal.get(key) == pytest.approx(value), f"{key} was clamped"


def test_user_board_save_load_delete(tmp_path):
    store = PresetStore(tmp_path)
    console = create_pedal("console", SR)
    console.apply_preset("Shortwave")
    console.swap_modules(0, 2)
    delay = create_pedal("delay", SR)
    delay.set("time", 512.0)
    delay.enabled = False
    path = store.save(board_to_dict("My Tone!", [console, delay], "tolex"))
    assert path.name == "my-tone.json"
    assert store.user_names() == ["My Tone!"] and store.is_user("My Tone!")

    data = store.load("My Tone!")
    restored = pedals_from_board(data, SR)
    assert data["skin"] == "tolex"
    assert [p.TYPE for p in restored] == ["console", "delay"]
    assert restored[0].order == [2, 1, 0, 3] and restored[0].values == console.values
    assert restored[1].get("time") == 512.0 and restored[1].enabled is False

    assert store.delete("My Tone!") and store.user_names() == []
    assert not store.delete("My Tone!")


def test_factory_presets_load_and_unknowns_raise(tmp_path):
    store = PresetStore(tmp_path)
    assert store.load("Welcome Board")["pedals"]
    assert not store.is_user("Welcome Board")
    with pytest.raises(KeyError):
        store.load("does not exist")


def test_unknown_pedal_types_and_corrupt_files_are_skipped(tmp_path):
    store = PresetStore(tmp_path)
    store.boards_dir.mkdir(parents=True)
    (store.boards_dir / "broken.json").write_text("{not json")
    (store.boards_dir / "ok.json").write_text(json.dumps(
        {"name": "Future", "pedals": [{"type": "flux-capacitor"}, {"type": "reverb"}]}))
    assert store.user_names() == ["Future"]
    assert [p.TYPE for p in pedals_from_board(store.load("Future"), SR)] == ["reverb"]


def test_session_round_trip(tmp_path):
    store = PresetStore(tmp_path / "fresh")
    assert store.load_session() == {}
    store.save_session({"preset": "X", "master_db": -3.0})
    assert store.load_session() == {"preset": "X", "master_db": -3.0}


def test_boards_live_in_the_presets_repo_get_history_and_old_ones_move_in(tmp_path, monkeypatch):
    import subprocess

    import pedalfx.presets as presets

    old_repo_boards, home, shared = tmp_path / "repo" / "boards", tmp_path / "home", tmp_path / "gear-presets"
    for folder, name in ((home / "boards", "Old"), (old_repo_boards, "Older")):
        folder.mkdir(parents=True)
        (folder / f"{name.lower()}.json").write_text(json.dumps({"name": name, "pedals": []}))
    monkeypatch.delenv("PEDALFX_HOME", raising=False)
    monkeypatch.setenv("GEAR_PRESETS", str(shared))
    monkeypatch.setattr(presets, "REPO_BOARDS", old_repo_boards)
    monkeypatch.setattr(presets.Path, "home", classmethod(lambda cls: tmp_path / "nowhere"))
    monkeypatch.setattr(presets, "app_dir", lambda: home)

    # no presets checkout on this machine: boards stay in the per-machine folder
    assert presets.boards_dir() == home / "boards"
    assert presets.PresetStore().user_names() == ["Old", "Older"] and not list(old_repo_boards.glob("*.json"))

    def git(*args):
        return subprocess.run(["git", "-C", str(shared), *args], capture_output=True, text=True)
    shared.mkdir()
    git("init", "-q")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    store = presets.PresetStore()
    assert store.boards_dir == shared / "pedalboard" and store.session_path == home / "session.json"
    assert store.user_names() == ["Old", "Older"] and not list((home / "boards").glob("*.json"))
    assert git("log", "-1", "--format=%s").stdout.strip() == "Bring in boards saved before the presets repo"

    store.save({"name": "New One", "pedals": []})
    assert (shared / "pedalboard" / "new-one.json").exists()
    assert git("log", "-1", "--format=%s").stdout.strip() == "Save board: New One"
    assert store.delete("New One")
    assert git("log", "-1", "--format=%s").stdout.strip() == "Delete board: New One"
    assert git("status", "--porcelain").stdout == ""

    monkeypatch.setenv("PEDALFX_HOME", str(tmp_path / "custom"))
    assert presets.boards_dir() == tmp_path / "custom" / "boards"


def test_state_moves_from_the_old_home_folder_without_overwriting(tmp_path, monkeypatch):
    from pathlib import Path

    from pedalfx import presets

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("PEDALFX_HOME", raising=False)
    old, new = tmp_path / ".pedalboard-effects", tmp_path / ".pedalboard"
    old.mkdir()
    (old / "session.json").write_text('{"preset": "Mine"}')
    (new / "presets").mkdir(parents=True)                 # a v1 folder already there
    (new / "presets" / "v1.json").write_text("{}")
    presets.migrate_home()
    assert (new / "session.json").read_text() == '{"preset": "Mine"}'
    assert (new / "presets" / "v1.json").exists() and not old.exists()

    old.mkdir()                                           # a stale copy must not clobber newer state
    (old / "session.json").write_text('{"preset": "Stale"}')
    presets.migrate_home()
    assert (new / "session.json").read_text() == '{"preset": "Mine"}' and old.exists()
    assert presets.app_dir() == new
