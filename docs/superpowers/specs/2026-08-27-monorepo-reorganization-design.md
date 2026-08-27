# Ultimate Guillotine Monorepo Reorganization

## Objective

Reorganize Ultimate Guillotine into a single workspace that can grow beyond the existing website to support league documents, historical records, private member data, automation agents, and operational scripts.

The first implementation will preserve the working website, import the authoritative 2025-26 league files, and establish a strict boundary between publishable league history and personal contact information.

## Repository Structure

```text
ultimate-guillotine/
├── apps/
│   └── web/                  # Existing React/Vite website
├── agents/                   # Agent definitions and future automation prompts
├── data/
│   └── private/              # Ignored local member/contact data
├── docs/
│   ├── contracts/            # Contract documents and reference material
│   ├── rules/                # Authoritative league rules
│   └── superpowers/specs/    # Approved repository and feature designs
├── history/
│   ├── contracts/2025-26/    # Historical contract workbook
│   └── league/               # Sanitized historical league records
├── scripts/                  # Import, extraction, and future scheduled jobs
├── package.json              # Workspace-level commands and metadata
└── pnpm-workspace.yaml       # pnpm workspace definition
```

Packages will only be introduced when code is genuinely shared by multiple applications or agents. The initial reorganization will not create an empty `packages/` hierarchy.

## Website Migration

The current React/Vite application will move from the repository root to `apps/web/` as one unit. Its source, public assets, environment definition, TypeScript configuration, Vite configuration, and web-specific tooling will move together.

The root will become the orchestration layer. Root commands will delegate development, build, lint, and preview operations to the web workspace so the normal developer workflow remains simple. The existing pnpm package-manager and lockfile changes in the working tree will be preserved rather than overwritten.

Deployment configuration will be updated only as needed for the new web application path. A successful production build from the repository root is the primary compatibility check.

## League Documents and History

The downloaded files will be classified as follows:

- `ULTIMATE GUILLOTINE GULAG LEAGUE RULES.docx` becomes the authoritative source document under `docs/rules/`.
- `GUILLOTINE GULAG INSURANCE OPTION CONTRACT.docx` moves under `docs/contracts/`.
- `All 2025_2026 Contracts In Order.xlsx` moves under `history/contracts/2025-26/`.
- A sanitized copy of `Ultimate Guillotine Records.xlsx` moves under `history/league/`.

The original records workbook in Downloads remains untouched as a backup during extraction and sanitization. The two explicitly unwanted spreadsheets, `Rankings.xlsx` and `Untitled spreadsheet.xlsx`, will be moved to macOS Trash and remain recoverable until Trash is emptied.

## Privacy Boundary

The historical records workbook may contain league-member contact information. Personal fields will be extracted into:

```text
data/private/league-members.json
```

That file and other contents of `data/private/` will be ignored by Git. A tracked schema/example file will document the supported shape without containing real personal information. The initial schema will retain only fields found in the source that are useful for league operations, such as display name, team name, email address, phone number, and relevant platform identifiers.

The tracked historical workbook will be a sanitized copy with contact-bearing content removed. Non-private league history, records, standings, awards, and other historical facts will remain intact and commit-safe. Before staging imported files, the repository will be scanned for email addresses and phone-number-like values to catch accidental personal-data leakage.

Scripts and applications must read private data through the ignored path or future secret storage. Private contact data must never be copied into browser assets, generated public files, logs, prompts committed to Git, or the website bundle.

## Agents and Scripts

`agents/` will initially contain documentation describing the intended home for future recap, messaging, research, and league-operations agents. No agent framework or vendor integration will be selected during this reorganization.

`scripts/` will contain deterministic maintenance utilities, beginning with extraction and privacy-validation logic if needed. Future scheduled jobs on the always-on Mac mini can invoke these scripts without coupling automation code to the web application.

## Data Flow

```text
downloaded source files
        |
        +--> tracked rules/contracts/history
        |
        +--> extraction/sanitization script
                 |
                 +--> ignored private member directory
                 +--> tracked sanitized history workbook

tracked history + external league APIs
        |
        +--> future scripts and agents
                 |
                 +--> website data
                 +--> weekly recaps
                 +--> approved league messages
```

The reorganization establishes these boundaries without implementing messaging, scheduling, or AI-provider integrations yet.

## Failure Handling and Safety

- Source files will be copied into the repository rather than destructively moved from Downloads.
- The original records workbook will not be modified in place.
- Unrelated working-tree changes will be preserved.
- Only the two explicitly unwanted spreadsheets will be trashed.
- Imported files will be validated before any source backup is considered disposable.
- Private-data extraction will fail closed: if sanitization cannot confidently separate contact information from historical content, the records workbook will remain unstaged until reviewed.

## Verification

Implementation is complete when:

1. The root workspace installs and builds the relocated web application successfully.
2. Existing lint or type checks run successfully, or pre-existing failures are documented precisely.
3. The rules, contract documents, contract history, and sanitized league history exist in their intended tracked locations.
4. The private player/contact directory is extracted locally and `git check-ignore` confirms it is ignored.
5. `git status` does not show the private member file.
6. A repository scan finds no extracted email addresses or phone numbers in tracked/imported content outside approved binary source documents; the sanitized records workbook receives a direct content check.
7. The unwanted spreadsheets are in macOS Trash and their original Download paths no longer exist.
8. The repository README explains the workspace layout and common commands.

## Out of Scope

- Redesigning the website.
- Selecting or implementing an agent framework.
- Sending league messages.
- Installing a scheduler on the Mac mini.
- Migrating the private directory into a hosted database or secrets manager.
- Normalizing all historical league data into a new database schema.
