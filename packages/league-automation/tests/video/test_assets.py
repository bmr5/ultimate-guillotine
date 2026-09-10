from pathlib import Path

import pytest

from ultimate_guillotine.video import assets as assets_mod
from ultimate_guillotine.video.assets import Assets, ToolMissing, find_tool, load_assets


def test_media_root_defaults_to_data_media_and_honours_the_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("UG_MEDIA_ROOT", raising=False)
    assert load_assets().root == Path("data/media")
    monkeypatch.setenv("UG_MEDIA_ROOT", "/tmp/elsewhere")
    assert load_assets().root == Path("/tmp/elsewhere")


def test_paths_hang_off_the_root() -> None:
    a = Assets(Path("/m"))
    assert a.reference_video == Path("/m/reference") / assets_mod.REFERENCE_VIDEO
    assert a.source_video == Path(
        "/m/reference/source/espn-tMgvUrwtaiw-schefter-parsons-breaking-news.mp4"
    )
    assert a.music == Path("/m/reference") / assets_mod.MUSIC
    assert a.generation_reference == Path("/m/reference/source/espn-schefter-clean-1024.mp4")
    assert (a.renders, a.generated, a.work) == (
        Path("/m/renders"),
        Path("/m/generated"),
        Path("/m/work"),
    )


def test_missing_lists_only_the_reference_files_that_are_not_on_disk(tmp_path: Path) -> None:
    a = Assets(tmp_path)
    a.music.parent.mkdir(parents=True)
    a.music.write_bytes(b"")
    assert a.missing() == [a.reference_video, a.source_video, a.generation_reference]


def test_find_tool_raises_a_plain_error_for_an_unknown_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(assets_mod.shutil, "which", lambda *_a, **_k: None)
    with pytest.raises(ToolMissing, match="no-such-tool"):
        find_tool("no-such-tool")


def test_find_tool_returns_the_path_which_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        assets_mod.shutil, "which", lambda name, path=None: f"/opt/homebrew/bin/{name}"
    )
    assert find_tool("ffmpeg") == "/opt/homebrew/bin/ffmpeg"
