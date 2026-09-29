# Sprint Radar com Jev

Demo que carrega uma sprint do Azure DevOps (Feature → User Story → Task), calcula os
números da sprint em código e pede ao Jev um **julgamento tipado por task**: chance de
fechar até o fim da sprint, fator principal de risco, bloqueio externo e "entregue mas
não fechada". As 80 tasks abertas da Sprint06 são julgadas em ~5 s por menos de 1 centavo.

## Executar

Requer Python 3.11+ e [uv](https://docs.astral.sh/uv/).

```bash
cd sprint-radar
cp .env.example .env   # preencha AZURE_DEVOPS_PAT e a chave do Jev
uv sync --extra dev
uv run sprint-radar
```

Abra <http://localhost:8766>. `AZURE_DEVOPS_PAT` também pode vir do ambiente do processo,
que prevalece sobre o `.env`. O PAT precisa de leitura em *Work Items* e *Work*.

```dotenv
AZURE_DEVOPS_PAT=<seu-pat>
ADO_ORG=exemplo-org
ADO_PROJECT=Projeto Demo
ADO_TEAM=Speed
JEV_PROVIDER=typesafe
TYPESAFE_API_KEY=<sua-chave>
```

## Roteiro do demo (5 min)

1. A sprint atual já vem selecionada. O placar do topo é **aritmética, sem IA**:
   dias úteis restantes, horas restantes, capacidade restante e a razão carga/capacidade.
   A barra por pessoa mostra quem está acima da capacidade (o traço é a capacidade).
2. **▶ Analisar com Jev.** O cronômetro corre, as pílulas acendem conforme cada resposta
   chega por SSE e o contador de custo sobe em tempo real.
3. Aponte os achados que só o texto revela: task com PR mergeado mas ainda `Active`,
   task esperando chamado do DevOps, task de 20 h que começou hoje sem descrição, dono
   em day off com dezenas de horas restantes.
4. Clique numa task: os três medidores, a distribuição do fator de risco e, em
   *"O que foi enviado ao Jev"*, o `state` e as perguntas exatas. Não é caixa-preta.
5. Use *ordenar por risco*, *só em risco* e os filtros por raia e pessoa. O percentual
   nas linhas de US e Feature é o roll-up ponderado pelas horas restantes.

## Como funciona

| Quem | Faz |
|---|---|
| `ado.py` | REST do Azure DevOps: iterações, capacidade, days off, WIQL, batch de campos, últimos 3 comentários das tasks abertas |
| `workdays.py` | Dias úteis de segunda a sexta descontando feriados nacionais (fixos e móveis) |
| `model.py` | Hierarquia, raia herdada do pai, horas por task, capacidade e carga por pessoa, roll-up |
| `jev.py` | Monta o `state` por task, as 4 perguntas e valida a resposta |
| `app.py` | FastAPI: `/api/sprints`, `/api/sprint/{id}`, `/api/sprint/{id}/analyze` (SSE), `/api/sprint/{id}/task/{id}/state` |

A divisão importa: **toda aritmética é feita em código** e entra no `state` como fato
(`business_days_left`, `remaining_capacity_h`, `load_ratio`, `days_since_activated`).
O Jev só julga o que número nenhum captura: o que os comentários e a descrição dizem.

Perguntas por task, todas numa única requisição:

| Chave | Tipo | Responde |
|---|---|---|
| `will_close` | Noul | probabilidade de chegar a `Closed` até o fim da sprint |
| `risk_driver` | Choice | `on_track`, `owner_overloaded`, `blocked_external`, `dependency_open`, `not_started_large`, `scope_unclear`, `done_not_closed` |
| `blocked_external` | Noul | espera alguém de fora do time sem resolução registrada |
| `done_not_closed` | Noul | há evidência de entrega, mas estado/horas dizem o contrário |

Regras de contorno:

- Só tasks em `New`, `Active` ou `Review` vão ao Jev. `Removed`/`Dropped` ficam fora dos
  totais; User Story, Feature e Spike não somam horas (as das filhas já contam).
- Descrição e comentários entram limpos de HTML e truncados (2.500 e 1.500 caracteres).
  Cada pergunta começa com um aviso de que o texto é material auditado, não instrução.
- Resposta sem `answers`, com probabilidade fora de 0–1 ou distribuição que não soma 1 é
  rejeitada; a task aparece com erro em vez de um número inventado.
- Custo: a TypeSafe informa só tokens; o custo é estimado por `PRICES_PER_MTOK` e marcado
  como `estimated`. Saída não é cobrada.
- O snapshot do ADO é gravado em `cache/<iteration-id>.json`. Se o ADO cair durante a
  apresentação, a lista de sprints e os dados vêm do cache; `↻ ADO` força nova busca.
- `?today=YYYY-MM-DD` em `/api/sprint/{id}` simula outra data (útil para replay).

## Testes

```bash
uv run pytest
uv run ruff check .
```

Os testes cobrem calendário, cálculo de capacidade e carga, herança de raia, limpeza
de texto, roll-up, contrato do Jev e do ADO com HTTP simulado. Nenhum faz chamada real.

## Limites

- O roll-up de US/Feature é aritmético (média ponderada). Uma versão 2 pode pedir ao Jev
  um julgamento por US com os resultados das filhas e os critérios de aceite.
- Os limiares de cor (70 % / 40 %) são ilustrativos; calibre com sprints passadas.
- Comentários entram só os 3 mais recentes. Bloqueios registrados mais atrás e já
  resolvidos podem não aparecer.
