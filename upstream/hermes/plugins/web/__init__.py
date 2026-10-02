"""Plugin: web search."""
def search(query, max_results=5):
    import urllib.request, urllib.parse, re
    encoded = urllib.parse.quote(query)
    url = f"https://html.duckduckgo.com/html/?q={encoded}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode("utf-8", errors="replace")
        results = re.findall(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>([^<]+)</a>', html)
        return [{"url": u, "title": t} for u, t in results[:max_results]]
    except Exception as e:
        return [{"error": str(e)}]
