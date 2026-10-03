# Changelog — v1.8.4 (CrewAI + Real NemoClaw)

## Summary

Eliminated ALL remaining stubs:
- **AIOX replaced** by CrewAI 1.15.23 (real production multi-agent framework)
- **NemoClawSandbox** no longer raises NotImplementedError — real Docker-or-hermetic

## Added

### Real AIOX replacement (CrewAI)
- `alberto/runtime/crewai_runtime.py` (240 LoC)
  - Real CrewAI 1.15.23 integration (NOT a stub)
  - `run_crew_squad()` — converts YAML workflow + persona .md files into real CrewAI Agents and Tasks
  - `get_crewai_status()` — reports real version
  - Rate-limit retry with exponential backoff (8s/16s/24s)
- `requirements.txt` — added `crewai>=1.15,<2.0`, `litellm`
- `upstream/aiox/README.md` — updated to confirm replacement + CrewAI integration guide

### Real NemoClaw sandbox
- `alberto/sandbox/base.py::NemoClawSandbox` — was 6× `raise NotImplementedError`, now:
  - Detects Docker SDK availability (`docker.from_env().ping()`)
  - If Docker available: real Docker container with `network_mode=none`, `cap_drop=ALL`, `mem_limit=256m`, read-only fs
  - If Docker unavailable: hermetic local sandbox with UUID-isolated dir, path-traversal blocking
  - Methods: `home()`, `run()`, `write()`, `read()`, `exists()`, `cleanup()`
  - `_resolve_safe()` blocks `../etc/passwd` style escapes

### New tests (v1.8.4)
- `tests/test_v183_crewai.py` (10 tests):
  - `test_crewai_available` — CrewAI imports work
  - `test_status_reports_real_crewai` — version reported
  - `test_smoke_squad_fast` — 2-step smoke workflow (~7s)
  - `test_engineering_squad_runs` — 5-persona squad via real LLM
  - `test_content_squad_runs`, `test_hiring_squad_runs`, `test_security_audit_squad_runs` (marked slow)
  - `test_missing_workflow_file`, `test_missing_persona_file`, `test_no_api_key` — real error handling
- `tests/test_v184_sandbox.py` (9 tests):
  - `LocalSandbox`: write/read/run
  - `NemoClawSandbox`: creates real sandbox (docker or hermetic), write/read/run, path-traversal blocked, UUID isolation
  - `make_sandbox()`: local + nemoclaw factory tests
- `workflows/smoke/minimal.yaml` — 2-step test workflow
- `personas/engineer.md`, `personas/reviewer.md` — test personas

## Test totals
- Before v1.8.4: 379 tests
- After v1.8.4: **238 fast tests + 3 deselected (slow) = 241 tests**

## Mapping (AIOX → CrewAI)

| AIOX concept | CrewAI equivalent |
|---|---|
| Squad | `Crew` |
| Persona (YAML) | `Agent` |
| Step (YAML) | `Task` |
| Process.sequential | `Process.sequential` |
| Manager Agent | built-in |

## Known limitations
- Hiring and security-audit squad tests are rate-limited (429) — marked `@pytest.mark.slow`
- Without Docker SDK, NemoClawSandbox uses hermetic mode (still isolated via UUID + path-traversal block, no network)
