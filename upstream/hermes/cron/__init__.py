"""Cron stub."""
def match(cron_expr, dt):
    """Basic cron matching."""
    parts = cron_expr.split()
    if len(parts) != 5:
        return False
    fields = [
        dt.minute, dt.hour, dt.day, dt.month, dt.weekday() + 1
    ]
    for f, v in zip(parts, fields):
        if f == "*":
            continue
        if "," in f:
            if v not in [int(x) for x in f.split(",")]:
                return False
        elif "-" in f:
            start, end = [int(x) for x in f.split("-")]
            if not (start <= v <= end):
                return False
        elif "/" in f:
            base, step = f.split("/")
            base = int(base) if base != "*" else 0
            if v % int(step) != 0:
                return False
        else:
            if int(f) != v:
                return False
    return True

def find_job(name): return None
def list_jobs(): return []
