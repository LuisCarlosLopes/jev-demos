# Skill Validator com Jev

Demo em Python para validar uma pasta de Agent Skill. O código verifica estrutura,
frontmatter, referências e possíveis segredos; o Jev avalia qualidade semântica e
sinais de risco. Funciona com a API direta TypeSafe e a Decisions API do OpenRouter.

## Executar

Requer Python 3.11+ e [uv](https://docs.astral.sh/uv/).

```bash
cd skill-validator
uv sync --extra dev
uv run skill-validator examples/summarize-notes 
```

O `.env` local já foi criado com valores vazios e está ignorado pelo Git. Em uma nova
cópia do demo, crie-o a partir do exemplo:

```bash
cp .env.example .env
```

Para chamar a TypeSafe, edite `.env`:

```dotenv
JEV_PROVIDER=typesafe
TYPESAFE_API_KEY=<sua-chave-typesafe>
TYPESAFE_MODEL=jev-latest
```

```bash
uv run skill-validator examples/summarize-notes --json reports/typesafe.json --markdown reports/typesafe.md
```

Para chamar o OpenRouter, edite `.env`:

```dotenv
JEV_PROVIDER=openrouter
OPENROUTER_API_KEY=<sua-chave-openrouter>
OPENROUTER_MODEL=typesafe/jev-1.13
```

```bash
uv run skill-validator examples/summarize-notes \
  --provider openrouter --json reports/openrouter.json --markdown reports/openrouter.md
```

`--provider` prevalece sobre `JEV_PROVIDER`. Variáveis do processo prevalecem sobre
as do `.env`. As chaves dos provedores são distintas; não se usa a chave TypeSafe
no OpenRouter. `--env-file /caminho/.env` permite escolher outro arquivo, sem procurar
automaticamente arquivos de credenciais em diretórios superiores.

Também funciona com pip:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
skill-validator examples/summarize-notes --local-only
```

## Exemplos

```bash
# Exemplo com estrutura válida; não faz chamadas externas.
uv run skill-validator examples/summarize-notes --local-only \
  --json reports/local.json --markdown reports/local.md

# Exemplo com nome inválido, description numérica e referência ausente.
# Sai com código 1 e não envia o conteúdo ao Jev.
uv run skill-validator examples/broken-skill --local-only

# Uma skill sua. SKILL.md também é aceito como argumento.
uv run skill-validator /caminho/da/minha-skill --policy policy.yaml
```

## O que é validado

| Camada | Verificações |
|---|---|
| Frontmatter | YAML seguro, delimitadores, duplicações, name/description, nome da pasta, tipos dos campos opcionais |
| Estrutura | SKILL.md na raiz, paths exigidos pela policy, symlinks, limites e erros de leitura |
| Referências | Links locais Markdown e paths convencionais em documentos; existência e confinamento à pasta |
| Segredos | Chaves com prefixos conhecidos, chaves privadas, JWTs, URLs com credenciais, atribuições suspeitas e as API keys configuradas |
| Jev / Score | Precisão dos gatilhos, clareza do procedimento, definição da saída e coerência do escopo |
| Jev / Noul | Sinais de exfiltração fora do escopo e tentativas de contornar permissões |

Somente `SKILL.md` é obrigatório por padrão. `scripts/`, `references/`, `assets/` e
`agents/` são opcionais. Campos extra de frontmatter produzem um aviso, permitindo
extensões de runtimes. Neste demo, aliases/merges YAML são rejeitados explicitamente.

O scanner lê também arquivos ocultos, como `.env`, e não executa scripts da skill.
Symlinks, arquivos ilegíveis e inspeções interrompidas por limites geram erros locais.
Binários são escaneados por padrões textuais, mas não entram na avaliação semântica.
Extensões em `allowed_binary_extensions` da policy (imagens, fontes, PDF) são aceitas
sem aviso; as demais geram o aviso `scan.binary`.
Links externos não são acessados. A análise de referências usa heurísticas Markdown:
não cobre links por referência nem resolve variáveis em scripts.

Uma falha local bloqueia qualquer chamada à API. Valores suspeitos nunca aparecem no
relatório: ele registra apenas regra, path e linha. O conteúdo da skill é tratado como
dado não confiável nas perguntas ao modelo. Isso reduz exposição, mas não transforma
o demo em um scanner exaustivo ou uma barreira infalível contra prompt injection.

## Padrões, pesos e decisão

Edite `policy.yaml` para acrescentar critérios, mudar pesos/limites ou exigir paths.
Por exemplo, `required_paths: [references]` torna essa pasta uma convenção obrigatória
para o seu catálogo. Cada dimensão precisa de 2 a 10 níveis concretos, um peso positivo,
e todos os pesos devem somar 1. Não use uma única pergunta vaga sobre “qualidade geral”.

As quatro dimensões padrão têm níveis de 0 a 3. A nota é calculada em código:

```text
qualidade = 100 × soma(peso × score / maior_nível)
```

Os limites de demonstração são nota mínima 75, confiança mínima 0,60, revisão de risco
a partir de 0,20 e bloqueio a partir de 0,80. Calibre esses valores com skills rotuladas;
eles não representam precisão medida deste validador.

| Status | Significado | Exit code |
|---|---|---:|
| passed | Regras locais e policy semântica atendidas | 0 |
| local_only | Somente inspeção local; nenhuma nota semântica | 0 |
| failed | Erro local, risco acima do limite ou nota insuficiente | 1 |
| review | Avaliação incerta ou risco intermediário | 2 |
| error | API/contrato/configuração semântica indisponível | 3 |

Erros de configuração da CLI saem com código 2. `--local-only` só dá sucesso para a
camada local; em CI que exige revisão semântica, execute sem essa opção e verifique
também `status == passed` no JSON. Avisos locais não reprovam automaticamente.

Riscos acima do limite não são compensados pela média de qualidade. Confiança abaixo
do limite solicita revisão antes de reprovar uma nota incerta. Uma resposta ausente,
malformada, com valores não finitos ou probabilidades inconsistentes nunca é aprovada.

O JSON guarda scores, probabilidades, confiança, modelo efetivo, consumo reportado,
custo em USD, tempo e a policy utilizada. Se o provedor não informa `usage.cost` (a
TypeSafe só devolve tokens), o custo é estimado pela tabela `PRICES_PER_MTOK` em
`semantic.py` e marcado com `cost_source: "estimated"`. Não contém os documentos da skill nem a API key. Isso
permite recalcular pesos/limites sem repetir a inferência; alterar perguntas ou níveis
exige nova avaliação. O Markdown e o terminal resumem os resultados sem inventar uma
justificativa em texto livre atribuída ao Jev.

## Integrações

| Provedor | Endpoint | Modelo padrão |
|---|---|---|
| TypeSafe | `https://api.typesafe.ai/v1/systemone` | `jev-latest` |
| OpenRouter | `https://openrouter.ai/api/alpha/decisions` | `typesafe/jev-1.13` |

As duas integrações usam HTTP com `httpx`, enviando `model`, `state` e `questions` e
lendo `answers`. O OpenRouter usa a API de decisões; não usamos chat completions nem
o modelo Jev Router para simular decisões. O endpoint OpenRouter é alpha e pode mudar.

As perguntas independentes são agrupadas em uma única requisição. Erros transitórios
429/503/529 recebem até três tentativas; redirecionamentos não são seguidos. Mensagens
de erro não ecoam corpos remotos nem headers. O timeout por tentativa vem do `.env`.

O limite `max_state_chars` evita truncamento silencioso e é uma estimativa conservadora,
não um contador de tokens. Ajuste-o respeitando o orçamento do modelo. Para avaliações
reprodutíveis, fixe uma versão do Jev e registre a policy; `jev-latest` pode mudar.

## Testes e limites

```bash
uv run pytest
uv run ruff check .
```

Os testes usam HTTP simulado para verificar os contratos dos dois provedores e casos
de segredos, inspeção incompleta, falhas de API e decisões incertas. Não exigem API key
e não fazem inferência real. Para testar a integração real, preencha `.env` e execute
o exemplo válido sem `--local-only`.

Validação estática não demonstra que a skill ativa corretamente ou executa o fluxo
certo. Para isso, adicione avaliações de execução com casos positivos e negativos.
Ausência de detecção de segredos não prova ausência de segredos; binários, arquivos
compactados e formatos não cobertos exigem ferramentas especializadas.

Documentação consultada:

- [Agent Skills Specification](https://agentskills.io/specification)
- [TypeSafe HTTP API](https://docs.typesafe.ai/api)
- [TypeSafe Score](https://docs.typesafe.ai/primitives/score)
- [TypeSafe Confidence](https://docs.typesafe.ai/confidence)
- [OpenRouter: Jev e chamada HTTP](https://openrouter.ai/blog/tutorials/how-to-use-jev/)
