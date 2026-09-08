from pathlib import Path


def test_supabase_config_is_present() -> None:
    assert Path("supabase/config.toml").is_file()
    assert Path("supabase/migrations").is_dir()
