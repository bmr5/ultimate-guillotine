# Scripts

Repository maintenance and future Mac mini automation entry points live here. Scripts should be deterministic, safe to rerun, and explicit about any external side effects.

## Import league records

Install the Python dependency:

```bash
python3 -m pip install -r scripts/requirements.txt
```

Extract the private 2022 member registration data and create the tracked history workbook:

```bash
python3 scripts/import_league_records.py \
  "/path/to/Ultimate Guillotine Records.xlsx" \
  --sanitized-output history/league/ultimate-guillotine-records.xlsx \
  --private-output data/private/league-members.json
```

Confirm that a sanitized workbook contains no email or phone-like values:

```bash
python3 scripts/import_league_records.py \
  history/league/ultimate-guillotine-records.xlsx \
  --check
```

The real member directory is local-only and must remain ignored by Git.
