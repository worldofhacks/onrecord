# T-001 Test Agent Report — Scaffold

**Status:** DONE (frozen failing tests written, confirmed RED against empty scaffold, confirmed GREEN against a correct implementation)

**Test file:** `tests/unit/test_scaffold.py` (plus `tests/__init__.py`, `tests/unit/__init__.py`)

**Run command:**
```
uv run --with pytest --with pyyaml -- pytest tests/unit/test_scaffold.py -v
```

## Schema decisions not otherwise pinned by the ticket

The ticket specifies field-level requirements for the registry (counts + required
keys) but not the top-level YAML shape or the `onrecord.registry.load()` return
type. To make these tests concrete and reproducible, the following were fixed,
documented in the test file's module docstring, and should be treated as part of
the frozen contract for T-001's implementer:

- `corpus/registry.yaml` is a mapping with three top-level lists:
  - `youtube_channels`: list of mappings, each with `id`, `name`, `jurisdiction`, `state` (>= 45 items)
  - `tickers`: list of mappings, each with `symbol`, `sector` (>= 90 items)
  - `docket_sources`: list (>= 10 items; no field-shape requirement per ticket text)
- `onrecord.registry.load()` takes no arguments and returns something exposing
  those same three collections — either dict keys or object attributes are
  accepted by the tests (`_attr_or_key` helper), so the implementer may return
  a plain `dict` or a small wrapper/dataclass.

## Criterion → test mapping

| Criterion | Test(s) | What it checks |
|---|---|---|
| AC-1 (clean clone + `make setup` → `import onrecord` succeeds) | `test_onrecord_package_importable` | `importlib.util.find_spec("onrecord")` is not `None` |
| AC-1 | `test_make_setup_installs_deps_and_onrecord_imports` | Guarded on `pyproject.toml` existing (else fails with "pyproject.toml missing"); then runs `make setup` via subprocess and `uv run python -c "import onrecord"`, asserting both exit 0 |
| AC-1 (frozen interface surface — `import onrecord` is only meaningful if its types are correct) | `test_doc_dataclass_is_frozen_with_exact_fields` | `onrecord.types.Doc` is a frozen dataclass with exact field order `id, text, source_type, venue_type, date, deep_link, ticker, jurisdiction, speaker`; first six required, last three default `None`; mutating a frozen instance raises `FrozenInstanceError` |
| AC-1 | `test_searchresult_dataclass_is_frozen_with_exact_fields` | Same, for `onrecord.types.SearchResult` (`doc_id, score, snippet`, all required) |
| AC-2 (`uv run pytest -q` executes the suite) | `test_makefile_test_target_delegates_to_pytest` | Reads `Makefile` text; the `test:` target's recipe contains `pytest` |
| AC-3 (registry) | `test_registry_file_exists` | `corpus/registry.yaml` exists |
| AC-3 | `test_registry_youtube_channels_meet_scale_and_schema` | `>= 45` entries under `youtube_channels`, each a mapping with `id/name/jurisdiction/state` |
| AC-3 | `test_registry_tickers_meet_scale_and_schema` | `>= 90` entries under `tickers`, each a mapping with `symbol/sector` |
| AC-3 | `test_registry_docket_sources_meet_scale` | `>= 10` entries under `docket_sources` |
| AC-3 | `test_registry_loadable_via_onrecord_registry_load` | `onrecord.registry.load()` exists and its result exposes the same three collections meeting the same count thresholds |
| AC-4 (Makefile targets exist) | `test_makefile_defines_all_required_targets` | `Makefile` defines `setup`, `test`, `eval`, `ingest`, `demo` target blocks |
| AC-4 (eval/ingest/demo delegate to onrecord entrypoints) | `test_makefile_stub_targets_delegate_to_onrecord_module[eval\|ingest\|demo]` (parametrized, 3 cases) | Each target's recipe text contains `uv run python -m onrecord` |

14 test items total (11 functions + 1 parametrized ×3).

## Failure-cleanliness fix during authoring

Initial draft used `importlib.util.find_spec("onrecord.types")` / `("onrecord.registry")`
directly as the import guard. Running the suite showed this raises an uncaught
`ModuleNotFoundError` (not a clean assertion) when the *parent* package
(`onrecord`) doesn't exist at all — `find_spec` only returns `None` cleanly for a
genuinely missing leaf module of an *importable* parent. Fixed by adding a
`_require_module_spec()` helper that catches `ModuleNotFoundError` and converts
it into a clean `pytest.fail(...)`, per the "no collection/uncaught-exception
failures" requirement. Verified by re-running — see failure output below.

## Verification performed

1. Ran the suite against the current (empty) worktree — all 14 fail, each with a
   clean `AssertionError` or `Failed: <message>` (no tracebacks from uncaught
   exceptions, no pytest collection errors). Full output below.
2. Built a throwaway correct implementation in the scratchpad (never touched the
   worktree's forbidden paths — `onrecord/`, `pyproject.toml`, `Makefile`,
   `corpus/` were only created outside `/Users/quietguy/Documents/Dev/Gauntlet/wt-T-001`)
   satisfying the schema above, and confirmed all 14 tests **pass** against it.
   This confirms the tests are achievable and not vacuously red.

## Failure output (current worktree, RED)

```
============================= test session starts ==============================
platform darwin -- Python 3.13.13, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/quietguy/Documents/Dev/Gauntlet/wt-T-001
collecting ... collected 14 items

tests/unit/test_scaffold.py::test_onrecord_package_importable FAILED     [  7%]
tests/unit/test_scaffold.py::test_make_setup_installs_deps_and_onrecord_imports FAILED [ 14%]
tests/unit/test_scaffold.py::test_doc_dataclass_is_frozen_with_exact_fields FAILED [ 21%]
tests/unit/test_scaffold.py::test_searchresult_dataclass_is_frozen_with_exact_fields FAILED [ 28%]
tests/unit/test_scaffold.py::test_makefile_test_target_delegates_to_pytest FAILED [ 35%]
tests/unit/test_scaffold.py::test_makefile_defines_all_required_targets FAILED [ 42%]
tests/unit/test_scaffold.py::test_makefile_stub_targets_delegate_to_onrecord_module[eval] FAILED [ 50%]
tests/unit/test_scaffold.py::test_makefile_stub_targets_delegate_to_onrecord_module[ingest] FAILED [ 57%]
tests/unit/test_scaffold.py::test_makefile_stub_targets_delegate_to_onrecord_module[demo] FAILED [ 64%]
tests/unit/test_scaffold.py::test_registry_file_exists FAILED            [ 71%]
tests/unit/test_scaffold.py::test_registry_youtube_channels_meet_scale_and_schema FAILED [ 78%]
tests/unit/test_scaffold.py::test_registry_tickers_meet_scale_and_schema FAILED [ 85%]
tests/unit/test_scaffold.py::test_registry_docket_sources_meet_scale FAILED [ 92%]
tests/unit/test_scaffold.py::test_registry_loadable_via_onrecord_registry_load FAILED [100%]

=================================== FAILURES ===================================
test_onrecord_package_importable
  AssertionError: onrecord package missing (importlib.util.find_spec returned None)

test_make_setup_installs_deps_and_onrecord_imports
  AssertionError: pyproject.toml missing

test_doc_dataclass_is_frozen_with_exact_fields
  Failed: onrecord package missing

test_searchresult_dataclass_is_frozen_with_exact_fields
  Failed: onrecord package missing

test_makefile_test_target_delegates_to_pytest
  Failed: Makefile missing

test_makefile_defines_all_required_targets
  Failed: Makefile missing

test_makefile_stub_targets_delegate_to_onrecord_module[eval]
  Failed: Makefile missing

test_makefile_stub_targets_delegate_to_onrecord_module[ingest]
  Failed: Makefile missing

test_makefile_stub_targets_delegate_to_onrecord_module[demo]
  Failed: Makefile missing

test_registry_file_exists
  AssertionError: corpus/registry.yaml missing

test_registry_youtube_channels_meet_scale_and_schema
  Failed: corpus/registry.yaml missing

test_registry_tickers_meet_scale_and_schema
  Failed: corpus/registry.yaml missing

test_registry_docket_sources_meet_scale
  Failed: corpus/registry.yaml missing

test_registry_loadable_via_onrecord_registry_load
  Failed: onrecord.registry module missing

=========================== short test summary info ============================
FAILED tests/unit/test_scaffold.py::test_onrecord_package_importable - Assert...
FAILED tests/unit/test_scaffold.py::test_make_setup_installs_deps_and_onrecord_imports
FAILED tests/unit/test_scaffold.py::test_doc_dataclass_is_frozen_with_exact_fields
FAILED tests/unit/test_scaffold.py::test_searchresult_dataclass_is_frozen_with_exact_fields
FAILED tests/unit/test_scaffold.py::test_makefile_test_target_delegates_to_pytest
FAILED tests/unit/test_scaffold.py::test_makefile_defines_all_required_targets
FAILED tests/unit/test_scaffold.py::test_makefile_stub_targets_delegate_to_onrecord_module[eval]
FAILED tests/unit/test_scaffold.py::test_makefile_stub_targets_delegate_to_onrecord_module[ingest]
FAILED tests/unit/test_scaffold.py::test_makefile_stub_targets_delegate_to_onrecord_module[demo]
FAILED tests/unit/test_scaffold.py::test_registry_file_exists - AssertionErro...
FAILED tests/unit/test_scaffold.py::test_registry_youtube_channels_meet_scale_and_schema
FAILED tests/unit/test_scaffold.py::test_registry_tickers_meet_scale_and_schema
FAILED tests/unit/test_scaffold.py::test_registry_docket_sources_meet_scale
FAILED tests/unit/test_scaffold.py::test_registry_loadable_via_onrecord_registry_load
============================== 14 failed in 0.08s ==============================
```

## Notes for the Implementation Agent

- All 4 ACs are covered; frozen-dataclass checks are grouped under AC-1 since a
  successful `import onrecord` is only meaningful if `onrecord.types.Doc` /
  `SearchResult` match the ticket's exact frozen contract.
- `test_make_setup_installs_deps_and_onrecord_imports` will actually shell out to
  `make setup` (real `uv sync`) and then `uv run python -c "import onrecord"` once
  `pyproject.toml` exists — expect it to take real wall-clock time (timeout set to
  600s / 120s respectively) and to require network access for dependency
  resolution the first time.
- Do not edit `tests/unit/test_scaffold.py` to make it pass — these tests are
  frozen. If a genuine ambiguity or defect is found in them, escalate to the
  orchestrator/Reviewer rather than editing directly.
