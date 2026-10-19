"""Real-browser E2E coverage for the Alberto AI frontend + HTTP API contract.

The browser drives the production HTML/JS against a live local FastAPI server.
The test backend is deterministic, so these tests validate integration without
requiring a paid LLM key; the separately gated NVIDIA test validates live AI.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_ready(url: str, process: subprocess.Popen, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"E2E backend exited early with code {process.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except Exception as exc:
            last_error = exc
        time.sleep(0.2)
    raise AssertionError(f"E2E backend did not become ready: {last_error}")


@pytest.mark.e2e
def test_frontend_chat_memory_squad_navigation_and_responsive_layout():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    port = _free_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["ALBERTO_ENV"] = "development"
    env["ALBERTO_API_TOKEN"] = "e2e-test-token-with-32-characters"
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "tests" / "frontend_e2e_server.py"), "--port", str(port)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    errors = []
    try:
        base_url = f"http://127.0.0.1:{port}"
        _wait_ready(base_url + "/", process)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 960})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base_url, wait_until="domcontentloaded", timeout=20000)
            auth_dialog = page.locator('[aria-labelledby="alberto-auth-title"]')
            auth_dialog.wait_for(timeout=10000)
            page.locator("#alberto-auth-token").fill("e2e-test-token-with-32-characters")
            page.get_by_role("button", name="Entrar").click()
            auth_dialog.wait_for(state="detached", timeout=10000)
            page.locator("#status-text").filter(has_text="online").wait_for(timeout=10000)
            assert page.title().startswith("Alberto AI")
            assert page.locator("#status-text").inner_text() == "online"

            # Chat: click/submit traverses the real browser fetch + FastAPI SSE path.
            page.locator("#composer").fill("verificação E2E da interface")
            page.locator("#send-btn").click()
            reply = page.locator(".msg.assistant .msg-content").last
            reply.wait_for(state="visible", timeout=10000)
            page.wait_for_function(
                "() => [...document.querySelectorAll('.msg.assistant .msg-content')].some(el => el.textContent.includes('E2E backend reply'))",
                timeout=10000,
            )
            assert "E2E backend reply: verificação E2E da interface" in reply.inner_text()

            # Conversation ID is retained and reused by the frontend.
            assert page.evaluate("sessionStorage.getItem('alberto.conversationId')") == "e2e-conversation-1"
            page.locator("#composer").fill("segundo turno na mesma conversa")
            page.locator("#send-btn").click()
            page.wait_for_function(
                "() => [...document.querySelectorAll('.msg.assistant .msg-content')].some(el => el.textContent.includes('E2E backend reply: segundo turno'))",
                timeout=10000,
            )
            assert page.evaluate("sessionStorage.getItem('alberto.conversationId')") == "e2e-conversation-1"

            # Clear resets both visible transcript and backend conversation identity.
            page.locator("#btn-clear").click()
            assert page.locator("#chat-empty").is_visible()
            assert page.evaluate("sessionStorage.getItem('alberto.conversationId')") is None
            page.locator("#composer").fill("nova conversa depois de limpar")
            page.locator("#send-btn").click()
            page.wait_for_function(
                "() => [...document.querySelectorAll('.msg.assistant .msg-content')].some(el => el.textContent.includes('E2E backend reply: nova conversa'))",
                timeout=10000,
            )
            assert page.evaluate("sessionStorage.getItem('alberto.conversationId')") == "e2e-conversation-2"

            # Memory write is confirmed by the API and reloaded from backend state.
            page.get_by_role("button", name="Memória").click()
            page.locator("#memory-add-btn").click()
            page.locator("#modal-mem-key").fill("e2e.frontend")
            page.locator("#modal-mem-val").fill("persisted-through-real-http")
            page.locator("#modal-mem-tags").fill("e2e")
            page.get_by_role("button", name="salvar").click()
            page.locator(".memory-key", has_text="e2e.frontend").wait_for(timeout=10000)
            assert page.locator(".memory-value", has_text="persisted-through-real-http").count() == 1
            page.get_by_role("button", name="Apagar memória e2e.frontend").click()
            page.locator(".memory-key", has_text="e2e.frontend").wait_for(state="detached", timeout=10000)

            # Shortcut create/delete controls must persist through backend routes.
            page.get_by_role("button", name="Atalhos").click()
            page.locator("#shortcut-add-btn").click()
            page.locator("#modal-shortcut-key").fill("e2e-shortcut")
            page.locator("#modal-shortcut-expansion").fill("texto de teste")
            page.get_by_role("button", name="salvar").click()
            page.locator(".shortcut-key", has_text="e2e-shortcut").wait_for(timeout=10000)
            page.get_by_role("button", name="Apagar atalho e2e-shortcut").click()
            page.locator(".shortcut-key", has_text="e2e-shortcut").wait_for(state="detached", timeout=10000)

            # Tool catalogue is populated from the live backend endpoint.
            page.get_by_role("button", name="Tools").click()
            assert page.locator("#tools-grid .tool-card").count() > 0

            # Squad activation updates backend state, not merely a local success toast.
            page.get_by_role("button", name="Squads").click()
            page.locator(".squad-card").filter(has_text="engineering").get_by_role("button", name="ativar").click()
            page.locator("#squad-status .squad-active-name", has_text="engineering").wait_for(timeout=5000)
            with urllib.request.urlopen(base_url + "/api/status", timeout=3) as response:
                import json
                status = json.loads(response.read().decode("utf-8"))
            assert status["active_squad"] == "engineering"
            page.locator(".squad-card").filter(has_text="engineering").get_by_role("button", name="hibernar").click()
            page.wait_for_function("async () => (await (await fetch('/api/status')).json()).active_squad === null", timeout=10000)

            # Model configuration is reflected from the backend, not only local text.
            page.set_viewport_size({"width": 390, "height": 844})
            page.get_by_role("button", name="Config").click()
            assert page.locator('[data-view="settings"]').evaluate("(el) => el.classList.contains('active')")
            assert page.locator("#settings-add-model").is_visible()
            page.locator("#settings-add-model").click()
            page.locator("#modal-task").select_option("chat")
            page.locator("#modal-provider").fill("test-provider")
            page.locator("#modal-modelid").fill("e2e-chat-model")
            page.locator("#modal-baseurl").fill("https://example.invalid/v1")
            page.locator("#modal-credenv").fill("E2E_TEST_KEY")
            page.get_by_role("button", name="salvar").click()
            page.locator("#settings-models").get_by_text("test-provider/e2e-chat-model").wait_for(timeout=10000)
            assert page.locator("#m-chat").inner_text() == "test-provider/e2e-chat-model"
            assert not errors, f"Browser JavaScript errors: {errors}"
            browser.close()
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        if process.stdout:
            output = process.stdout.read()
            if process.returncode not in (0, -15, 143) and output:
                raise AssertionError(f"E2E backend failed unexpectedly:\n{output[-4000:]}")
