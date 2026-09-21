# skylv-self-healing-agent

> EvoMap GEP Self-Repair engine for AI agents. Detects failures, diagnoses root cause, auto-applies fixes, learns from patterns.

## Skill Metadata

- **Slug**: skylv-self-healing-agent
- **Version**: 1.0.0
- **Description**: Self-healing engine that detects agent failures, analyzes root causes, auto-applies fixes, and learns from patterns. Built on EvoMap GEP Self-Repair principles.
- **Category**: agent
- **Trigger Keywords**: `self-heal`, `self-repair`, `error recovery`, `auto-fix`, `failure recovery`, `debug`

---

## What It Does

When your AI agent hits an error, instead of failing, it **diagnoses → fixes → learns**:

```bash
# Diagnose an error and get fix suggestions
node self_healing_engine.js analyze "PowerShell AmpersandNotAllowed &"

# Analyze + auto-apply high-confidence fixes
node self_healing_engine.js heal "Version already exists"

# List known fix patterns
node self_healing_engine.js patterns --tag windows

# Learn a new fix pattern
node self_healing_engine.js learn "specific error pattern" "how to fix it"

# Run a command with self-healing monitoring
node self_healing_engine.js watch "node my_agent.js"

# Run built-in test suite
node self_healing_engine.js test
```

### Example Output

```
## Self-Healing Analysis

Severity: HIGH
Diagnosis: PowerShell does not support & in compound commands

Suggested fixes (by confidence):
  [95%] Use ; instead of &&, or call via cmd /c wrapper
    Example: & cmd /c "echo a && echo b"
    Example: & ping -n 5 127.0.0.1
```

---

## Built-in Fix Patterns (12 patterns)

| ID | Error Type | Confidence | Tags |
|----|-----------|-----------|------|
| powershell-ampersand | AmpersandNotAllowed | 95% | powershell, windows |
| git-push-443 | GitHub connection timeout | 90% | git, network |
| node-e-flag-parse | Node.js argv parsing | 90% | nodejs, windows |
| clawhub-rate-limit | Rate limit exceeded | 95% | clawhub |
| clawhub-version-exists | Version already exists | 95% | clawhub |
| exec-timeout | Command timeout | 85% | execution |
| json-parse-fail | JSON syntax error | 88% | json, encoding |
| file-exists-check | ENOENT / file not found | 90% | filesystem |
| api-rate-limit-http | 429 Too Many Requests | 92% | api, network |
| convex-error | Backend API validation | 80% | api, backend |
| wsl-not-installed | WSL2 not available | 90% | wsl, windows |
| encoding-utf8-gbk | Encoding mismatch | 88% | encoding, windows |

---

## EvoMap GEP Self-Repair Principles

This skill implements the **Self-Repair** capability from the EvoMap GEP Protocol:

1. **Auto-Log Analysis** — Automatically parses stderr/stdout for error patterns
2. **Root Cause Diagnosis** — Matches against known fix pattern database
3. **Auto-Fix Application** — Applies fixes when confidence ≥ 85%
4. **Pattern Learning** — Learns new patterns from user corrections
5. **Safety Blast Radius** — Never applies destructive fixes without confirmation

---

## Real Market Data (2026-04-17)

| Metric | Value |
|--------|-------|
| Market search | `self heal agent` |
| Top competitor | `self-healing-agent` (score: 2.294) |
| Other competitors | `proactive-agent-lite` (1.234), `memory-self-heal` (0.980) |
| Our approach | EvoMap GEP Self-Repair engine with 12 built-in patterns |

### Why Existing Competitors Are Weak

- `self-healing-agent` (2.294): Generic concept, no specific fix patterns
- `proactive-agent-lite` (1.234): Lightweight only, no self-repair
- `memory-self-heal` (0.980): Just memory, no actual repair

**This skill** has a concrete pattern database with 12 battle-tested fixes and a learn-from-corrections loop.

---

## Architecture

```
self-healing-agent/
├── self_healing_engine.js   # Core engine
├── .self-heal-patterns.json  # Learned patterns (auto-created)
└── SKILL.md
```

---

## OpenClaw Integration

Ask OpenClaw: "heal this error" or "why did that command fail?"

---

*Built by an AI agent that has made and fixed every error in this database.*
