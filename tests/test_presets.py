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


def test_boards_default_to_the_repository_and_adopt_old_ones(tmp_path, monkeypatch):
    import pedalfx.presets as presets

    assert presets.REPO_BOARDS.name == "boards" and (presets.REPO_BOARDS.parent / "src").is_dir()
    repo_boards, home = tmp_path / "repo" / "boards", tmp_path / "home"
    (home / "boards").mkdir(parents=True)
    (home / "boards" / "old.json").write_text('{"name": "Old", "pedals": []}')
    monkeypatch.delenv("PEDALFX_HOME", raising=False)
    monkeypatch.setattr(presets, "REPO_BOARDS", repo_boards)
    monkeypatch.setattr(presets.Path, "home", classmethod(lambda cls: tmp_path / "nowhere"))
    monkeypatch.setattr(presets, "app_dir", lambda: home)
    store = presets.PresetStore()
    assert store.boards_dir == repo_boards and store.session_path == home / "session.json"
    assert store.user_names() == ["Old"]             # copied over from the old location
    store.save({"name": "New One", "pedals": []})
    assert (repo_boards / "new-one.json").exists()

    monkeypatch.setenv("PEDALFX_HOME", str(tmp_path / "custom"))
    assert presets.boards_dir() == tmp_path / "custom" / "boards"
