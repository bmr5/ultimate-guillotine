from pathlib import Path


def main() -> None:
    if not Path("supabase/config.toml").is_file():
        raise SystemExit("supabase/config.toml missing: run `supabase init`")
    print("Supabase baseline present")


if __name__ == "__main__":
    main()
