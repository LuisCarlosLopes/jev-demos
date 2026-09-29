# Catálogo de IA com Jev

Demo de velocidade de decisão. Um site com o catálogo de skills, MCPs e plugins da
empresa. A pessoa descreve o que precisa e, enquanto digita, o Jev decide o que é
relevante, infere os filtros e a tela se adapta.

Cada busca é **uma única requisição** com ~115 decisões avaliadas em paralelo:

| Decisão | Primitivo | Uso na tela |
|---|---|---|
| Tecnologia citada | Choice (11 + "não citado") | Chip de filtro: esconde artefatos de outra stack e mantém os genéricos (Git/GitHub conta como genérico) |
| Tipo de artefato | Choice (skill/MCP/plugin) | Chip de filtro. "Algo que leia o ADO" deve inferir MCP |
| Time mencionado | Choice (7 times) | Chip informativo: ordena, não filtra |
| Finalidade | Choice (13) | Chip informativo: ordena, não filtra |
| Consulta incompleta | Noul | Ainda digitando: mantém o último resultado útil |
| Relevância de cada artefato | 1 Noul por item (110) | Lista, barra de relevância e "Recomendado" |

O Jev só decide. **Limiares, filtros e ordenação rodam no navegador** sobre as
probabilidades recebidas, então mexer nos sliders recalcula a tela sem nova inferência.
Os chips mostram a confiança e podem ser removidos. Quando os filtros escondem
resultados relevantes, a tela avisa quantos.

## Executar

Requer Python 3.11+ e [uv](https://docs.astral.sh/uv/).

```bash
cd catalog-ai
uv sync --extra dev
cp .env.example .env   # preencha TYPESAFE_API_KEY ou OPENROUTER_API_KEY
uv run catalog-ai      # http://127.0.0.1:8770
```

Sem chave, dá para ver a interface com um Jev **simulado** (heurística lexical local).
A tela exibe um aviso e os números de latência e relevância não representam o modelo:

```bash
uv run catalog-ai --fake --port 8771
```

Para reaproveitar a chave do outro demo sem copiá-la:

```bash
uv run catalog-ai --env-file ../skill-validator/.env
```

`--provider openrouter` usa a Decisions API do OpenRouter, com a mesma configuração
do `skill-validator` (`JEV_PROVIDER`, `*_API_KEY`, `*_MODEL`, `JEV_TIMEOUT_SECONDS`).

## Passo 0: medir antes de apresentar

A documentação não publica a latência. Antes da demo, meça com o catálogo real:

```bash
uv run python scripts/bench_latency.py --sizes 10 50 110 --runs 5 [--env-file ../skill-validator/.env]
```

A saída traz p50/p95 em ms, tokens e custo por tamanho de requisição. Se o p50 com 110
artefatos passar de ~600 ms, a busca a cada tecla vai parecer lenta. Nesse caso, aumente
`DEBOUNCE_MS` em `static/app.js` ou reduza o catálogo enviado.

Medição de 29/09/2026 (`jev-latest` → `jev-1.13.0`, API TypeSafe, 5 execuções):

| Artefatos | Perguntas | p50 | p95 | Tokens | US$ por busca |
|---:|---:|---:|---:|---:|---:|
| 10 | 15 | 292 ms | 432 ms | 3.291 | 0,000138 |
| 50 | 55 | 360 ms | 374 ms | 11.069 | 0,000465 |
| 110 | 115 | 426 ms | 455 ms | 21.970 | 0,000923 |

Passar de 15 para 115 perguntas custou ~130 ms a mais. Nas 7 consultas do roteiro, a
resposta ficou entre 450 e 590 ms, e o primeiro resultado estava certo em todas.

## Velocidade e economia

- **Uma ida e volta por busca.** Todas as perguntas vão juntas, e a documentação diz
  que "adicionar Nouls quase não muda o tempo de resposta".
- **Conexão reaproveitada.** Um `httpx.AsyncClient` com keep-alive, aquecido na subida
  com uma decisão mínima (~60 tokens), para a primeira busca não pagar o handshake TLS.
- **Digitação.** Debounce de 220 ms, cancelamento da requisição anterior e descarte de
  respostas atrasadas. Buscas repetidas vêm de um cache LRU em memória (custo zero).
- **Tokens.** O texto repetido em cada Noul é curto de propósito (cada palavra vale
  ×110) e as descrições são cortadas em 280 caracteres. Estimativa: ~20k tokens de
  entrada por busca (medido: 21.970), cerca de US$ 0,0009 a US$ 0,042/M. Saída não é cobrada.
- **Telemetria na tela.** Latência do Jev e do servidor, número de decisões, tokens e
  custo por busca, mais os totais da sessão. O painel "Decisões desta busca" mostra as
  distribuições dos Choices e o histograma dos 110 Nouls.

## Base do catálogo

`data/catalog.json` tem 110 artefatos:

- **97 skills reais** do registro público [skills.sh](https://skills.sh), o mesmo que a
  skill `find-skills` consulta com `npx skills find`. Nome, descrição, comando de
  instalação e número de instalações vêm do registro.
- **13 artefatos internos de exemplo** em `data/internal.json` (MCPs, plugins e skills
  da Aurora Cloud), para ter os três tipos e a tecnologia da casa.

Os **times donos são fictícios** e as tags de finalidade e tecnologia de cada skill
são derivadas por heurística em `scripts/build_catalog.py`. São metadados de exemplo,
não classificação oficial. Para regenerar (usa cache em `scripts/.cache/` e respeita o
rate limit do registro):

```bash
uv run python scripts/build_catalog.py
```

As descrições vêm da web e são tratadas como dados não confiáveis: o HTML as escapa e
as perguntas ao Jev dizem que o texto do artefato não é instrução.

## Limites

- Choice aceita até 255 opções e o contexto é de 64k tokens (32k para estado + maior
  pergunta). Acima de ~250 artefatos, seria preciso um pré-filtro (lexical ou por
  embedding) antes do Jev. `load_catalog` recusa catálogos maiores.
- Probabilidades de Choice somam 1, por isso a lista usa um Noul por artefato: duas
  skills igualmente boas recebem, cada uma, probabilidade alta.
- Os limiares padrão (relevância 60%, filtro 70%, incompleta 70%) foram escolhidos com
  as 7 consultas do roteiro. Calibre com consultas rotuladas.
- Time é só ordenação: no teste real, "sou do front" inferiu time Frontend com 82% e,
  como filtro, esconderia o `webapp-testing`, que é do time Qualidade.
- O Jev não explica as respostas. Os motivos no card (tags destacadas, barra de
  relevância) vêm dos dados, não de texto gerado.

## Testes

```bash
uv run pytest
uv run ruff check .
```

Os testes usam HTTP simulado: contrato da requisição, validação das respostas
(probabilidades, opções, chaves ausentes), cache, erros sem vazar o corpo remoto e o
modo simulado. Não exigem API key.
