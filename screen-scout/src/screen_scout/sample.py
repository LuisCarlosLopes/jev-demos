"""Aplicação-alvo de exemplo (Aurora RH, fictícia) servida em /alvo.

Um cadastro de colaborador com validações reais e dois defeitos plantados em
sample/colaborador.js. As demais telas existem só para os links e o "Cancelar" irem a algum
lugar. Os dados ficam em memória.
"""

import asyncio
import html
from collections import deque
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse

SAMPLE = Path(__file__).resolve().parents[2] / "sample"

router = APIRouter(prefix="/alvo")
_registros: deque[dict] = deque(maxlen=200)
_contador = {"proximo": 1001}


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} · Aurora RH</title><link rel="stylesheet" href="/alvo/style.css">
</head><body>
<header class="topbar"><strong class="logo">Aurora RH</strong>
<nav aria-label="Principal"><a href="/alvo/">Início</a>
<a href="/alvo/colaboradores">Colaboradores</a><a href="/alvo/folha">Folha de pagamento</a></nav>
<a class="sair" href="/alvo/sair">Sair</a></header>
<main>{body}</main></body></html>""")


@router.get("/colaborador")
async def colaborador():
    return FileResponse(SAMPLE / "colaborador.html")


@router.get("/fornecedor")
async def fornecedor():
    # Cadastro em abas (ARIA tabs): campos obrigatórios fora da aba inicial.
    return FileResponse(SAMPLE / "fornecedor.html")


@router.get("/colaborador.js")
async def script():
    return FileResponse(SAMPLE / "colaborador.js", media_type="text/javascript")


@router.get("/style.css")
async def style():
    return FileResponse(SAMPLE / "style.css", media_type="text/css")


@router.get("/")
async def inicio():
    return _page("Início", "<h1>Início</h1><p>Bem-vindo ao Aurora RH (sistema fictício).</p>"
                 '<p><a href="/alvo/colaborador">Cadastrar colaborador</a></p>')


@router.get("/colaboradores")
async def colaboradores():
    linhas = "".join(
        f"<tr><td>{html.escape(r['matricula'])}</td><td>{html.escape(r.get('nome', ''))}</td>"
        f"<td>{html.escape(r.get('cargo', ''))}</td></tr>"
        for r in reversed(_registros)
    ) or '<tr><td colspan="3">Nenhum colaborador cadastrado.</td></tr>'
    return _page("Colaboradores", '<h1>Colaboradores</h1><p><a href="/alvo/colaborador">'
                 "Novo colaborador</a></p><table><thead><tr><th>Matrícula</th><th>Nome</th>"
                 f"<th>Cargo</th></tr></thead><tbody>{linhas}</tbody></table>")


@router.get("/folha")
async def folha():
    return _page("Folha de pagamento", "<h1>Folha de pagamento</h1><p>Em construção.</p>")


@router.get("/sair")
async def sair():
    return _page("Sessão encerrada", "<h1>Sessão encerrada</h1>"
                 '<p><a href="/alvo/colaborador">Entrar novamente</a></p>')


@router.post("/api/colaboradores", status_code=201)
async def salvar(request: Request):
    dados = await request.json()
    await asyncio.sleep(0.12)  # simula a gravação
    matricula = f"{_contador['proximo']:06d}"
    _contador["proximo"] += 1
    _registros.append({**{k: str(v)[:120] for k, v in dados.items()}, "matricula": matricula})
    return {"matricula": matricula}


@router.post("/api/aprovacoes", status_code=202)
async def aprovacao():
    return {"status": "enviado"}
