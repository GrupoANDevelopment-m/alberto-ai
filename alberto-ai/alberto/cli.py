#!/usr/bin/env python3
"""
alberto — CLI entry point.

Usage:
    alberto banner                           # show identity banner
    alberto status                           # show engine/model/squad status
    alberto chat "<prompt>"                  # quick chat (uses task=chat)
    alberto ask "<prompt>"                   # dispatch via orchestrator
    alberto memory set <key> <value>         # set memory
    alberto memory get <key>                 # get memory
    alberto memory search <query>            # search memory
    alberto memory list                      # list all memory
    alberto model list                       # list configured tasks
    alberto model set <task> <provider> <model_id> <base_url> <cred_env>
    alberto model test <task>                # show env vars
    alberto squad list                       # list available squads
    alberto squad describe <name>            # show squad details
    alberto squad activate <name>            # opt-in to a squad
    alberto squad hibernate                  # opt-out
    alberto squad run <name> "<prompt>"      # run squad workflow
    alberto s list                           # list shortcuts
    alberto s add <key> "<expansion>"        # add shortcut
    alberto s rm <key>                       # remove shortcut
    alberto s <key> [args]                   # invoke shortcut
    alberto hermes browser <url>             # fetch URL
    alberto hermes exec "<python code>"      # sandboxed python
    alberto strategy "<prompt>"              # show orchestrator decision

Environment:
    ALBERTO_SANDBOX_KIND = local | nemoclaw (default: local)
    ALBERTO_SANDBOX_BASE = path (default: tempdir)
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import shlex
from pathlib import Path
from typing import List

from .agent import Alberto
from .identity import get_banner, NAME, VERSION
from .tools_registry import list_tools, invoke_tool


def _get_alberto(**kwargs) -> Alberto:
    """Lazy-init Alberto singleton (one per CLI invocation)."""
    base = Path(__file__).parent.parent
    catalog_dir = base / "workflows"
    personas_dir = base / "personas"
    return Alberto(catalog_dir=catalog_dir, personas_dir=personas_dir, **kwargs)


def cmd_banner(args, alberto: Alberto) -> int:
    print(get_banner())
    return 0


def cmd_status(args, alberto: Alberto) -> int:
    print(json.dumps(alberto.status(), indent=2))
    return 0


def cmd_chat(args, alberto: Alberto) -> int:
    out = alberto.chat(args.prompt)
    print(out)
    return 0


def cmd_ask(args, alberto: Alberto) -> int:
    out = alberto.dispatch(args.prompt)
    strat = out["strategy"]
    print(f"[strategy] {strat.mode} | engine={strat.engine} | task={strat.task_routing} | {strat.reason}")
    result = out["result"]
    if isinstance(result, dict):
        print(json.dumps(result, indent=2))
    else:
        print(result)
    return 0


def cmd_memory(args, alberto: Alberto) -> int:
    if args.action == "set":
        alberto.memory_set(args.key, args.value)
        print(f"ok: {args.key}")
    elif args.action == "get":
        v = alberto.memory_get(args.key)
        print(v if v is not None else "(not found)")
    elif args.action == "search":
        for hit in alberto.memory_search(args.query):
            print(f"[{hit['key']}] {hit['value'][:120]}")
    elif args.action == "list":
        for hit in alberto.memory_list():
            print(f"[{hit['key']}] {hit['value'][:120]}")
    return 0


def cmd_model(args, alberto: Alberto) -> int:
    if args.action == "list":
        for t in alberto.model_list():
            spec = alberto.router.resolve(t)
            print(f"{t}: {spec.provider}/{spec.model_id} @ {spec.base_url}")
    elif args.action == "set":
        alberto.model_set(
            args.task,
            provider=args.provider,
            model_id=args.model_id,
            base_url=args.base_url,
            credential_env=args.cred_env,
        )
        print(f"ok: {args.task} -> {args.provider}/{args.model_id}")
    elif args.action == "test":
        env = alberto.model_test(args.task)
        if not env:
            print(f"no model configured for task '{args.task}'")
            return 1
        for k, v in env.items():
            masked = v if k != "OPENAI_API_KEY" else v[:6] + "***"
            print(f"{k}={masked}")
    return 0


def cmd_squad(args, alberto: Alberto) -> int:
    if args.action == "list":
        for s in alberto.squad_list():
            print(s)
    elif args.action == "describe":
        d = alberto.squad_describe(args.name)
        if d is None:
            print(f"unknown squad: {args.name}")
            return 1
        print(json.dumps(d, indent=2))
    elif args.action == "activate":
        alberto.squad_activate(args.name)
        print(f"ok: {args.name} activated")
    elif args.action == "hibernate":
        alberto.squad_hibernate()
        print("ok: no active squad")
    elif args.action == "run":
        out = alberto.run_squad(args.name, args.prompt)
        print(json.dumps(out, indent=2))
    return 0


def cmd_shortcut(args, alberto: Alberto) -> int:
    if args.action == "list":
        for k, v in alberto.shortcuts.list().items():
            print(f"{k:20s} → {v.expansion}")
    elif args.action == "add":
        alberto.shortcuts.add(args.key, args.expansion)
        print(f"ok: /s {args.key} → {args.expansion}")
    elif args.action == "rm":
        ok = alberto.shortcuts.remove(args.key)
        print("ok" if ok else "not found")
    elif args.action == "show":
        sc = alberto.shortcuts.get(args.key)
        if sc is None:
            print("not found")
            return 1
        print(json.dumps({"key": args.key, **sc.__dict__}, indent=2))
    elif args.action == "use":
        rest = " ".join(args.rest or [])
        out = alberto.shortcut_expand(args.key, rest)
        if out is None:
            print(f"no shortcut '{args.key}'")
            return 1
        print(out)
    return 0


def cmd_hermes(args, alberto: Alberto) -> int:
    if not alberto.hermes.is_running():
        alberto.hermes.start()
    if args.action == "browser":
        out = alberto.hermes.browser(args.url)
        print(out)
    elif args.action == "exec":
        result = alberto.hermes.code_execution(args.code)
        print(json.dumps(result, indent=2))
    return 0


def cmd_strategy(args, alberto: Alberto) -> int:
    strat = alberto.orchestrator.decide(args.prompt, active_squad=alberto.catalog.active_squad)
    print(json.dumps({
        "mode": strat.mode, "reason": strat.reason,
        "engine": strat.engine, "squad": strat.squad,
        "task_routing": strat.task_routing,
    }, indent=2))
    return 0




def cmd_serve(args, alberto):
    from .server import run_server
    run_server(host=args.host, port=args.port)
    return 0


def cmd_tool(args, alberto):
    import json as _json
    try:
        payload = _json.loads(args.args_json or "{}")
    except Exception as e:
        print(f"invalid JSON: {e}")
        return 1
    result = invoke_tool(alberto, args.name, payload)
    print(_json.dumps(result, indent=2))
    return 0


def cmd_tools(args, alberto):
    print(json.dumps(list_tools(), indent=2))
    return 0


def cmd_loop(args, alberto):
    """24/7 autonomy loop. Blocks until SIGINT or --max reached."""
    from alberto.runtime.autonomy import AutonomyLoop
    loop = AutonomyLoop(alberto, tick_seconds=args.tick, max_iterations=args.max)
    loop.start()
    return 0


def cmd_mcp(args, alberto):
    """MCP server management."""
    a = args.mcp_action
    if a == "list":
        for s in alberto.mcp.list_servers():
            mark = "🟢" if s["connected"] else "⚪"
            print(f"  {mark} {s['name']:25s} {s['transport']:6s} {s['command'] or s['url'] or ''} tools={s['tools']}")
    elif a == "add" and args.mcp_args:
        name = args.mcp_args[0]
        cmd = args.mcp_args[1] if len(args.mcp_args) > 1 else None
        cmd_args = args.mcp_args[2:] if len(args.mcp_args) > 2 else []
        alberto.mcp.add(name, command=cmd, args=cmd_args)
        print(f"added MCP server {name}")
    elif a == "connect" and args.mcp_args:
        ok = alberto.mcp.connect(args.mcp_args[0])
        print(f"{'connected' if ok else 'failed'}: {args.mcp_args[0]}")
    elif a == "disconnect" and args.mcp_args:
        alberto.mcp.disconnect(args.mcp_args[0])
        print(f"disconnected {args.mcp_args[0]}")
    elif a == "call" and len(args.mcp_args) >= 2:
        import json
        tool_args = json.loads(args.mcp_args[2]) if len(args.mcp_args) > 2 else {}
        result = alberto.mcp.call(args.mcp_args[0], args.mcp_args[1], tool_args)
        print(json.dumps(result, indent=2))
    return 0


def cmd_install(args, alberto):
    """Extension installer."""
    a = args.install_action
    if a == "install" and args.install_args:
        name = args.install_args[0]
        ext = alberto.extensions.install(name, source=args.source, ext_type=args.type)
        print(f"installed {ext.ext_type} {ext.name}")
    elif a == "uninstall" and args.install_args:
        ok = alberto.extensions.uninstall(args.install_args[0])
        print(f"uninstalled: {ok}")
    elif a == "list":
        for ext in alberto.extensions.list():
            mark = "🟢" if ext.enabled else "⚪"
            print(f"  {mark} {ext.ext_type:8s} {ext.name:30s} v{ext.version} — {ext.description[:50]}")
    elif a == "enable" and args.install_args:
        alberto.extensions.enable(args.install_args[0])
    elif a == "disable" and args.install_args:
        alberto.extensions.disable(args.install_args[0])
    elif a == "create-skill" and args.install_args:
        name = args.install_args[0]
        path = alberto.extensions.create_skill(name, description=args.description or name,
                                               content=args.content or f"Auto-created skill: {name}",
                                               category=args.category)
        print(f"created skill at {path}")
    return 0


def cmd_app(args, alberto):
    """App creation from description."""
    if args.app_action == "create" and args.app_args:
        name = args.app_args[0]
        desc = args.description or " ".join(args.app_args[1:]) or "An app created by Alberto"
        from alberto.runtime.app_creator import AppCreator
        from pathlib import Path
        creator = AppCreator(output_dir=Path(args.output))
        result = creator.create(name, desc, run=args.run)
        print(json.dumps(result, indent=2))
    return 0


def cmd_skill(args, alberto):
    """Skill engine — list, show, run, commands."""
    from alberto.runtime.skill_engine import list_skills, show_skill, run_skill
    a = args.skill_action
    if a == "list":
        skills = list_skills()
        from collections import defaultdict
        by_cat = defaultdict(int)
        for s in skills:
            by_cat[s["category"]] += 1
        print(f"{len(skills)} skills:")
        for cat, count in sorted(by_cat.items(), key=lambda x: -x[1]):
            print(f"  {cat:30s} {count:3d}")
    elif a == "show" and args.skill_args:
        import json
        print(json.dumps(show_skill(args.skill_args[0]), indent=2, ensure_ascii=False))
    elif a == "run" and args.skill_args:
        name = args.skill_args[0]
        rargs = args.skill_args[1:]
        r = run_skill(name, rargs, sandbox=alberto.sandbox, timeout=args.timeout)
        if r.get("ok"):
            print(r.get("stdout", ""))
        else:
            print(f"FAIL: {r.get('error','')}", file=sys.stderr)
            if r.get("stderr"):
                print(r["stderr"], file=sys.stderr)
    elif a == "commands" and args.skill_args:
        from alberto.runtime.skill_engine import find_skill, extract_code_blocks
        path = find_skill(args.skill_args[0])
        if not path:
            print(f"skill '{args.skill_args[0]}' not found", file=sys.stderr)
            return 1
        content = path.read_text(encoding="utf-8", errors="replace")
        blocks = extract_code_blocks(content)
        for i, b in enumerate(blocks):
            print(f"\n--- block {i+1} ({b['lang']}) ---")
            print(b["code"][:400])
    elif a == "run-all" and args.skill_args:
        from alberto.runtime.skill_engine import find_skill, extract_code_blocks, substitute_args
        import subprocess
        path = find_skill(args.skill_args[0])
        if not path:
            print(f"skill '{args.skill_args[0]}' not found", file=sys.stderr)
            return 1
        content = path.read_text(encoding="utf-8", errors="replace")
        blocks = extract_code_blocks(content)
        rargs = args.skill_args[1:]
        for i, b in enumerate(blocks):
            if b["lang"] not in ("bash", "sh", "shell", "python", "python3", "py"):
                continue
            code = substitute_args(b["code"], rargs)
            print(f"\n--- block {i+1} ({b['lang']}) ---")
            try:
                if b["lang"] in ("python", "python3", "py"):
                    cmd = [sys.executable, "-c", code]
                else:
                    cmd = ["bash", "-c", code]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=args.timeout)
                if result.stdout:
                    print(result.stdout, end="")
                if result.stderr:
                    print(result.stderr, end="", file=sys.stderr)
            except subprocess.TimeoutExpired:
                print(f"timeout after {args.timeout}s", file=sys.stderr)
    return 0


def cmd_research(args, alberto):
    """Autonomous research — search DuckDuckGo, Wikipedia, arXiv, local skills."""
    import json
    a = args.research_action
    if a == "search" and args.research_args:
        query = " ".join(args.research_args)
        result = alberto.researcher.search(query, sources=args.sources.split(","), limit=args.limit)
        print(json.dumps(result, indent=2, ensure_ascii=False)[:5000])
    elif a == "study" and args.research_args:
        target = " ".join(args.research_args)
        result = alberto.researcher.study(target)
        print(f"✓ Studied '{target}'")
        print(f"  sources: {result.get('sources_used')}")
        print(f"  hits: {result.get('total_hits')}")
        print(f"  cached: {result.get('cached_at')}")
    elif a == "replicate" and args.research_args:
        target = " ".join(args.research_args)
        result = alberto.researcher.replicate(target)
        print(f"✓ Replication plan for '{target}'")
        print(json.dumps(result.get("plan", {}), indent=2)[:3000])
    return 0


def cmd_learn(args, alberto):
    """Learner — create/evolve skills, lessons learned, user profile."""
    a = args.learn_action
    if a == "create-skill" and args.learn_args:
        name = args.learn_args[0]
        path = alberto.learner.create_skill(
            name, description=args.description or name,
            content=args.content or f"Auto-created skill: {name}",
            category=args.category,
        )
        print(f"created: {path}")
    elif a == "evolve-skill" and args.learn_args:
        path = alberto.learner.evolve_skill(args.learn_args[0], improvements=args.improvements or "")
        print(f"evolved: {path}")
    elif a == "lesson":
        l = alberto.learner.lesson_learned(
            mistake=args.mistake, why=args.why, fix=args.fix,
            context=args.context, severity=args.severity,
        )
        print(f"lesson recorded: {l['id']}")
    elif a == "recall-lessons":
        lessons = alberto.learner.recall_lessons(args.query or "", limit=args.limit)
        for l in lessons:
            print(f"  [{l.get('severity','info')}] {l['mistake']} → {l['fix']}")
    elif a == "overcome" and args.learn_args:
        path = alberto.learner.overcome_obstacle(
            args.learn_args[0], tried=args.tried, workaround=args.workaround,
        )
        print(f"obstacle skill: {path}")
    elif a == "observe" and args.learn_args:
        alberto.learner.observe_interaction(args.learn_args[0], args.response or "")
        print("observed")
    elif a == "adapt":
        import json
        print(json.dumps(alberto.learner.get_adaptation_hints(), indent=2, ensure_ascii=False))
    elif a == "apply":
        warnings = alberto.learner.apply_lessons(args.action or "")
        if warnings:
            for w in warnings:
                print(w)
        else:
            print("no applicable lessons")
    return 0


def cmd_test(args, alberto):
    """Intensive testing of apps/systems."""
    from alberto.runtime.tester import AppTester
    t = AppTester(Path(args.app_dir))
    if args.phase == "smoke":
        r = t.smoke()
    elif args.phase == "perf":
        r = t.perf(args.endpoint, n_requests=args.n, concurrency=args.concurrency)
    elif args.phase == "install":
        r = t.test_install()
    elif args.phase == "e2e":
        r = t.test_frontend_e2e()
    else:
        r = t.full()
    import json
    print(json.dumps(r, indent=2, default=str))
    return 0 if r.get("ok") else 1


def cmd_router(args, alberto):
    """Smart LLM router — cost + latency optimization with fallback."""
    import json
    a = args.router_action
    alberto.smart_router._ensure_loaded()
    if a == "list":
        for s in alberto.smart_router.specs:
            print(f"  [{s.capability:10s}] {s.provider:10s} {s.model_id:35s} cost_in=${s.cost_per_1k_input:.4f}/1k priority={s.priority}")
    elif a == "stats":
        for mid, st in alberto.smart_router.stats.items():
            print(f"  {mid:35s} calls={st.calls} ok={st.successes} fail={st.failures} cost=${st.total_cost_usd:.4f} avg={st.avg_latency_ms:.0f}ms")
    elif a == "cost":
        print(f"Total cost: ${alberto.smart_router.total_cost():.4f}")
    elif a == "rank":
        ranked = alberto.smart_router.rank_models(args.task, prefer_cheap=args.cheap)
        for s in ranked:
            print(f"  {s.model_id:35s} priority={s.priority} cost_in=${s.cost_per_1k_input:.4f}")
    elif a == "test":
        r = alberto.smart_router.complete(
            [{"role":"user","content":args.prompt or "ping"}],
            task=args.task, max_tokens=20
        )
        if r.get("ok"):
            print(f"model: {r.get('model_used')}")
            print(f"content: {r.get('content','')[:200]}")
            print(f"tokens: in={r.get('input_tokens')} out={r.get('output_tokens')}")
            print(f"cost: ${(r.get('input_tokens',0)/1000)*0.0001 + (r.get('output_tokens',0)/1000)*0.0001:.6f}")
        else:
            print(f"FAIL: {r.get('error')}")
    return 0


def cmd_heal(args, alberto):
    """Self-healing — recovery from failures."""
    import json
    if args.heal_action == "attempt":
        try:
            err = Exception(args.error)
        except Exception:
            err = RuntimeError(args.error)
        r = alberto.healer.attempt_heal(err, args.context or "")
        print(json.dumps(r, indent=2, default=str))
    elif args.heal_action == "log":
        for h in alberto.healer.history[-args.limit:]:
            ts = h.get("at", 0)
            err_str = h.get("error", "")[:60]
            fixed = h.get("fixed")
            print(f"  [{ts:.0f}] {err_str} -> fixed={fixed}")
    return 0


def cmd_meta(args, alberto):
    """Meta controller — the executive function."""
    from alberto.runtime.meta_controller import MetaController
    mc = MetaController(alberto)
    a = args.meta_action
    if a == "plan" and args.meta_args:
        objective = " ".join(args.meta_args)
        plan = mc.plan_objective(objective)
        print(f"Plan: {plan.objective}")
        print(f"  status: {plan.status}, subtasks: {len(plan.subtasks)}")
        for st in plan.subtasks:
            print(f"    - {st.id}: {st.description[:50]}")
            print(f"      skill: {st.skill or '(none)'}")
        if args.run:
            events = []
            def on_event(event, data):
                events.append((event, data))
                print(f"    [event] {event}: {list(data.keys())}")
            mc.on_event(on_event)
            print("\nExecuting...")
            plan = mc.execute(plan)
            print(f"\nFinal status: {plan.status}, iterations: {plan.iterations}")
            for st in plan.subtasks:
                print(f"  {st.id}: {st.status} (skill={st.skill}, attempts={st.attempts})")
    elif a == "skills":
        sa = args.meta_args[0] if args.meta_args else "list"
        if sa == "list":
            print(f"{mc.skill_manager.total()} skills managed")
        elif sa == "search" and args.meta_args[1:]:
            q = " ".join(args.meta_args[1:]) or args.query
            print(f"Search: {q!r}")
            for r in mc.skill_manager.search(q, limit=args.limit):
                print(f"  {r['score']:.2f} {r['skill']['name']:30s} [{r['skill']['category']}]")
        elif sa == "recommend" and args.meta_args[1:]:
            q = " ".join(args.meta_args[1:]) or args.query
            print(f"Recommend for: {q!r}")
            for r in mc.skill_manager.recommend(q, top=args.limit):
                s = r["skill"]
                stats = s["stats"]
                sr = stats["success"] / max(1, stats["success"] + stats["fail"])
                print(f"  {r['score']:.2f} {s['name']:30s} [{s['category']}] success_rate={sr:.0%}")
        elif sa == "stats":
            n = 0
            for nm, m in mc.skill_manager.index.items():
                stats = m["stats"]
                if stats["success"] or stats["fail"]:
                    print(f"  {nm:30s} ok={stats['success']} fail={stats['fail']}")
                    n += 1
                if n >= args.limit: break
            if n == 0:
                print("  (no stats yet)")
        elif sa == "top":
            for p in mc.skill_manager.get_top_performers(n=args.limit):
                print(f"  {p['name']:30s} {p['success_rate']*100:.0f}% ({p['success']}/{p['success']+p['fail']})")
        elif sa == "failures":
            for p in mc.skill_manager.get_failure_prone(n=args.limit):
                print(f"  {p['name']:30s} fails={p['fail']}")
    elif a == "history":
        for h in mc.get_history(limit=args.limit):
            print(f"  {h['objective'][:50]:50s} → {h['status']}")
    return 0


def cmd_aiox(args, alberto):
    """AIOX squad management — list/run workflows."""
    from .runtime.integration import list_aiox_workflows, run_aiox_workflow
    if args.aiox_action == "list":
        wfs = list_aiox_workflows()
        print(f"AIOX workflows ({len(wfs)}):")
        for w in wfs:
            print(f"  - {w}")
    elif args.aiox_action == "run":
        if not args.workflow:
            print("usage: alberto aiox run <workflow>")
            return 1
        r = run_aiox_workflow(args.workflow, alberto)
        print(json.dumps(r, indent=2, ensure_ascii=False))
    return 0


def cmd_nemoclaw(args, alberto):
    """NemoClaw sandbox status."""
    from .runtime.integration import nemoclaw_sandbox_status
    print(json.dumps(nemoclaw_sandbox_status(), indent=2))
    return 0


def cmd_security(args, alberto):
    """Test NemoClaw security: scan a string for secrets + check a path."""
    from .runtime.nemoclaw_real import (
        scan_secrets, is_protected_path, scan_env_leak, nemoclaw_pre_write_check, SECRET_PATTERNS
    )
    if args.security_action == "scan":
        if not args.text:
            print("usage: alberto security scan <text>")
            return 1
        matches = scan_secrets(args.text)
        if matches:
            print(f"FOUND {len(matches)} secret(s):")
            for m in matches:
                print(f"  - {m['pattern']}: {m['redacted']}")
        else:
            print("CLEAN: no secrets detected")
    elif args.security_action == "path":
        p = args.text or args.path
        if not p:
            print("usage: alberto security path <path>")
            return 1
        blocked = is_protected_path(p)
        print(f"{'BLOCKED' if blocked else 'ALLOWED'}: {p}")
    elif args.security_action == "patterns":
        print(f"{len(SECRET_PATTERNS)} secret patterns loaded:")
        for name, _ in SECRET_PATTERNS:
            print(f"  - {name}")
    return 0


def cmd_vision(args, alberto):
    """Vision API: describe image with text prompt."""
    from .runtime.integration import call_vision
    enable_thinking = not args.no_thinking
    result = call_vision(alberto, args.text, args.image_url,
                        model=args.model, enable_thinking=enable_thinking)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str)[:2000])
    return 0


def cmd_auto_invoke(args, alberto):
    """Auto-detect which skill should run for an intent."""
    from .runtime.skill_engine import auto_invoke_skill
    result = auto_invoke_skill(args.intent)
    if result:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("No skill matches this intent")
    return 0


def cmd_fallback(args, alberto):
    """Setup auto-fallback chain (deepseek-v4-pro -> gemma4)."""
    from .runtime.integration import setup_fallback_chain
    primary = args.primary or "deepseek-ai/deepseek-v4-pro-0813"
    fallback = args.fallback or "google/diffusiongemma-26b-a4b-it"
    ok = setup_fallback_chain(alberto, primary=primary, fallback=fallback)
    if ok:
        print(f"✓ Fallback chain: {primary} -> {fallback}")
        print(f"  Primary supports function calling (deepseek emits tool_calls)")
        print(f"  Fallback is gemma4 (no FC) - Mavis takes over via 'Comando:' interceptor")
    else:
        print("✗ Failed to setup fallback")
    return 0


def main(argv: List[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    parser = argparse.ArgumentParser(prog="alberto", description=f"{NAME} v{VERSION}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("banner", help="show identity banner")
    sub.add_parser("status", help="show engine/model/squad status")

    p = sub.add_parser("chat", help="quick chat")
    p.add_argument("prompt")

    p = sub.add_parser("ask", help="dispatch via orchestrator")
    p.add_argument("prompt")

    p = sub.add_parser("memory", help="memory ops")
    p.add_argument("action", choices=["set", "get", "search", "list"])
    p.add_argument("args", nargs="*")

    p = sub.add_parser("model", help="model config")
    p.add_argument("action", choices=["list", "set", "test"])
    p.add_argument("args", nargs="*")

    p = sub.add_parser("squad", help="squad ops")
    p.add_argument("action", choices=["list", "describe", "activate", "hibernate", "run"])
    p.add_argument("args", nargs="*")

    p = sub.add_parser("s", help="shortcuts")
    p.add_argument("action", choices=["list", "add", "rm", "show", "use"])
    p.add_argument("args", nargs="*")

    p = sub.add_parser("hermes", help="hermes engine commands")
    p.add_argument("action", choices=["browser", "exec"])
    p.add_argument("args", nargs="*")

    p = sub.add_parser("strategy", help="show orchestrator decision")
    p.add_argument("prompt")

    p = sub.add_parser("serve", help="start HTTP server (frontend + API)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8741)

    p = sub.add_parser("tool", help="invoke a tool")
    p.add_argument("name")
    p.add_argument("args_json", nargs="?", default="{}")

    p = sub.add_parser("tools", help="list available tools")

    # New: 24/7 loop
    p = sub.add_parser("loop", help="start 24/7 autonomy loop")
    p.add_argument("--tick", type=float, default=60.0)
    p.add_argument("--max", type=int, default=None)

    # New: MCP
    p = sub.add_parser("mcp", help="MCP server management")
    p.add_argument("mcp_action", choices=["list", "add", "connect", "disconnect", "call"])
    p.add_argument("mcp_args", nargs="*")

    # New: install/extension
    p = sub.add_parser("install", help="install/manage extensions")
    p.add_argument("install_action", choices=["install", "uninstall", "list", "enable", "disable", "create-skill"])
    p.add_argument("install_args", nargs="*")
    p.add_argument("--source")
    p.add_argument("--type", default="skill")
    p.add_argument("--description")
    p.add_argument("--content")
    p.add_argument("--category", default="user")

    # New: app creation
    p = sub.add_parser("app", help="create complete app from description")
    p.add_argument("app_action", choices=["create"])
    p.add_argument("app_args", nargs="*")
    p.add_argument("--description")
    p.add_argument("--run", action="store_true")
    p.add_argument("--output", default="./apps")

    # New: skill engine
    p = sub.add_parser("skill", help="list/show/run skills")
    p.add_argument("skill_action", choices=["list", "show", "run", "run-all", "commands"])
    p.add_argument("skill_args", nargs="*")
    p.add_argument("--timeout", type=int, default=60)

    # New: research
    p = sub.add_parser("research", help="search/study/replicate")
    p.add_argument("research_action", choices=["search", "study", "replicate"])
    p.add_argument("research_args", nargs="*")
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--sources", default="duckduckgo,wikipedia,arxiv,local_skills")

    # New: learn
    p = sub.add_parser("learn", help="learn from experience, create/evolve skills")
    p.add_argument("learn_action", choices=["create-skill", "evolve-skill", "lesson", "recall-lessons",
                                              "overcome", "observe", "adapt", "apply"])
    p.add_argument("learn_args", nargs="*")
    p.add_argument("--query", default="")
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--description", default=None)
    p.add_argument("--content", default=None)
    p.add_argument("--category", default="user")
    p.add_argument("--improvements", default=None)
    p.add_argument("--mistake", default=None)
    p.add_argument("--why", default="")
    p.add_argument("--fix", default=None)
    p.add_argument("--context", default="")
    p.add_argument("--severity", default="info")
    p.add_argument("--response", default="")
    p.add_argument("--action", default="")
    p.add_argument("--tried", nargs="*", default=[])
    p.add_argument("--workaround", default="")

    # New: test
    p = sub.add_parser("test", help="intensive testing of apps")
    p.add_argument("app_dir")
    p.add_argument("--phase", default="full",
                   choices=["smoke", "perf", "install", "e2e", "full"])
    p.add_argument("--endpoint", default="/")
    p.add_argument("--n", type=int, default=50)
    p.add_argument("--concurrency", type=int, default=5)

    # New: smart router
    p = sub.add_parser("router", help="smart LLM router")
    p.add_argument("router_action", choices=["list", "stats", "cost", "rank", "test"])
    p.add_argument("--task", default="chat")
    p.add_argument("--cheap", action="store_true")
    p.add_argument("--prompt", default=None)

    # New: self-healing
    p = sub.add_parser("heal", help="self-healing — recover from failures")
    p.add_argument("heal_action", choices=["attempt", "log"])
    p.add_argument("error", nargs="?")
    p.add_argument("--context", default="")
    p.add_argument("--limit", type=int, default=20)

    # New: meta controller
    p = sub.add_parser("meta", help="meta controller — plan, skill manager, history")
    p.add_argument("meta_action", choices=["plan", "skills", "history"])
    p.add_argument("meta_args", nargs="*")
    p.add_argument("--run", action="store_true")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--query", default="")

    # AIOX
    p_aiox = sub.add_parser("aiox", help="AIOX squad management")
    p_aiox.add_argument("aiox_action", choices=["list", "run"])
    p_aiox.add_argument("workflow", nargs="?")

    # NemoClaw
    sub.add_parser("nemoclaw", help="NemoClaw sandbox status")

    # Security
    p_sec = sub.add_parser("security", help="Test NemoClaw security (scan text, check path, list patterns)")
    p_sec.add_argument("security_action", choices=["scan", "path", "patterns"])
    p_sec.add_argument("text", nargs="?")
    p_sec.add_argument("--path", default="")

    # Vision (multimodal)
    p_vision = sub.add_parser("vision", help="Vision API: describe image with text prompt")
    p_vision.add_argument("text", help="Question/prompt about the image")
    p_vision.add_argument("image_url", help="URL of the image")
    p_vision.add_argument("--model", default="google/diffusiongemma-26b-a4b-it",
                        choices=["google/diffusiongemma-26b-a4b-it",
                                "meta/llama-3.2-90b-vision-instruct",
                                "meta/llama-3.2-11b-vision-instruct",
                                "moonshotai/kimi-k3"])
    p_vision.add_argument("--no-thinking", action="store_true")

    # Skill auto-invoke
    p_auto = sub.add_parser("auto-invoke", help="Auto-detect which skill should run for an intent")
    p_auto.add_argument("intent", help="The intent/request to match")

    # Fallback
    p_fb = sub.add_parser("fallback", help="Setup auto-fallback chain (primary -> fallback)")
    p_fb.add_argument("--primary", default="deepseek-ai/deepseek-v4-pro-0813")
    p_fb.add_argument("--fallback", default="google/diffusiongemma-26b-a4b-it")


    args = parser.parse_args(argv)

    # Map remaining args
    if args.cmd == "memory":
        if args.action == "set" and len(args.args) >= 2:
            args.key, args.value = args.args[0], " ".join(args.args[1:])
        elif args.action == "get" and args.args:
            args.key = args.args[0]
        elif args.action == "search" and args.args:
            args.query = " ".join(args.args)
    elif args.cmd == "model":
        if args.action == "set" and len(args.args) >= 5:
            args.task, args.provider, args.model_id, args.base_url, args.cred_env = args.args[:5]
        elif args.action == "test" and args.args:
            args.task = args.args[0]
    elif args.cmd == "squad":
        if args.action in ("describe", "activate") and args.args:
            args.name = args.args[0]
        elif args.action == "run" and len(args.args) >= 2:
            args.name, args.prompt = args.args[0], " ".join(args.args[1:])
    elif args.cmd == "s":
        if args.action in ("add", "rm", "show") and args.args:
            args.key = args.args[0]
            if args.action == "add" and len(args.args) >= 2:
                args.expansion = " ".join(args.args[1:])
        elif args.action == "use" and args.args:
            args.key = args.args[0]
            args.rest = args.args[1:]
    elif args.cmd == "hermes":
        if args.action == "browser" and args.args:
            args.url = args.args[0]
        elif args.action == "exec" and args.args:
            args.code = " ".join(args.args)

    handlers = {
        "banner": cmd_banner,
        "status": cmd_status,
        "chat": cmd_chat,
        "ask": cmd_ask,
        "memory": cmd_memory,
        "model": cmd_model,
        "squad": cmd_squad,
        "s": cmd_shortcut,
        "hermes": cmd_hermes,
        "strategy": cmd_strategy,
        "serve": cmd_serve,
        "tool": cmd_tool,
        "tools": cmd_tools,
        "loop": cmd_loop,
        "mcp": cmd_mcp,
        "install": cmd_install,
        "app": cmd_app,
        "aiox": cmd_aiox,
        "nemoclaw": cmd_nemoclaw,
        "security": cmd_security,
        "vision": cmd_vision,
        "auto-invoke": cmd_auto_invoke,
        "fallback": cmd_fallback,
        "skill": cmd_skill,
        "research": cmd_research,
        "learn": cmd_learn,
        "test": cmd_test,
        "meta": cmd_meta,
        "heal": cmd_heal,
        "router": cmd_router,
    }
    alberto = _get_alberto()
    try:
        return handlers[args.cmd](args, alberto)
    finally:
        alberto.shutdown()


if __name__ == "__main__":
    sys.exit(main())