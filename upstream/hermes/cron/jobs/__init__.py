class AmbiguousJobReference(Exception): pass
def find_job(name): return None
def list_jobs(): return []

def claim_job_for_fire(name): return None
def release_job(name): pass

def create_job(*args, **kwargs): return None
def delete_job(name): return True
def update_job(name, **kwargs): return None

def get_job(name): return None

def mark_job_run(name): pass

def parse_schedule(expr): return expr

def pause_job(name): return True
def resume_job(name): return True

def remove_job(name): return True

def resolve_job_ref(ref): return None
