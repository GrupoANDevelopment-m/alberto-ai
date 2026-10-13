# Alberto AI — v1.8.4 (hardening in progress)

**Alberto AI** is a modular Python agent framework that combines model routing, tool execution, persistent conversations, workflows, personas, skills, browser integrations, and a configurable sandbox. The project contains Alberto-owned orchestration code alongside vendored/upstream components; integration depth varies by subsystem.

> **Security status:** experimental. The CI regression suite is useful evidence, not a security certification. Do not expose an instance to untrusted users or allow unrestricted autonomous shell/skill execution without a properly configured isolation boundary and reviewed policy.

## What it does

- **Model access and routing:** OpenAI-compatible providers, configurable models, chat and tool-calling paths.
- **Tools and runtime:** file operations, shell/terminal execution, patch application, browser/search integrations, memory, tasks, and workflow/skill invocation.
- **Agent orchestration:** personas, YAML workflows, routing, conversations, and selected self-healing utilities.
- **Interfaces:** command-line interface (`alberto`) and HTTP/web interface (`alberto-serve`).
- **Quality tooling:** offline regression tests, security-focused tests, and a live-provider quality/latency benchmark.

Capabilities depend on installed optional components, provider credentials, network access, and sandbox mode. A listed tool or upstream directory does not by itself prove that every upstream feature is fully integrated or production-safe.

## Installation

Python 3.11 is the CI-tested version.

```bash
git clone https://github.com/GrupoANDevelopment-m/alberto-ai.git
cd alberto-ai
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e . --no-deps
```

System dependencies may be required for specific document, browser, or vision features. The CI workflow installs `poppler-utils`; browser features may also require Playwright browser binaries.

## Configure a model provider

Set credentials through environment variables. Never commit API keys to the repository or put them in examples, logs, or screenshots.

```bash
export NVIDIA_API_KEY="your-provider-key"
alberto model set chat nvidia google/diffusiongemma-26b-a4b-it https://integrate.api.nvidia.com/v1 NVIDIA_API_KEY
alberto chat "Olá, Alberto. Responde em português."
```

Use a provider and model that are currently enabled for your account. Provider/model availability, pricing, quotas, and multimodal support are external dependencies and can change.

Start the HTTP interface when needed:

```bash
alberto-serve --host 127.0.0.1 --port 8741
```

Keep the server bound to localhost during development. Before remote deployment, configure authentication, network ingress, secrets, logging, and a hardened execution environment; do not assume the development server is safe to expose publicly.

## Sandbox and execution safety

Alberto supports more than one sandbox mode. **These modes do not provide equivalent security.**

| Configuration | Meaning | Appropriate use |
|---|---|---|
| `ALBERTO_SANDBOX_KIND=local` (default when no mode is configured) | Runs commands as host processes under the current OS user. Workspace path checks are defense-in-depth, not an OS isolation boundary. | Local development and trusted testing only. |
| `ALBERTO_SANDBOX_KIND=nemoclaw` | Selects the NemoClaw/Docker-backed sandbox implementation. Actual isolation still depends on Docker being available and the container being configured correctly. | Preferred starting point for controlled execution; verify the deployed container policy. |
| `ALBERTO_REQUIRE_DOCKER=1` | Requires the NemoClaw mode. If a conflicting sandbox mode is explicitly configured, initialization fails rather than silently downgrading to host execution. | Environments where host-process fallback is unacceptable. |

For a Docker-required run, configure both variables explicitly:

```bash
export ALBERTO_REQUIRE_DOCKER=1
export ALBERTO_SANDBOX_KIND=nemoclaw
alberto --help
```

The application must fail to initialize if Docker isolation cannot be established. Do not interpret a class name, a passing unit test, or a successful CLI launch as proof of container isolation. Validate the effective runtime mode and Docker security options in the deployment environment.

### Additional execution controls

- Treat downloaded or locally installed skills as executable code. Review provenance and permissions before enabling them.
- Do not treat shell-command blocklists as a complete security boundary.
- Keep provider keys and other secrets outside skill workspaces and child-process environments where possible.
- Use least-privilege service accounts, filesystem restrictions, network egress controls, resource limits, timeouts, and disposable workspaces.
- Keep human approval for destructive actions, permission changes, deployments, and self-healing operations that mutate the host.
- Back up persistent memory/configuration before upgrades or repair operations.

## Test strategy

The GitHub Actions workflow runs targeted suites on Python 3.11. It separates offline regressions from provider-dependent tests and runs CLI smoke checks. Tests marked as network-, LLM-, or slow-dependent are excluded from the offline regression job; therefore, a green CI run is **not** evidence that live provider integrations, browser access, or all optional features work in the deployment environment.

Run the same principal offline regression suites locally:

```bash
export ALBERTO_OFFLINE=1
unset NVIDIA_API_KEY OPENAI_API_KEY
python -m pytest \
  tests/test_v15_unit.py \
  tests/test_v15_components.py \
  tests/test_v17_security.py \
  tests/test_file_read_security.py \
  tests/test_self_healing_control.py \
  tests/test_self_healing_safety.py \
  tests/test_multiedit_security.py \
  tests/test_alberto_cli_tool_security.py \
  tests/test_v184_sandbox.py \
  tests/test_sandbox_config.py \
  tests/test_skill_execution_security.py \
  tests/test_webfetch_ssrf.py \
  tests/test_shell_sandbox_routing.py \
  tests/test_hermes_sandbox_routing.py \
  tests/test_benchmark_alberto.py \
  tests/test_no_embedded_credentials.py -v --tb=short

python -m pytest tests/test_cli_smoke.py -v --tb=short
```

The CI workflow also runs selected integration and workflow-consistency tests with network/LLM/slow tests deselected. Use the workflow definition as the source of truth for the exact test selection.

## Live quality and latency benchmark

The benchmark sends **real prompts through Alberto's configured model route**. It does not generate replacement model responses. Provider errors are recorded as failures; they must not be counted as model-quality successes.

```bash
export NVIDIA_API_KEY="your-provider-key"
# Configure a model route before running the benchmark.
python scripts/benchmark_alberto.py --repeats 1 --pause 0.25
```

The default suite checks exact instruction following, arithmetic, structured JSON, line formatting, simple classification, multilingual output, and a basic logical condition. It reports case pass rate, errors, mean/median/p95 latency, and per-category metrics in a JSON report under `benchmark-results/`.

For a more stable comparison, run multiple repeats under the same provider, model, prompt suite, network conditions, and configuration. Record the commit SHA, model/provider, timestamp, and sandbox mode alongside the results. This benchmark is a small baseline—not a comprehensive reasoning benchmark—and it does not currently report reliable token usage or cost. A live run requires working provider credentials and was not executed by CI.

## Current verification and known limits

- The latest completed CI run for the hardening branch passed its selected suites on Python 3.11: 254 offline regression tests, 10 CLI smoke tests, and 290 passed / 2 skipped / 7 deselected in the additional regression job. See [pull request #8](https://github.com/GrupoANDevelopment-m/alberto-ai/pull/8) for the run history.
- The most recent completed coverage report measured **28% overall coverage**. Critical paths still need more branch coverage and adversarial testing.
- The CI suite deliberately skips or deselects provider/network-dependent tests. Those integrations require separate, credentialed end-to-end verification.
- Security changes include fail-closed shell execution when no sandbox is configured, sandbox-confined directory changes, safer patch application, sandbox-backed skill execution, SSRF-focused URL checks, and enforcement of `ALBERTO_REQUIRE_DOCKER` at agent initialization.
- These changes reduce specific risks; they do not prove the absence of vulnerabilities. The default `local` sandbox remains a host-process mode unless Docker-required mode is explicitly enabled.

## Repository map

- `alberto/` — agent, model routing, tools, orchestration, and runtime.
- `alberto/sandbox/` — local and NemoClaw/Docker-backed sandbox implementations.
- `alberto/engines/` and `alberto/runtime/` — tool engines, bridges, skills, workflow execution, and support modules.
- `upstream/` — vendored upstream source; check each component's license and integration path before redistribution or deployment.
- `personas/`, `workflows/`, `skills/` — persona definitions, workflow YAML, and executable skill material.
- `tests/` — unit, integration, security-regression, CLI, and benchmark-scoring tests.
- `scripts/benchmark_alberto.py` — real-provider quality/latency benchmark.
- `.github/workflows/ci.yml` — CI test selection and coverage reporting.

## Contributing

Keep changes narrow and traceable. Add a regression test for each fixed bug, run the relevant test subset, then run the complete CI selection. Do not claim performance gains without a reproducible baseline and comparable before/after runs. Do not claim production readiness based only on unit tests or README feature lists.

## License and upstream attribution

Review the repository's license and the licenses/notices for every vendored upstream component before distribution. Preserve required attribution and license files.
