# Brand Live com Jev

Demo de velocidade de decisão. Uma marca fictícia (hero, diferenciais, planos, e-mail e
post social) muda **enquanto a pessoa fala**. A voz vira texto no navegador; cada frase
vira uma única requisição ao Jev com ~10 decisões tipadas; o navegador aplica as
decisões a um catálogo de peças prontas. O Jev não gera nada. Ele escolhe.

O painel à direita mostra, por frase, as probabilidades, a latência e o custo. Medido
com `jev-latest` (jev-1.13) em 29/09/2026: **~320 ms** por frase, ~3.200 tokens de
entrada, **US$ 0,00013** por comando. Quinze comandos custaram US$ 0,002.

| Decisão | Primitivo | Uso na tela |
|---|---|---|
| É um comando? | Noul | Ignora "hmm, deixa eu ver" e frases ainda incompletas |
| Intenção | Choice (10) | Decide qual faceta abaixo vale; as outras são ignoradas |
| Alvo da cor | Choice (4) | Fundo, cor principal, texto ou destaque; sem alvo = principal |
| Cor | Choice (27) | Paleta nomeada: "vinho", "marinho", "bege" resolvem para um hex |
| Segmento | Choice (12 + fora do catálogo) | Troca tema, nome, copy e tom de uma vez |
| Tom de voz | Score (5 níveis) | Copy formal ou casual, raio dos cantos; "mais leve" é relativo ao tom atual |
| Layout, fonte, seção | Choice | Dividido/centralizado/minimalista; sans/serif/display/mono; mostrar/esconder |
| Fora do catálogo | Noul | "Põe uma foto" vira aviso, não erro silencioso |

O Jev só decide. **Limiares ficam no navegador**: acima de `aplicar` a mudança entra;
entre `perguntar` e `aplicar` a tela mostra as duas opções mais prováveis e espera um
clique; abaixo, ignora. Mexer nos sliders não custa nova inferência.

## Executar

Requer Python 3.11+, [uv](https://docs.astral.sh/uv/) e Chrome/Edge (Web Speech API).

```bash
cd brand-live
uv sync --extra dev
cp .env.example .env   # preencha TYPESAFE_API_KEY ou OPENROUTER_API_KEY
uv run brand-live      # http://127.0.0.1:8775
```

Sem chave, dá para ver a interface com um Jev **simulado** (heurística lexical local).
A tela exibe um aviso e os números não representam o modelo:

```bash
uv run brand-live --fake --port 8776
```

Clique no microfone (ou barra de espaço) e fale em português. O campo de texto faz o
mesmo e serve de reserva quando o ambiente está barulhento.

## Roteiro sugerido

1. "quero vender consultoria de RH" — tema, nome e copy trocam de uma vez.
2. "fundo vermelho" — só o fundo muda; o texto se ajusta ao contraste.
3. "isso está muito sério, deixa mais leve" — Score relativo ao tom atual.
4. "muda pra vender tênis" — outro segmento, outra fonte, outro tom.
5. "tira o e-mail" / "volta" — seção some e volta pelo histórico.
6. "quero vender foguetes" — segmento fora do catálogo: a tela avisa em vez de chutar.

## Como a voz vira decisão

O Chrome entrega transcrições parciais enquanto a frase é dita. Cada parcial estável
por 350 ms vai ao Jev marcada como `partial`; a página já reage antes de a frase fechar.
Quando a frase fecha, a versão final vai de novo, mas o navegador não reaplica a
mesma mudança (mesma intenção, mesmo valor, mesmo alvo). O servidor guarda um cache
por (frase, estado do brand) para não pagar duas vezes pela mesma parcial.

Falando sem pausa, o Chrome mantém tudo num único segmento que só cresce ("quero
vender café fundo vermelho deixa mais leve"). Assim que um trecho vira mudança
aplicada, o navegador passa a mandar ao Jev **só as palavras novas**; cada ordem ganha
a própria linha no painel. Sem isso, apenas a primeira ordem de cada respiração seria
ouvida.

## Limites

- O Jev escolhe entre opções que existem: não há "cor #FF6B35" nem segmento novo. É
  isso que mantém a resposta em milissegundos e o brand dentro do design system.
- Uma frase, uma intenção. "Fundo vermelho e título maior" aplica só a primeira.
- O modo simulado devolve sempre 88% de confiança; o caminho "quis dizer?" só aparece
  com o Jev real ou subindo o slider `aplicar`.
- Os limiares de demonstração não foram calibrados com comandos rotulados. Numa rodada
  de 25 frases do roteiro (incluindo palavras soltas como "vinho", "café", "volta" e
  conversa como "bom dia pessoal"), todas foram classificadas como esperado depois de
  explicitar nas perguntas que palavra solta conta como comando.
- `out_of_catalog` oscila entre 30% e 55% em comandos válidos; o limiar de 0,70 segura,
  mas vale observar antes de baixá-lo.

## Testes

```bash
uv run pytest
uv run ruff check .
```

Os testes cobrem o contrato das perguntas, a validação das respostas, o orçamento de
tokens, o cache, a resposta segura a falhas do provedor e o roteiro acima em modo
simulado. Não fazem inferência real.
