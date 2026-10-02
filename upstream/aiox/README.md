# ⚠️ AIOX: REFERENCE DOCS ONLY (v1.8.2+)

AIOX upstream é **APENAS documentação + 21 YAMLs de workflows specs**.

## Status atual

```bash
$ find upstream/aiox -name "*.py" | wc -l
0                            # Zero código Python

$ find upstream/aiox -name "*.yaml" | wc -l
21                           # Só YAML specs

$ npm view @aiox/cli
404 Not Found                 # Não existe no npm registry
```

AIOX é um **framework de orquestração multi-agente** que foi descontinuado.
A SynkraAI (criadores) mantém apenas a documentação e os YAMLs de exemplo
em `upstream/aiox/squads/claude-code-mastery/`.

## Como Alberto usa AIOX

Alberto AI **NÃO depende** de AIOX runtime. Em vez disso, Alberto tem:

- **15 squads/workflows** em `workflows/*.yaml` (reais, executáveis)
- **37 personas** em `personas/*.md`
- **25+ tools Hermes** via `upstream_bridge.py`
- **Tool calling real** via `function_caller.py`

Os YAMLs AIOX em `claude-code-mastery/workflows/wf-*.yaml` servem apenas
como **referência** (exemplos de workflows bem estruturados). Eles não
são executados diretamente.

## Alternativas (próximas versões)

Para substituir AIOX no Alberto AI, avaliamos:

| Framework | Stars | Sub-agents | Runtime | Status |
|---|---|---|---|---|
| **DeerFlow** (ByteDance) | 14k+ | Sim (YAML) | Python | ⏳ Planejado v2.0 |
| **CrewAI** | 30k+ | Sim (role-based) | Python | ⏳ Opcional |
| **LangGraph** | 8k+ | Sim (DAG) | Python | ⏳ Opcional |
| **OpenAI Agents SDK** | 5k+ | Sim (handoffs) | Python | ⏳ Opcional |
| **Agno** | 18k+ | Sim | Python | ⏳ Opcional |

Nenhum desses vai substituir o AIOX upstream no Alberto. Em vez disso,
vamos adicionar **suporte para import** de workflows desses formatos.

Por enquanto, **os 15 workflows em `workflows/*.yaml` são a fonte da verdade**
do Alberto.
