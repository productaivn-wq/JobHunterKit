# Folder-depth policy

## Standard

Use three total layers, including the project:

`project / zone / document.ext`

When the project root is counted as layer 0, the maximum relative file depth is 2. Managed documents must be direct children of a lifecycle zone. A deep scan must still inspect all layers.

Examples:

- Allowed: `30_REFERENCE/document.pdf`.
- Not allowed: `30_REFERENCE/Career/document.pdf`.

## Opaque technical exceptions

The following exact trees may exceed the managed-document limit because their internal layout is application-controlled or preserved verbatim:

- `00_INBOX/Quarantine/`
- `10_ACTIVE_TIMEBOUND/human_agency_director_ai_transformation/`
- `10_ACTIVE_TIMEBOUND/Project/app/config/`
- `10_ACTIVE_TIMEBOUND/Project/app/scripts/tests/data/`
- `10_ACTIVE_TIMEBOUND/Project/app/scripts/tests/e2e/`
- `10_ACTIVE_TIMEBOUND/Project/app/tailored_cv_renderer/`
- `20_ACTIVE_CONTINUOUS/Operations/runtime/`
- `40_ARCHIVE/Legacy/JobHunterKit_git_history/`
- `40_ARCHIVE/Legacy/snapshots/`
- `40_ARCHIVE/tailored_cv_renderer_abandoned_prototype/`

Each listed path is an exact subtree boundary and is treated as one opaque technical object. These exceptions do not permit ordinary curated documents to be stored deeply elsewhere in `Project/` or `Operations/`, nor do they exempt similarly named sibling folders. Curated software documentation and `skill_catalog.json` belong directly in `30_REFERENCE/`. New exceptions require an explicit update to this policy, `PROJECT_ORGANIZATION.md`, and the validator.
