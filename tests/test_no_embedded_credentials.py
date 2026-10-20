"""Prevent regressions that reintroduce provider credentials into live tests."""
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
CREDENTIAL_TEST_FILES = (
    Path("tests/test_full_e2e_chat.py"),
    Path("tests/test_intensive.py"),
    Path("tests/test_v15_real.py"),
)


def test_live_test_files_do_not_embed_provider_credentials():
    token_patterns = (
        re.compile(r"nvapi-[A-Za-z0-9_-]{40,}"),
        re.compile(r"sk-(?:proj-|ant-api03-)?[A-Za-z0-9_-]{24,}"),
        re.compile(r"gh[pousr]_[A-Za-z0-9_]{30,}"),
        re.compile(r"AKIA[A-Z0-9]{16}"),
    )
    for relative_path in CREDENTIAL_TEST_FILES:
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        for pattern in token_patterns:
            assert pattern.search(source) is None, (
                f"credential-shaped literal found in {relative_path}; "
                "use environment variables for live credentials and synthetic fixtures for scanner tests"
            )
