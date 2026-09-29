# Jev Demos

Coleção de demos do **Jev, da TypeSafe**, explorando decisões tipadas com probabilidades em aplicações Python, interfaces web e integrações com Azure DevOps.

Os exemplos usam três tipos de pergunta: **Noul**, para uma probabilidade de sim/não; **Choice**, para escolher entre opções; e **Score**, para avaliar uma rubrica. O código usa essas respostas para filtrar resultados, aplicar mudanças na interface e sinalizar situações que precisam de revisão humana.

## Demos

| Demo | O que demonstra | Interface |
|---|---|---|
| [Hello Jev](hello-jev/hello_jev.py) | Uma chamada com Noul, Choice e Score para classificar uma mensagem de cliente e definir seu encaminhamento. | Terminal |
| [Skill Validator](skill-validator/README.md) | Validação local de Agent Skills e avaliação semântica de qualidade e risco com Jev. | CLI e relatórios JSON/Markdown |
| [Story Sizer](story-sizer/README.md) | Sugestão de tamanho de User Stories do Azure DevOps, com distribuição de probabilidades e comparação com estimativas do time. | Web e CLI |
| [Sprint Radar](sprint-radar/README.md) | Análise de risco de entrega das tasks de uma sprint do Azure DevOps, combinando cálculos de capacidade com julgamentos do Jev. | Web |
| [Catalog AI](catalog-ai/README.md) | Busca de skills, MCPs e plugins enquanto a pessoa digita, com relevância por item e filtros inferidos pelo Jev. | Web |
| [Brand Live](brand-live/README.md) | Comandos por voz ou texto que alteram uma marca fictícia a partir de peças prontas, com decisões aplicadas em tempo real. | Web |

Cada demo é independente e tem sua própria configuração. Os detalhes, roteiros e limites estão nos READMEs de cada pasta.

## Começar

Requisitos:

- Python 3.11 ou superior.
- `uv` para instalar dependências e executar os projetos com `pyproject.toml`.
- Uma chave TypeSafe ou OpenRouter para chamadas reais ao Jev.
- Acesso ao Azure DevOps e um PAT para Story Sizer e Sprint Radar.
- Chrome ou Edge para usar o reconhecimento de voz do Brand Live.

### Primeira chamada ao Jev

O Hello Jev usa apenas a biblioteca padrão do Python. Na raiz do repositório, copie o arquivo de configuração e preencha a chave do provedor escolhido:

```bash
cp hello-jev/.env.example hello-jev/.env
python3 hello-jev/hello_jev.py
python3 hello-jev/hello_jev.py "O suporte demorou 3 dias e ninguém resolveu meu problema."
```

O terminal mostra probabilidades, confiança, latência, tokens e custo, além da ação definida pelos limiares do código.

### Explorar uma interface sem chave

Catalog AI e Brand Live oferecem um modo simulado com heurísticas locais:

```bash
cd catalog-ai
uv sync --extra dev
uv run catalog-ai --fake --port 8771
```

Abra [http://127.0.0.1:8771](http://127.0.0.1:8771). As probabilidades e métricas desse modo não representam o Jev real.

Para experimentar o Brand Live, execute em sua pasta:

```bash
cd brand-live
uv sync --extra dev
uv run brand-live --fake --port 8776
```

Abra [http://127.0.0.1:8776](http://127.0.0.1:8776).

### Executar com o Jev real

Na pasta do demo escolhido:

```bash
uv sync --extra dev
cp .env.example .env
```

Edite o `.env` para selecionar o provedor e preencher a chave correspondente:

```dotenv
JEV_PROVIDER=typesafe
TYPESAFE_API_KEY=<sua-chave-typesafe>
```

Ou:

```dotenv
JEV_PROVIDER=openrouter
OPENROUTER_API_KEY=<sua-chave-openrouter>
```

Mantenha as demais configurações do `.env.example` de cada demo, incluindo o modelo. Depois, execute o comando correspondente dentro da pasta:

| Demo | Comando | Endereço padrão |
|---|---|---|
| Skill Validator | `uv run skill-validator examples/summarize-notes` | Terminal |
| Story Sizer | `uv run story-sizer-web` | [http://127.0.0.1:8765](http://127.0.0.1:8765) |
| Sprint Radar | `uv run sprint-radar` | [http://localhost:8766](http://localhost:8766) |
| Catalog AI | `uv run catalog-ai` | [http://127.0.0.1:8770](http://127.0.0.1:8770) |
| Brand Live | `uv run brand-live` | [http://127.0.0.1:8775](http://127.0.0.1:8775) |

Story Sizer e Sprint Radar também exigem `ADO_ORG`, `ADO_PROJECT`, `ADO_TEAM` e `AZURE_DEVOPS_PAT`. No Story Sizer, a gravação do tamanho no ADO fica desligada por padrão (`ALLOW_WRITE=false`); consulte seu README para habilitá-la.

O Skill Validator pode executar apenas a inspeção local, sem chave nem chamada ao Jev:

```bash
uv run skill-validator examples/summarize-notes --local-only
```

## Iniciar os demos web no Windows

O script [demos.ps1](demos.ps1) inicia, consulta e encerra os demos web. Execute na raiz do repositório com PowerShell, após preparar os arquivos `.env` necessários:

```powershell
./demos.ps1                                    # inicia todos os demos web
./demos.ps1 catalog-ai brand-live -Fake -Open   # inicia os dois em modo simulado
./demos.ps1 -Status                            # consulta os serviços
./demos.ps1 -Stop                              # encerra os serviços iniciados pelo script
```

O script salva logs e PIDs em `.run/`. Ele usa comandos específicos do Windows; no macOS ou Linux, execute cada demo pelos comandos individuais acima.

## Desenvolvimento

Dentro de cada projeto com `pyproject.toml`, instale as dependências de desenvolvimento e rode:

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
```

As suítes desses projetos usam chamadas HTTP simuladas e não exigem chaves de API. Para validar a integração real, configure o provedor e execute o demo correspondente.

## Sobre os resultados

Estes projetos são demonstrações. Limiares, rubricas e probabilidades precisam ser avaliados no contexto de uso; os READMEs individuais registram medições e limitações. No Story Sizer, por exemplo, a sugestão serve como triagem com incerteza explícita e não substitui a estimativa do time.
