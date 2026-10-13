# Alberto AI — Security Review and Remediation Status

**Status:** ongoing engineering review; **not** an independent penetration test or certification.  
**Scope:** repository source and targeted GitHub Actions regression tests on the `audit/integrated-hardening` branch.  
**Last reviewed:** 2026-10-13.

## Important correction to the previous report

The former v1.7 report described Alberto as “safe for production” and assigned a 9.0/10 score. That conclusion was not supported by an independent audit, a documented threat model, or comprehensive adversarial testing. The score is withdrawn. Passing tests only demonstrate the behavior covered by those tests; they do not establish that the application is secure.

## Findings and current disposition

| Finding | Risk | Current disposition |
|---|---|---|
| Host-process sandbox can execute commands as the current OS user | **Critical when exposed to untrusted prompts/tools** | Explicitly documented. `ALBERTO_REQUIRE_DOCKER=1` now selects NemoClaw mode by default and rejects a conflicting explicit mode. Deployment must still verify Docker actually starts with the expected restrictions. |
| Shell safety based on pattern blocking is incomplete | High | Shell execution now fails closed if no sandbox object is configured and routes through the configured sandbox. Pattern checks remain defense-in-depth, not a complete shell allowlist. |
| Skills may contain executable shell/Python instructions | High | Treat skills as executable code. Provenance review, integrity validation, restricted permissions, and stronger approval controls remain necessary. |
| Patch application can modify or create files | High | The patch handler uses validated patch operations and confines resolved targets to the target directory, applies protected-path checks, and has regression coverage. Further adversarial testing for symlinks, malformed hunks, race conditions, and partial writes remains required. |
| Directory changes can escape intended workspace | High | The working-directory handler confines paths to the configured sandbox home and persists only validated directories. Regression tests cover traversal rejection. |
| SSRF and unsafe URL fetches | High | URL-safety regression tests are in CI. DNS rebinding, redirect chains, IPv6 variants, proxy behavior, and every browser/fetch path still require independent adversarial coverage. |
| Self-healing can mutate runtime state or restart processes | High | Targeted safety/control tests run in CI. Rollback, checkpoints, approval boundaries, and recovery after partial failure require further validation. |
| Test coverage is low for the size of the codebase | High | The last completed coverage report before the latest configuration tests was **28% overall**. Critical security and orchestration modules need higher branch coverage. |
| Provider and network integrations are not fully exercised in offline CI | Medium–High | Offline tests deliberately deselect network-, LLM-, and slow-marked cases. Live integration and quality benchmarks must be run separately with authorized credentials. |
| Lockfile, deployment configuration, dependencies, and upstream integration | Medium–High | Must be reviewed for the actual deployment. A vendored source tree or dependency installation does not prove complete integration or secure configuration. |

## Security changes made in the hardening branch

- Shell and actor execution require a configured sandbox instead of silently using an unconfigured direct execution path.
- Actor sessions and their working directories are confined to the sandbox workspace.
- Directory changes are checked against the sandbox home.
- Patch application uses parsed operations, target-directory confinement, and protected-path checks.
- Skills are routed through the configured sandbox, with regression tests for nonzero exits.
- URL-fetch security has regression coverage for SSRF-related cases.
- `ALBERTO_REQUIRE_DOCKER` is enforced during agent initialization: if enabled, a conflicting explicit sandbox mode fails closed rather than silently falling back to host execution.
- Tests were added for the required-Docker configuration path.

These changes address specific code paths; they do not establish that all tools share the same controls or that every upstream tool follows the same policy. Verify each execution route in the deployed configuration.

## Reproducible validation

The GitHub Actions workflow on Python 3.11 runs:
1. targeted offline unit and security-regression suites;
2. CLI smoke tests;
3. selected integration/workflow tests with network, LLM, and slow tests deselected;
4. coverage reporting.

The last completed CI run before the Docker-configuration regression was added reported **290 passed, 2 skipped, and 7 deselected** in the additional offline regression job, with **28% total coverage** in the coverage job. A newer CI run must be checked before treating that as the current result. Passing offline tests do not validate live provider credentials, browser access, Docker isolation in deployment, or all optional integrations.

For a local run, follow the exact test commands in `.github/workflows/ci.yml`. Avoid running provider-dependent tests without explicit authorization and valid credentials.

## Required work before a production-readiness claim

1. Define trust boundaries and a threat model for prompt injection, malicious skills, untrusted files, network fetches, secrets, and tool execution.
2. Make the intended isolation mode explicit in deployment configuration; verify container user, mounts, capabilities, network policy, resource limits, filesystem mode, and secret exposure.
3. Expand adversarial tests for path traversal, symlinks, shell variants, patch edge cases, SSRF/redirects, malicious skills, prompt injection, and concurrent operations.
4. Add rollback/checkpoint tests for self-healing and file mutation.
5. Raise branch coverage on critical security paths and run tests across supported Python versions.
6. Run live-provider benchmarks and integration tests with recorded provider/model/commit metadata. Report failures, latency distributions, and quality scores; do not substitute synthetic responses.
7. Review dependency pinning, licenses, upstream notices, and the actual packaging/deployment artifacts.
8. Arrange an independent penetration test before making an external security certification or production-safety claim.

## Operational guidance

- For trusted local development only, the default `local` mode runs subprocesses on the host and is **not** an OS security boundary.
- For an environment that cannot permit host-process fallback, configure both `ALBERTO_REQUIRE_DOCKER=1` and `ALBERTO_SANDBOX_KIND=nemoclaw`, then validate the running container's actual settings.
- Bind the web server to localhost unless authentication and remote-access controls have been configured and reviewed.
- Never commit provider keys. Use least-privilege credentials, network egress restrictions, explicit approval for destructive operations, and backups before upgrades or repair operations.

**Conclusion:** Alberto has meaningful security controls and a growing regression suite, but the evidence currently supports “experimental framework undergoing hardening,” not “independently verified safe for production.”
