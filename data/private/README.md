# Private league data

This directory is the local-only boundary for member names, contact details, payment status, and other registration information used by scripts and future agents.

`league-members.json` is generated from the source records workbook and ignored by Git. Never copy its contents into `apps/web/public`, tracked prompts, logs, fixtures, or generated website data.

Use `league-members.example.json` when developing against the schema. It contains fake data only.
