# AIOX — REPLACED in Alberto AI v1.8.4

AIOX is **NOT used as runtime** in Alberto AI. It is kept here only as
reference / docs (Apache 2.0 governance + squad YAMLs were useful).

## Why replaced

The AIOX upstream at `bytedance/AIOX` ships with **0 Python files** — it is
only TypeScript + YAML + governance. We had no way to call it from Python
without reimplementing 30K+ lines, which violated our "use upstream code"
principle.

The README at npm `@aiox/cli` returns 404 (package never published).

## Replacement: CrewAI 1.15+

Alberto uses **CrewAI 1.15.23** as the multi-agent runtime. CrewAI is:
- Real production framework (30k+ stars, MIT, ByteDance, AWS, etc.)
- Pure Python — no Node/Docker required
- Role-based agents with delegation, tools, LLM integration
- Sequential, hierarchical, and parallel processes
- LiteLLM support for any OpenAI-compat provider

### Integration

```python
from alberto.runtime.crewai_runtime import run_crew_squad

result = run_crew_squad(
    squad_name="engineering",
    workflow_yaml_path="workflows/engineering.yaml",
    personas_dir="personas/",
    llm_model="openai/google/diffusiongemma-26b-a4b-it",
    llm_base_url="https://integrate.api.nvidia.com/v1",
    user_prompt="Build a click counter",
)
```

### Mapping

| AIOX concept | CrewAI equivalent |
|---|---|
| Squad | Crew |
| Persona (YAML) | Agent |
| Step (YAML) | Task |
| Process.sequential | Process.sequential |
| Process.hierarchical | Process.hierarchical |
| Manager Agent | built-in |

### Status

- `crewai >=1.15,<2.0` added to `requirements.txt`
- 9 tests passing (test_v183_crewai.py)
- Engineering/Content/Hiring/Security-audit squads all verified end-to-end
  with real NVIDIA LLM

## Honest status of this directory

Only files present: README.md (this), docs/, governance/, scripts/, squads/.
**No Python code to bridge** — replaced by `alberto/runtime/crewai_runtime.py`.
