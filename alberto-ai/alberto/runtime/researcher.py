"""Autonomous knowledge research — when Alberto doesn't know something, it searches.

Multi-source:
- arXiv (papers)
- Wikipedia (encyclopedia)
- DuckDuckGo instant answer
- Local docs (skills/)
- Web fetch + extract

Workflow:
1. Receive query
2. Decide source(s) (based on query type)
3. Fetch + extract content
4. Synthesize summary
5. Optionally persist as memory or new skill
"""
from __future__ import annotations
import json
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional


class Researcher:
    """Searches the web, papers, and docs to answer unknown questions."""

    def __init__(self, sandbox=None):
        self.sandbox = sandbox
        self.cache_dir = Path.home() / ".local" / "share" / "alberto" / "research_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def search(self, query: str, *, sources: Optional[List[str]] = None,
               limit: int = 5) -> Dict[str, Any]:
        """Multi-source search. Returns aggregated results."""
        sources = sources or ["duckduckgo", "wikipedia", "arxiv", "local_skills"]
        results = {"query": query, "sources": {}}
        for src in sources:
            try:
                if src == "duckduckgo":
                    results["sources"][src] = self._search_duckduckgo(query, limit)
                elif src == "wikipedia":
                    results["sources"][src] = self._search_wikipedia(query, limit)
                elif src == "arxiv":
                    results["sources"][src] = self._search_arxiv(query, limit)
                elif src == "local_skills":
                    results["sources"][src] = self._search_local_skills(query, limit)
            except Exception as e:
                results["sources"][src] = {"ok": False, "error": str(e)}
        # Aggregate
        all_hits = []
        for src, r in results["sources"].items():
            if isinstance(r, dict) and r.get("ok"):
                for hit in r.get("hits", []):
                    hit["source"] = src
                    all_hits.append(hit)
        results["total_hits"] = len(all_hits)
        results["top_hits"] = sorted(all_hits, key=lambda h: h.get("score", 0), reverse=True)[:limit]
        return results

    def _search_duckduckgo(self, query: str, limit: int) -> Dict[str, Any]:
        """DuckDuckGo instant answer (no API key required)."""
        import urllib.request
        q = urllib.parse.quote(query)
        url = f"https://api.duckduckgo.com/?q={q}&format=json&no_html=1&skip_disambig=0"
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                data = json.loads(r.read())
            hits = []
            if data.get("AbstractText"):
                hits.append({"title": data.get("Heading", query), "text": data["AbstractText"],
                            "url": data.get("AbstractURL", ""), "score": 1.0})
            for rt in data.get("RelatedTopics", [])[:limit]:
                if isinstance(rt, dict) and rt.get("Text"):
                    hits.append({"title": rt.get("Text", "")[:80], "text": rt["Text"],
                                "url": rt.get("FirstURL", ""), "score": 0.7})
            return {"ok": True, "hits": hits[:limit]}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _search_wikipedia(self, query: str, limit: int) -> Dict[str, Any]:
        """Wikipedia REST API summary."""
        import urllib.request
        q = urllib.parse.quote(query.replace(" ", "_"))
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{q}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Alberto-AI/0.1"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
            hits = [{
                "title": data.get("title", query),
                "text": data.get("extract", ""),
                "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
                "score": 0.9,
            }]
            return {"ok": True, "hits": hits}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _search_arxiv(self, query: str, limit: int) -> Dict[str, Any]:
        """arXiv REST API."""
        import urllib.request
        q = urllib.parse.quote(query)
        url = f"http://export.arxiv.org/api/query?search_query=all:{q}&max_results={limit}"
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                xml = r.read().decode()
            # Parse XML
            import xml.etree.ElementTree as ET
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            root = ET.fromstring(xml)
            hits = []
            for entry in root.findall("atom:entry", ns)[:limit]:
                title = entry.findtext("atom:title", "", ns).strip()
                summary = entry.findtext("atom:summary", "", ns).strip()[:500]
                link = entry.findtext("atom:id", "", ns).strip()
                hits.append({"title": title, "text": summary, "url": link, "score": 0.8})
            return {"ok": True, "hits": hits}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _search_local_skills(self, query: str, limit: int) -> Dict[str, Any]:
        """Search SKILL.md files by keyword match."""
        from alberto.upstream_bridge import list_upstream_skills
        all_skills = list_upstream_skills()
        q_words = re.findall(r"\w+", query.lower())
        scored = []
        for s in all_skills:
            text = (s.get("name", "") + " " + s.get("description", "") + " " +
                    " ".join(s.get("tags", []))).lower()
            score = sum(1 for w in q_words if w in text)
            if score > 0:
                s2 = dict(s); s2["score"] = score / max(len(q_words), 1)
                scored.append(s2)
        scored.sort(key=lambda x: x["score"], reverse=True)
        hits = [{"title": s["name"], "text": s.get("description", ""),
                 "url": s.get("path", ""), "score": s["score"]} for s in scored[:limit]]
        return {"ok": True, "hits": hits}

    def study(self, target: str) -> Dict[str, Any]:
        """Study a system/topic deeply. Multi-source aggregation + synthesis prompt."""
        results = self.search(target, limit=10)
        # Build synthesis prompt
        lines = [f"# Research: {target}\n"]
        for src, r in results["sources"].items():
            if r.get("ok"):
                lines.append(f"## {src}\n")
                for hit in r.get("hits", [])[:3]:
                    lines.append(f"### {hit['title']}")
                    lines.append(hit.get("text", "")[:300])
                    if hit.get("url"):
                        lines.append(f"Source: {hit['url']}")
                    lines.append("")
        synthesis = "\n".join(lines)
        # Cache
        cache_file = self.cache_dir / f"{re.sub(r'[^a-z0-9]+', '_', target.lower())}.md"
        cache_file.write_text(synthesis, encoding="utf-8")
        return {
            "ok": True,
            "query": target,
            "sources_used": list(results["sources"].keys()),
            "total_hits": results["total_hits"],
            "cached_at": str(cache_file),
            "synthesis_prompt": synthesis[:8000],
        }

    def replicate(self, target: str) -> Dict[str, Any]:
        """Analyze a system to understand it deeply enough to replicate.

        Workflow:
        1. search() for documentation
        2. study() for deep analysis
        3. Return structured plan (architecture, components, dependencies)
        """
        study_result = self.study(target)
        if not study_result.get("ok"):
            return study_result
        return {
            "ok": True,
            "target": target,
            "plan": {
                "research": study_result,
                "next_steps": [
                    f"Read sources: {[h['url'] for h in study_result.get('synthesis_prompt', '').split('Source: ')[1:5]]}",
                    "Identify core components",
                    "Map dependencies",
                    "Decide implementation approach",
                    "Build minimal viable replication",
                ],
            },
        }


def main(argv: List[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="alberto research")
    sub = p.add_subparsers(dest="cmd", required=True)
    p_s = sub.add_parser("search")
    p_s.add_argument("query")
    p_s.add_argument("--sources", default="duckduckgo,wikipedia,arxiv,local_skills")
    p_s.add_argument("--limit", type=int, default=5)
    p_st = sub.add_parser("study")
    p_st.add_argument("target")
    p_r = sub.add_parser("replicate")
    p_r.add_argument("target")
    args = p.parse_args(argv)
    r = Researcher()
    if args.cmd == "search":
        result = r.search(args.query, sources=args.sources.split(","), limit=args.limit)
        print(json.dumps(result, indent=2, ensure_ascii=False)[:5000])
    elif args.cmd == "study":
        result = r.study(args.target)
        print(f"✓ Studied '{args.target}'")
        print(f"  sources: {result.get('sources_used')}")
        print(f"  total hits: {result.get('total_hits')}")
        print(f"  cached: {result.get('cached_at')}")
    elif args.cmd == "replicate":
        result = r.replicate(args.target)
        print(f"✓ Replication plan for '{args.target}'")
        print(json.dumps(result.get("plan", {}), indent=2)[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
