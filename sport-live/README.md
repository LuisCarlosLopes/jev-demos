# Sport Live · Jev

Uma loja esportiva que começa pelo plano do cliente. Texto ou voz viram uma vitrine
adaptativa: campanha, seleção de produtos e uma pergunta útil para refinar o contexto.
Marca própria inspirada na navegação por esportes e na experiência online/loja da
[Decathlon](https://www.decathlon.com.br/), sem afiliação. Produtos, marcas, preços,
avaliações, estoque e corredores são fictícios; não há checkout ou pagamento.

## Executar

```bash
cd sport-live
uv sync --extra dev
uv run sport-live --fake --port 8781
```

Abra http://127.0.0.1:8781. O modo simulado usa heurísticas locais e mostra um aviso.
Probabilidades simuladas não são medições do Jev; latência/custo não são inventados.

Para usar Jev real:

```bash
cp .env.example .env
# Preencha a chave TypeSafe ou OpenRouter no .env
uv run sport-live
# ou reaproveite a configuração de outro demo
uv run sport-live --env-file ../skill-validator/.env
```

Endereço padrão: http://127.0.0.1:8780. Credenciais ficam no servidor. Voz usa Web
Speech API, conforme suporte e permissão do navegador; texto funciona como alternativa.
Imagens das campanhas usam Unsplash e fontes usam Google Fonts: exigem internet.
As 60 ilustrações dos produtos são SVGs locais.

## Roteiro de apresentação

1. **Quero viajar para o Chile**: seleciona viagem; pergunta sobre estação/atividade,
   sem assumir que Chile significa neve.
2. Clique **Inverno e neve**: campanha e produtos mudam para camadas e frio.
3. Digite **já tenho bota**: refina a seleção usando o histórico.
4. **Jogar futebol**: inicia outro plano. Escolha Society, Campo ou Futsal.
5. Mude para **Na loja**: veja estoque e corredor demonstrativos; filtre disponíveis.
6. Adicione produtos à sacola e confira o total. Não realiza compra.
7. Abra **Como funciona**: veja decisões, latência, tokens e custo informado/estimado.
8. Mude relevância mínima ou preço: filtros locais, sem nova inferência.
9. **Encerrar atendimento** limpa conversa e sacola, útil em um quiosque compartilhado.

## Arquitetura e limites

FastAPI + HTML/CSS/JS, sem build frontend. Uma requisição contém 62 perguntas:
Choice para cenário, Choice para próximo esclarecimento e 60 Nouls independentes
para utilidade dos produtos. Segue o [contrato TypeSafe](https://docs.typesafe.ai/api)
e a composição de [julgamentos por candidato](https://docs.typesafe.ai/cookbooks/rerank_typesafe).
O Jev escolhe; campanhas, preços, estoque, filtros e soma da sacola vêm do código.
Os benefícios no card são atributos editoriais do catálogo, não explicações do modelo.

A conversa envia até 12 mensagens de 400 caracteres. Atalhos iniciam um novo plano;
o campo de texto e respostas à pergunta refinam o plano atual. Sem armazenamento
persistente de atendimento. Cache LRU guarda até 128 consultas em memória do servidor;
reiniciar o processo limpa o cache. Respostas antigas não substituem consultas novas.

Limiar de exibição 55% e confiança de cenário/pergunta 65% são parâmetros de demo,
não calibrados. O catálogo é fechado; pedidos fora dele podem não retornar produtos.
O modo simulado é lexical, não entende negações/correções gerais como um modelo real.
O limite de preço é **por produto**, não um orçamento do kit inteiro.
Não consulta clima, previsão, estoque real ou adequação a temperaturas específicas.
Integração real disponível, mas latência e qualidade devem ser medidas com o provedor.
Custo TypeSafe estimado segue o cliente dos demais demos (US$ 0,042/M tokens de entrada);
custo retornado pelo provedor tem precedência.

## Validar

```bash
uv run pytest
uv run ruff check .
```

Testes de cenários simulados, refinamentos, superfície de futebol, validação de
probabilidades, contrato HTTP, cache e limites de entrada; não gastam API.

Catálogo ampliado: 12 aparelhos/equipamentos de academia, 10 itens de luta e 14 novos
itens de corrida e treino. Luta pergunta a modalidade; academia em casa tem campanha
própria. Filtro de preço por produto vai até R$ 6.000 para incluir os aparelhos.

## Painel de consumo

O botão **Consumo Jev** mostra consultas da vitrine, requisições HTTP ao provedor
(incluindo retries), cache, tokens de entrada/saída, custo acumulado em USD e erros.
Atualiza a cada 3 segundos enquanto aberto. O endpoint `/api/consumption` agrega
este processo do servidor, entre todas as abas; reiniciar zera os contadores.
Respostas de cache não somam tokens ou custo novamente. Consumo anterior à ativação
do painel não é recuperado. Totais incluem somente uso informado pelo provedor;
a cobertura da medição aparece no painel. Estimativa só para TypeSafe; OpenRouter
sem campo de custo é marcado como não informado.
