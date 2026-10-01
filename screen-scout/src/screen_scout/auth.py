"""Telas com login: você entra numa janela do navegador e o demo guarda a sessão para reusar.

O Screen Scout nunca digita credenciais. Ele abre o endereço numa janela visível, espera você
concluir o login (inclusive MFA) e, quando a tela pedida carrega, salva o `storage_state` do
Playwright (cookies e localStorage) em `.auth/<host>.json`. As explorações e os testes gerados
desse host passam a usar o arquivo.

O arquivo equivale a uma sessão aberta: fica fora do Git, não vai para o Jev nem para lugar
nenhum, e pode ser apagado pela interface ("esquecer sessão").
"""

import asyncio
import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
AUTH_DIR = ROOT / ".auth"

# Etapas de login/SSO: enquanto a URL passa por elas, a sessão ainda não está pronta.
AUTH_STEP = re.compile(r"idpresponse|/oauth2?/|/login|/signin|/sso|/auth/|/saml", re.I)

READY = """
() => {
  const visible = (el) => el.checkVisibility ? el.checkVisibility() : el.offsetParent !== null;
  const busy = [...document.querySelectorAll("[aria-busy=true], [role=progressbar]")]
    .some(visible);
  const interactive = [...document.querySelectorAll(
    "input:not([type=hidden]), select, textarea, button, a[href], [role=button]"
  )].filter(visible).length;
  return interactive > 0 && !busy;
}
"""


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def redirected_to(requested: str, final: str) -> str | None:
    """Host para onde a tela foi levada, se diferente do pedido (tipicamente o login)."""
    target, now = host_of(requested), host_of(final)
    return now if now and target and now != target else None


def session_file(url: str) -> Path:
    return AUTH_DIR / f"{re.sub(r'[^a-z0-9.-]', '_', host_of(url)) or 'local'}.json"


def storage_state_for(url: str) -> str | None:
    path = session_file(url)
    return str(path) if path.is_file() else None


def session_info(url: str) -> dict:
    host = host_of(url)
    path = session_file(url)
    if not path.is_file():
        return {"host": host, "exists": False}
    try:
        cookies = json.loads(path.read_text(encoding="utf-8")).get("cookies", [])
    except (OSError, ValueError):
        return {"host": host, "exists": False}
    mine = [c for c in cookies if host.endswith(str(c.get("domain", "")).lstrip("."))]
    expiring = [c["expires"] for c in mine if isinstance(c.get("expires"), int | float)
                and c["expires"] > 0]
    expires = min(expiring) if expiring else None
    return {
        "host": host,
        "exists": True,
        "saved_at": datetime.fromtimestamp(path.stat().st_mtime).strftime("%d/%m %H:%M"),
        "cookies": len(mine),
        # Cookies de sessão (sem data) valem até o servidor decidir; aí só a próxima exploração diz.
        "expires_at": datetime.fromtimestamp(expires).strftime("%d/%m %H:%M") if expires else None,
        "expired": bool(expires and expires < time.time()),
    }


def forget(url: str) -> bool:
    path = session_file(url)
    if path.is_file():
        path.unlink()
        return True
    return False


async def login(playwright, url: str, channel: str = "", timeout_s: int = 300) -> dict:
    """Abre uma janela, espera o login terminar na tela pedida e salva a sessão."""
    target = host_of(url)
    wanted = urlparse(url).path.rstrip("/")
    options: dict = {"headless": False}
    if channel in {"msedge", "chrome"}:
        options["channel"] = channel
    browser = await playwright.chromium.launch(**options)
    saved = False
    try:
        context = await browser.new_context(locale="pt-BR", no_viewport=True)
        page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline and browser.is_connected() and not page.is_closed():
            current = page.url
            if host_of(current) == target and not AUTH_STEP.search(current):
                try:
                    ready = await page.evaluate(READY)
                except Exception:  # noqa: BLE001 - a página navegou no meio da leitura
                    ready = False
                if ready:
                    AUTH_DIR.mkdir(exist_ok=True)
                    await context.storage_state(path=str(session_file(url)))
                    saved = True
                    if urlparse(current).path.rstrip("/") == wanted:
                        break
            await asyncio.sleep(0.7)
    finally:
        if browser.is_connected():
            await browser.close()
    if not saved:
        raise RuntimeError(
            "O login não chegou à tela pedida a tempo (ou a janela foi fechada antes). "
            "Tente de novo e espere a tela carregar."
        )
    return session_info(url)
