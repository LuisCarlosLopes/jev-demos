# Screen Scout: Jev + Playwright

Explora uma tela, encontra defeitos e gera o plano e os testes em poucos segundos, sem LLM no
laço. O Playwright lê a tela e executa as sondagens, o Jev toma as decisões semânticas e o código
monta o plano e os testes a partir de um catálogo.

Na tela de exemplo (um cadastro de colaborador com dois defeitos plantados), uma exploração
leva de 6,5 a 14 s, faz 27 sondagens e 89 decisões do Jev em 2 requisições, custa
US$ 0,0013 e entrega 31 cenários e 28 testes. Rodando os testes, 25 passam e 3 falham,
exatamente nos defeitos plantados.

## A ideia, passo a passo

Explorar uma tela para testá-la é, na maior parte, **decidir**: o que é cada campo, qual dado
ele espera, se é obrigatório, o que cada botão faz, se é seguro clicar, e se a tela aceitou ou
recusou o que foi digitado. Gerar texto é a menor parte. No fluxo com LLM (o plan → generate →
heal do `playwright-cli`), um agente relê o snapshot da tela a cada ação e escreve cada passo,
um cenário por vez. Aqui cada decisão é uma pergunta tipada ao Jev, e todas as perguntas vão
juntas.

| # | Etapa | Quem faz | O que acontece |
|---|---|---|---|
| 1 | Captura | Playwright | Inventário dos campos e ações num `evaluate` só. Cada localizador (`get_by_label`, `get_by_role`…) é verificado: precisa resolver exatamente o elemento capturado. |
| 2 | Classificação | **Jev**, 1 requisição | Tipo de dado de cada campo (Choice com 17 tipos), obrigatoriedade (Noul), papel de cada ação (Choice com 11 papéis), risco de clicar (Noul), tipo de tela (Choice), criticidade (Score) e dados pessoais (Noul). O que o HTML já responde (`type=email`, `required`) não vira pergunta. |
| 3 | Sondagens | Playwright, 6 em paralelo | Uma página nova por sondagem. Preenche a massa válida trocando **um valor por vez** (vazio, CPF com dígito errado, data inexistente, valor negativo…), aciona a tela e registra o que mudou: texto novo, campos marcados como inválidos, URL, diálogos, erros HTTP. |
| 4 | Oráculo | **Jev**, 1 requisição | Para cada sondagem: a tela aceitou, recusou, deu erro ou não respondeu (Choice)? A mensagem aponta para qual campo (Choice)? |
| 5 | Veredicto | código | Esperado × observado vira ✅ conforme, ❌ divergência, ⚠️ revisar (confiança baixa ou recusa por outro campo) ou 🔎 observado (sem regra universal: registra como está). |
| 6 | Geração | código | Plano em Markdown no formato do planner do Playwright, testes em Python (pytest-playwright) e TypeScript (`@playwright/test`). A massa vem do catálogo, as asserções vêm do que a tela mostrou e os localizadores são os verificados. |

O Jev não escreve nada. Ele escolhe peças de um catálogo (`catalog.py`): cada tipo de dado já
traz valores válidos e inválidos e o nome do cenário. Por isso o mesmo conjunto de decisões
sempre produz o mesmo plano e o mesmo código, e o custo não depende do tamanho do texto gerado.

A exploração também aprende as convenções da tela. Se nas outras recusas ela marcou o campo com
`aria-invalid` e mostrou "Revise o campo destacado.", o teste de uma divergência exige isso, e
passa a passar quando o defeito for corrigido.

## Executar

Requer Python 3.11+, [uv](https://docs.astral.sh/uv/) e o Chromium do Playwright 1.59
(`uv run playwright install chromium`, se ainda não houver). Sem o Chromium, use
`SCOUT_BROWSER_CHANNEL=msedge` ou `chrome` para usar o navegador instalado.

```bash
cd screen-scout
uv sync --extra dev
cp .env.example .env              # preencha TYPESAFE_API_KEY (ou OPENROUTER_API_KEY)
uv run screen-scout               # http://127.0.0.1:8785
```

Para reaproveitar a chave de outro demo sem copiá-la:

```bash
uv run screen-scout --env-file ../skill-validator/.env
```

Sem chave, com um Jev **simulado** (heurística por palavras-chave; a tela avisa):

```bash
uv run screen-scout --fake --port 8786
```

A interface já vem com a tela de exemplo (`/alvo/colaborador`, "Aurora RH", fictícia). Clique em
**Explorar tela** e depois em **Rodar testes Python** na aba Código.

### Linha de comando

```bash
uv run screen-scout-cli exemplo --run                    # tela embutida, roda os testes gerados
uv run screen-scout-cli http://localhost:4200/cadastro   # sua tela local
uv run screen-scout-cli https://homolog.exemplo/cadastro --no-submit
```

Os arquivos vão para `generated/<tela>/`: `plano.md`, `test_<tela>.py`, `<tela>.spec.ts`,
`exploracao.json` (todas as decisões e observações) e `tela.jpg`.

## Telas com login

Se a tela redireciona para outro endereço (por exemplo `login.microsoftonline.com`), a
exploração para com um aviso: ela nunca explora nem digita num sistema que não foi o pedido.
Para entrar:

1. Na interface, com o endereço preenchido, clique em **Entrar…** (na CLI: `--login`).
2. Uma janela do navegador abre nesta máquina. **Você** faz o login nela, com MFA se houver. O
   demo não digita credenciais.
3. Quando a tela pedida carrega, a sessão (cookies e localStorage) é salva em
   `.auth/<host>.json` e a janela fecha.
4. **Explorar tela** passa a usar essa sessão, e **Rodar testes** também, via
   `SCREEN_SCOUT_STORAGE_STATE`: os testes gerados para uma tela com login leem essa variável.

O arquivo equivale a uma sessão aberta: fica fora do Git, não é enviado a lugar nenhum e sai com
"esquecer sessão". Se a sessão expirar, a exploração volta a parar no login. Se a política de
acesso da empresa recusar o Chromium do Playwright, use `SCOUT_BROWSER_CHANNEL=msedge`.

```bash
uv run screen-scout-cli https://app.exemplo.com.br/cadastro --login --env-file ../skill-validator/.env
```

## Segurança da exploração

- **Salvar o formulário só em endereço local** (`localhost`, `127.0.0.1`, `*.test`) por padrão.
  Fora disso, as sondagens que gravam ficam desligadas e o plano marca esses cenários como não
  executados. Ligue (`--submit` ou a caixa na tela) só em ambiente de teste.
- **Portão de risco em três camadas.** Uma ação não é clicada se: o papel escolhido pelo Jev é
  de risco (excluir, enviar, sair, exportar); o Noul de risco passa de 35%; o rótulo tem uma
  palavra de risco (`RISKY_WORDS`); ou é link externo ou abre outra aba. Essas ações viram
  cenários manuais no plano. Um `button type=reset` nativo ignora a lista de palavras.
- **O botão de salvar é escolhido com cuidado.** Se o envio nativo do formulário foi barrado
  como risco, outro botão ("Salvar rascunho") não o substitui, porque rascunhos costumam pular a
  validação. Um "salvar" com palavra de risco ("Pagar selecionados") também é barrado.
- **O texto da tela é dado, não instrução**: toda pergunta ao Jev diz isso, e a interface escapa
  tudo o que vem da página.
- **O que sai da máquina**: rótulos, textos visíveis e mensagens da tela, e a massa sintética,
  vão para a API do Jev. Não aponte o demo para telas com dados reais.

## Medições (30/09/2026, `jev-latest` → `jev-1.13.0`, Windows, 8 núcleos)

Tela de exemplo, servidor e navegador já abertos:

| Etapa | Tempo |
|---|---:|
| Captura (inventário, 22 localizadores verificados, screenshot) | 0,5–1,0 s |
| Classificação: 44 perguntas numa requisição | 0,36–0,78 s |
| 27 sondagens, 6 páginas em paralelo | 5–9 s |
| Oráculo: 45 perguntas numa requisição | 0,37–0,41 s |
| Plano, Python e TypeScript | ~25 ms |
| **Total** | **6,5–14 s** |

As duas requisições ao Jev somam ~31,7 mil tokens de entrada (US$ 0,0013). Uma segunda
exploração da mesma tela reaproveita a classificação do cache (custo zero nessa etapa).

- **Todas as decisões corretas** na tela de exemplo: 9/9 tipos, 12/12 obrigatoriedades,
  10/10 papéis, as 3 ações de risco barradas e 23/23 veredictos do oráculo, com o campo certo.
- **Testes gerados**: 25 passam e 3 falham (CPF com dígito errado, CPF com dígitos repetidos,
  salário negativo). A suíte leva ~35 s nesta máquina, porque os testes que falham esperam o
  timeout de 5 s do `expect`. O `.spec.ts` rodou no `playwright test` real (Edge instalado) com
  o mesmo resultado.

## Assertividade: Jev × heurística por palavras-chave

`scripts/eval_decisions.py` captura telas com rótulos difíceis para palavra-chave ("Documento"
no lugar de CNPJ, "Endereço para envio das notas fiscais" que é um e-mail, "Inativar
fornecedor", "Pagar selecionados") e mensagens reais de ERP ("Não foi possível gravar: documento
já cadastrado"), e compara com um gabarito. A heurística é o próprio modo `--fake`.

| Decisão | Desenvolvimento: Jev | Heurística | Validação: Jev | Heurística |
|---|---:|---:|---:|---:|
| Tipo de dado | 21/21 | 13/21 | 9/9 | 6/9 |
| Obrigatoriedade | 26/26 | 26/26 | 14/14 | 14/14 |
| Papel da ação | 27/27 | 23/27 | 11/11 | 9/11 |
| Portão de risco | 24/24 | 22/24 | 9/9 | 9/9 |
| Tipo de tela | 4/4 | 0/4 | 2/2 | 1/2 |
| Oráculo: desfecho | 16/16 | 10/16 | 6/6 | 2/6 |
| Oráculo: campo apontado | 15/15 | 10/15 | 6/6 | 3/6 |

Como ler:

- **Desenvolvimento** (4 telas, 16 casos) foi usado para ajustar as perguntas. A primeira rodada
  deu 20/21, 25/26 e 14/24 no portão de risco, e três ajustes chegaram ao 100%:
  1. O contexto da tela deixou de juntar rótulos vizinhos numa linha. Com "Colaborador *
     Matrícula", o Jev dava "Matrícula" como obrigatória com 97%.
  2. A pergunta de risco passou a dizer que ir para outra tela não é efeito. Links de navegação
     caíram de 40–56% para 8–14%.
  3. A obrigatoriedade passou a ser perguntada pela marca no rótulo, não pela importância do
     dado.
- **Validação** (2 telas, 6 casos) teve o gabarito escrito antes de rodar o Jev, sem ajuste
  depois. O Jev acertou 57/57 e a heurística 44/57. É uma amostra pequena: serve para mostrar
  que os ajustes não decoraram as telas de desenvolvimento, não para prometer 100%.
- **Onde a heurística empata**: obrigatoriedade. Um "termina com `*` ou diz obrigatório" resolve
  quando a tela segue a convenção. O Jev ganha onde o sentido está no texto: tipo de dado,
  papel da ação e, principalmente, no oráculo, que precisa entender "não foi possível gravar" e
  "sessão expirada".
- **O portão de risco precisa das três camadas.** O Noul sozinho dá 33% para "Encerrar conta"
  (quem barra é o papel "excluir") e 14% para um link externo (quem barra é a regra
  determinística). As ações seguras ficam em 8–17% e as de risco em 53–76%.

O detalhe, com cada erro e o risco estimado de cada ação, fica em
[evals/resultado.md](evals/resultado.md). Rode de novo com:

```bash
uv run python scripts/eval_decisions.py --env-file ../skill-validator/.env
```

## Velocidade

- **Duas idas ao Jev por tela.** Dezenas de perguntas por requisição, avaliadas em paralelo.
  Com 44 perguntas, a classificação volta em 0,3–0,8 s.
- **Telas grandes cabem no limite do Jev** (64k tokens por requisição, ~3 caracteres de JSON por
  token). Elementos sem localizador único, como os 60 botões "copiar" repetidos numa grade de
  cards, não viram pergunta: não seriam sondados nem testados. Se ainda passar de ~80 mil
  caracteres, as perguntas se dividem em requisições paralelas com o mesmo estado.
- **O navegador é o gargalo, e por isso roda em paralelo**: 6 páginas, cada uma num contexto
  reaproveitado. A página nova zera o DOM e o JavaScript; o contexto mantém o cache HTTP e os
  cookies, o que pesa numa SPA de vários MB.
- **Stack trace do Playwright para Python.** A cada chamada, a API assíncrona monta um
  `inspect.stack()`, com um `os.stat` por frame. No Windows isso era cerca de 60% da CPU das sondagens.
  O demo pré-calcula esse stack por tarefa (`cache_call_stack`, o mesmo atalho que a API síncrona
  do Playwright usa) e a CPU caiu de ~7,4 s para ~2,7 s em 27 sondagens. Os testes gerados não
  usam esse atalho: continuam código Playwright idiomático.
- **Estabilização sem espera fixa**: um script injetado marca a última mutação do DOM e as
  requisições pendentes; a sondagem segue quando a tela fica 120 ms quieta.
- **Navegador e conexão aquecidos**: o `Engine` mantém um loop asyncio próprio com o Chromium e
  o cliente HTTP abertos entre explorações.

## Limites

- **Uma tela por vez.** Não segue fluxos de várias etapas, abas que carregam campos novos nem
  wizards. Não faz login: para telas autenticadas, falta passar um `storage_state` do Playwright.
- **O catálogo limita a criatividade.** Os casos são os do catálogo (formato, obrigatoriedade,
  limites, ações). Regras entre campos ("fim depois do início"), permissões e regras de negócio
  não aparecem. Um LLM pode entrar só nos casos marcados como "revisar": o plano segue o formato
  do planner do Playwright justamente para o generator/healer continuar a partir dele.
- **Um fator por vez** pressupõe que a massa válida é aceita. Se o caminho feliz for recusado,
  as recusas das outras sondagens viram "revisar".
- **Componentes customizados** (datepicker, máscara que só aceita teclado, combos com busca)
  podem precisar de ajuste no `fill`. O demo usa o `fill` do Playwright, como os testes gerados.
- **Elementos repetidos** (um botão "copiar" por card) ficam fora: sem localizador único não há
  teste estável. Rótulos com contador ("Skill103", "Filtros (3)") viram localizador sem o número
  quando isso ainda identifica um elemento só.
- **Telas de pesquisa e painéis** exploram pouco: sem uma ação de salvar, sobram limites, "limpar",
  navegação e acessibilidade. As sondagens são pensadas para formulários.
- **"Limpar" vale para o próprio grupo**: só se cobra o valor inicial dos campos do mesmo
  formulário, seção ou barra lateral da ação.
- **Os limiares** (confiança 60%, obrigatório 50%, risco 35%) foram escolhidos com os dados
  acima. Calibre com telas do seu produto.

## Estrutura

| Arquivo | Papel |
|---|---|
| `src/screen_scout/capture.py` | Inventário, localizadores verificados, estabilização, contexto da tela |
| `src/screen_scout/catalog.py` | Tipos de dado (massa válida e inválida), papéis, desfechos, palavras de risco |
| `src/screen_scout/decisions.py` | Perguntas ao Jev (classificação e oráculo) e validação das respostas |
| `src/screen_scout/profile.py` | Fatos do DOM + decisões + limiares; portão de risco; escolha do "salvar" |
| `src/screen_scout/probes.py` | Plano de sondagens, execução em paralelo, observação |
| `src/screen_scout/plan.py` | Veredictos, convenções aprendidas, casos de teste, plano em Markdown |
| `src/screen_scout/codegen.py` | Emissores Python e TypeScript |
| `src/screen_scout/pipeline.py` | Orquestração, `Engine` (loop próprio com navegador aquecido), progresso |
| `src/screen_scout/app.py` · `cli.py` · `runner.py` | Interface web, linha de comando, execução dos testes gerados |
| `src/screen_scout/sample.py` · `sample/` | Tela-alvo de exemplo com os defeitos plantados |
| `evals/` · `scripts/eval_decisions.py` | Telas de avaliação, gabarito e resultado |

## Testes

```bash
uv run pytest
uv run ruff check .
```

Os testes usam o Jev simulado, sem chave. Um deles abre o Chromium e explora a tela de exemplo
de ponta a ponta (~10 s): confirma as 3 divergências, as 3 ações barradas e os arquivos gerados.
