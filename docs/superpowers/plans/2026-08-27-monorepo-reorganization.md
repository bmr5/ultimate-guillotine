# Ultimate Guillotine Monorepo Reorganization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize the repository around the existing website, tracked league documents/history, ignored private member data, future agents, and repeatable maintenance scripts.

**Architecture:** The current Vite application becomes the `@ultimate-guillotine/web` pnpm workspace under `apps/web`; the repository root orchestrates workspace commands. A deterministic Python importer separates the 2022 registration sheet from the historical workbook, writes its member/contact records to an ignored JSON file, and saves the remaining history sheets as the tracked workbook.

**Tech Stack:** pnpm 9, React 18, Vite 4, TypeScript 5, Python 3, openpyxl 3.1.5, pytest/unittest, Git

**Spec:** `docs/superpowers/specs/2026-08-27-monorepo-reorganization-design.md`

## Global Constraints

- Preserve the user's existing pnpm 9 `package.json` and lockfile changes.
- Do not modify the original `Ultimate Guillotine Records.xlsx` in Downloads.
- Copy authoritative source files into the repository; do not destructively move them.
- Move only `Rankings.xlsx` and `Untitled spreadsheet.xlsx` to macOS Trash.
- Never stage or commit `data/private/league-members.json`.
- Keep all historical sheets except the contact-bearing 2022 registration sheet in the tracked workbook.
- Do not implement messaging, scheduling, or an agent framework in this change.
- Avoid implementation commits that would absorb the user's pre-existing package-manager changes.

---

### Task 1: Add the privacy-preserving records importer

**Files:**
- Create: `scripts/import_league_records.py`
- Create: `scripts/requirements.txt`
- Create: `scripts/tests/test_import_league_records.py`
- Create: `scripts/README.md`

**Interfaces:**
- Consumes: an `.xlsx` workbook containing a `2022` registration sheet.
- Produces: `import_records(source: Path, sanitized_output: Path, private_output: Path) -> ImportSummary`.
- Produces: ignored JSON shaped as `{source, sourceSheet, members}`.
- Produces: a sanitized `.xlsx` with every non-private sheet preserved and the `2022` sheet removed.

- [ ] **Step 1: Write a failing importer test**

```python
def test_import_extracts_members_and_removes_registration_sheet(tmp_path):
    source = make_source_workbook(tmp_path / "records.xlsx")
    sanitized = tmp_path / "sanitized.xlsx"
    private = tmp_path / "league-members.json"

    summary = import_records(source, sanitized, private)

    assert summary.member_count == 1
    assert summary.removed_sheet == "2022"
    assert load_workbook(sanitized).sheetnames == ["Winners", "2025"]
    member = json.loads(private.read_text())["members"][0]
    assert member["firstName"] == "Test"
    assert member["email"] == "test@example.com"
```

- [ ] **Step 2: Run the focused test and confirm it fails because the importer does not exist**

Run: `python3 -m unittest scripts/tests/test_import_league_records.py -v`

Expected: import failure for `scripts.import_league_records`.

- [ ] **Step 3: Implement extraction, sanitization, and leak scanning**

```python
@dataclass(frozen=True)
class ImportSummary:
    member_count: int
    removed_sheet: str
    retained_sheets: tuple[str, ...]


def import_records(source: Path, sanitized_output: Path, private_output: Path) -> ImportSummary:
    workbook = load_workbook(source)
    registration = workbook["2022"]
    members = extract_members(registration)
    workbook.remove(registration)
    assert_no_contact_values(workbook)
    write_private_directory(private_output, source.name, members)
    sanitized_output.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(sanitized_output)
    return ImportSummary(len(members), "2022", tuple(workbook.sheetnames))
```

Map columns `B`, `C`, `D`, `E`, `F`, `G`, `H`, and `J` to `firstName`, `lastName`, `email`, `phone`, `loveLanguage`, `teamNameReservation`, `duesPaid`, and `draftAvailability`. Skip rows without either a first or last name. Normalize empty strings to `null` and preserve phone-like values as strings.

- [ ] **Step 4: Add negative tests for missing registration sheet and residual contacts**

```python
def test_import_rejects_workbook_without_registration_sheet(tmp_path):
    with self.assertRaisesRegex(ValueError, "2022 registration sheet"):
        import_records(source_without_2022, sanitized, private)


def test_contact_scan_rejects_email_in_retained_sheet():
    with self.assertRaisesRegex(ValueError, "contact-like value"):
        assert_no_contact_values(workbook_with_email_in_winners)
```

- [ ] **Step 5: Run the importer test suite**

Run: `python3 -m unittest discover -s scripts/tests -v`

Expected: all importer tests pass.

### Task 2: Import and classify the league source material

**Files:**
- Create: `docs/rules/ultimate-guillotine-gulag-league-rules.docx`
- Create: `docs/contracts/gulag-insurance-option-contract.docx`
- Create: `history/contracts/2025-26/all-contracts.xlsx`
- Create: `history/league/ultimate-guillotine-records.xlsx`
- Create: `data/private/league-members.json` (ignored)
- Create: `data/private/league-members.example.json`
- Create: `data/private/README.md`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: files under `/Users/benray/Downloads/Guillotine/`.
- Produces: stable repository paths used by future website, agent, and script work.
- Produces: a private member directory with the Task 1 JSON schema.

- [ ] **Step 1: Add the private-data ignore contract**

```gitignore
data/private/*
!data/private/README.md
!data/private/league-members.example.json
```

- [ ] **Step 2: Add a fake-data schema example**

```json
{
  "source": "example.xlsx",
  "sourceSheet": "2022",
  "members": [
    {
      "firstName": "Example",
      "lastName": "Member",
      "email": "member@example.com",
      "phone": "555-010-0000",
      "teamNameReservation": "Example Team"
    }
  ]
}
```

- [ ] **Step 3: Copy the rules, contract, and contract-history files to normalized tracked paths**

Run explicit `cp` operations from the downloaded files to the three target paths. Verify each copied DOCX/XLSX archive with `unzip -t`.

- [ ] **Step 4: Run the records importer**

Run:

```bash
python3 scripts/import_league_records.py \
  /Users/benray/Downloads/Guillotine/Ultimate\ Guillotine\ Records.xlsx \
  --sanitized-output history/league/ultimate-guillotine-records.xlsx \
  --private-output data/private/league-members.json
```

Expected: 18 member rows extracted; tracked workbook retains `Winners`, `2025`, `2023`, and `2024`.

- [ ] **Step 5: Prove the privacy boundary**

Run:

```bash
git check-ignore -v data/private/league-members.json
git status --short -- data/private/league-members.json
python3 scripts/import_league_records.py --check history/league/ultimate-guillotine-records.xlsx
```

Expected: the private file matches `.gitignore`, does not appear in status, and the sanitized workbook has zero email/phone-like cells.

- [ ] **Step 6: Move the two unwanted spreadsheets to recoverable Trash paths**

Resolve collision-free targets under `/Users/benray/.Trash/`, move only `Rankings.xlsx` and `Untitled spreadsheet.xlsx`, then verify their original paths no longer exist.

### Task 3: Relocate the website into a pnpm workspace

**Files:**
- Create: `apps/web/package.json` from the current web manifest
- Move: `src/` to `apps/web/src/`
- Move: `public/` to `apps/web/public/`
- Move: `index.html`, `env.ts`, `fetchPlayerData.js`, and web configuration files to `apps/web/`
- Create: `pnpm-workspace.yaml`
- Modify: `package.json`
- Modify: `pnpm-lock.yaml` through `pnpm install --lockfile-only`

**Interfaces:**
- Consumes: existing root commands `dev`, `build`, `lint`, and `preview`.
- Produces: equivalent root commands delegated to `@ultimate-guillotine/web`.
- Produces: independently addressable workspace package `@ultimate-guillotine/web`.

- [ ] **Step 1: Record the current web build baseline**

Run: `pnpm build`

Expected: successful TypeScript and Vite production build, or a precisely captured pre-existing failure.

- [ ] **Step 2: Move the web application and app-specific configuration together**

Move `.env.example`, `.eslintrc.cjs`, `.prettierignore`, `.prettierrc.cjs`, `env.ts`, `fetchPlayerData.js`, `index.html`, `postcss.config.js`, `public/`, `src/`, `tailwind.config.js`, `tsconfig.json`, `tsconfig.node.json`, `vercel.json`, `vite.config.ts`, and the timestamped Vite artifact into `apps/web/`.

- [ ] **Step 3: Convert the existing package manifest into the web manifest**

Set:

```json
{
  "name": "@ultimate-guillotine/web",
  "private": true,
  "version": "0.0.0"
}
```

Retain its existing scripts, dependencies, and dev dependencies.

- [ ] **Step 4: Add the root workspace manifest**

```json
{
  "name": "ultimate-guillotine",
  "private": true,
  "packageManager": "pnpm@9.15.0+sha512.76e2379760a4328ec4415815bcd6628dee727af3779aaa4c914e3944156c4299921a89f976381ee107d41f12cfa4b66681ca9c718f0668fa0831ed4c6d8ba56c",
  "scripts": {
    "dev": "pnpm --filter @ultimate-guillotine/web dev",
    "build": "pnpm --filter @ultimate-guillotine/web build",
    "lint": "pnpm --filter @ultimate-guillotine/web lint",
    "preview": "pnpm --filter @ultimate-guillotine/web preview"
  }
}
```

- [ ] **Step 5: Define and install the workspace**

```yaml
packages:
  - apps/*
```

Run: `pnpm install --lockfile-only`

Expected: pnpm lockfile v9 with `apps/web` as the importer.

- [ ] **Step 6: Run relocated application checks**

Run: `pnpm build && pnpm lint`

Expected: the build and lint results match or improve upon the baseline.

### Task 4: Document workspace responsibilities

**Files:**
- Create: `agents/README.md`
- Modify: `README.md`

**Interfaces:**
- Produces: onboarding guidance for humans and future agents.
- Produces: stable directory ownership rules that prevent private data from reaching public bundles.

- [ ] **Step 1: Document the future agent boundary**

State that each future agent receives its own folder containing purpose, inputs, outputs, permissions, and runbook; no agent may send external messages without an explicit delivery policy and dry-run mode.

- [ ] **Step 2: Replace the starter README with project-specific instructions**

Document repository layout, `pnpm` web commands, records import command, private-data behavior, and the location of authoritative rules/history.

- [ ] **Step 3: Verify documented commands**

Run every non-destructive command shown in the README and correct any mismatch.

### Task 5: Final repository verification

**Files:**
- Verify all files changed by Tasks 1-4.

**Interfaces:**
- Produces: evidence that the relocated site works and personal information is excluded from Git.

- [ ] **Step 1: Run automated checks**

Run:

```bash
python3 -m unittest discover -s scripts/tests -v
pnpm build
pnpm lint
```

- [ ] **Step 2: Validate imported Office archives**

Run `unzip -t` against both tracked DOCX files and both tracked XLSX files.

- [ ] **Step 3: Validate spreadsheet contents**

Confirm the sanitized workbook contains `Winners`, `2025`, `2023`, and `2024`, excludes `2022`, and contains zero contact-like values. Confirm the contract workbook remains structurally readable.

- [ ] **Step 4: Check Git privacy and scope**

Run:

```bash
git check-ignore -v data/private/league-members.json
git ls-files data/private/league-members.json
git diff --check
git status --short
```

Expected: the real private directory is ignored and untracked, no whitespace errors exist, and only intended implementation changes plus the user's preserved package-manager changes appear.

- [ ] **Step 5: Report recovery and known limitations**

Report the exact Trash targets for the two unwanted spreadsheets, confirm the Downloads originals retained for imported source files, and identify any pre-existing build or lint failures separately from reorganization regressions.
