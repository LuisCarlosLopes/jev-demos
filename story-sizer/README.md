# Story Sizer com Jev

Demo que lê as User Stories de uma sprint do Azure DevOps, encontra as que estão sem
`SR_TAMANHO` (t-shirt size: PP, P, M, G, GG) e pede ao Jev uma sugestão de tamanho a
partir do título, descrição e critérios de aceite. A interface mostra a **distribuição de
probabilidade** de cada story, não só a letra vencedora: é o que diferencia um modelo de
decisão de um chat pedindo "qual o tamanho?".

Na Sprint06 do time Speed: 31 stories classificadas em 3,4 s, 73 mil tokens, US$ 0,003.

## Executar

Requer Python 3.11+ e [uv](https://docs.astral.sh/uv/).

```bash
cd story-sizer
cp .env.example .env    # preencha AZURE_DEVOPS_PAT e TYPESAFE_API_KEY
uv sync --extra dev
uv run story-sizer-web  # http://127.0.0.1:8765
```

O PAT precisa do escopo *Work Items (Read)*. Para o botão "Aplicar no ADO" funcionar,
use *Read & Write* e defina `ALLOW_WRITE=true`; por padrão a escrita fica desligada e
o botão só explica isso.

CLI, sem interface:

```bash
uv run story-sizer sprints                                  # iterações do time
uv run story-sizer stories --sprint "IA - Senior\Speed\Sprint06"
uv run story-sizer size --sprint "IA - Senior\Speed\Sprint06" --limit 3 --json reports/s6.json
uv run story-sizer validate --sprint "IA - Senior\Speed\Sprint05" --json reports/val.json
```

## Como o Jev é usado

Uma requisição por story, todas em paralelo (`JEV_MAX_CONCURRENCY`), cada uma com
seis perguntas tipadas sobre o mesmo `state`:

| Pergunta | Tipo | Para quê |
|---|---|---|
| `size` | Choice (PP/P/M/G/GG) | A sugestão. Cada opção tem critério, esforço e exemplos em `policy.yaml`. |
| `scope`, `complexity`, `uncertainty` | Score 0–3 | Os "porquês": aparecem como medidores no card. |
| `vague_criteria`, `should_split` | Noul | Alertas: critérios de aceite vagos, story que deveria ser quebrada. |

A decisão é feita em código a partir da `confidence` do Choice (`scoring.py`):

| Faixa | Confiança | Na interface |
|---|---|---|
| firme | ≥ 0,70 | badge verde, sugestão direta |
| com alternativa | 0,45–0,70 | badge âmbar, mostra a 2ª opção |
| precisa de humano | < 0,45 | badge cinza, distribuição espalhada |

O esforço em dias de cada story é a média ponderada pela distribuição (não o ponto
médio do vencedor), o que estabiliza o somatório da sprint. O Jev não gera texto: tudo
que aparece na tela vem das probabilidades e da rubrica local.

## Preparação do texto

- HTML do ADO vira texto preservando marcadores de lista (`normalize.py`).
- Stream vem do padrão de título `[Sprint N - Stream X]` ou da tag.
- Orçamento de `max_state_chars` (60k, bem abaixo dos 32k tokens de state do modelo):
  a descrição é truncada primeiro; critérios de aceite vão sempre inteiros. Cards
  truncados recebem aviso.
- O conteúdo da story é tratado como dado não confiável na instrução de cada pergunta.

## Modo validação

`story-sizer validate` pega as stories **fechadas** de uma sprint, soma `CompletedWork`
das tasks filhas, converte em tamanho "real" pela tabela `validation` da policy e compara
com a sugestão do Jev. Imprime acerto exato, acerto dentro de ±1 tamanho e a matriz de
confusão. É a forma de calibrar os critérios sem rotular stories à mão.

A referência é limpa antes de comparar: stories fechadas sem horas ou com menos de
metade da estimativa apontada (`min_completed_ratio`) saem da amostra. O alvo padrão é
a **estimativa das tasks** (`--target estimativa`), que é o julgamento do time ao
planejar — o que uma sugestão a partir do texto tenta reproduzir; `--target realizado`
compara com `CompletedWork`. A saída inclui sempre o baseline trivial ("sempre P"),
porque sem ele um acerto de 40% parece bom quando não é.

### O que a calibração mostrou (Sprints 03–05, 26 stories limpas)

Foram testadas quatro formulações da pergunta de tamanho, âncoras com stories reais do
time nos critérios, e cortes ajustados sobre o valor esperado da distribuição com
validação leave-one-out. Resumo:

| Abordagem | Exato | ±1 | Spearman vs horas |
|---|---|---|---|
| Choice com letras PP–GG (v1/v2) | 27% | 65% | 0,22 |
| **Choice com opções em horas (adotada)** | 23–39% | 73% | 0,31 |
| Score ordinal 0–4 | 15% | 54% | 0,27 |
| Nouls cumulativos (≤4 h? ≤16 h? …) | 12% | 31% | 0,42 |
| Âncoras com stories reais do time | sem efeito | | |
| Cortes calibrados (leave-one-out) | 30–39% | 83–91% | |
| **Baseline "sempre P"** | **39%** | **100%** | |

Conclusão honesta: **o texto das stories deste time não determina o esforço.** A
estimativa do próprio time correlaciona só 0,62 com o realizado; o Jev, lendo apenas
título, descrição e critérios, chega a 0,3–0,4 e não supera uma constante em acerto.
Stories de 2–3 h aqui têm cinco tasks e critérios de aceite longos; nenhum leitor
diria "duas horas" só pelo texto. Calibrar cortes não cria um sinal que o texto não
tem. O que ficou no produto é o que ajudou de forma mensurável: opções nomeadas em
horas (o Choice com letras colapsava no meio da escala), referência limpa e baseline
visível. A sugestão de tamanho deve ser lida como **triagem com incerteza explícita**,
não como estimativa; o card mostra ao lado a estimativa das tasks do time quando existe.

## Ajustes

Tudo que define a classificação está em `policy.yaml`: critérios e exemplos de cada
tamanho, dias por tamanho, faixas de confiança, perguntas de apoio e limiares dos
alertas. Alterar critérios muda as respostas; alterar faixas e dias só muda a leitura.

## Limites

- Só texto. Anexos e imagens da story não entram.
- Sem base rotulada no Speed (5 stories com `SR_TAMANHO` no projeto inteiro), a
  acurácia vem só do modo validação, que depende da qualidade dos apontamentos.
- `jev-1.13.0` está fixado no `.env.example`; `jev-latest` pode mudar e quebrar
  comparabilidade entre sprints.

## Testes

```bash
uv run pytest
uv run ruff check .
```
