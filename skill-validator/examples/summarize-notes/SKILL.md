---
name: summarize-notes
description: Resume notas de reunião fornecidas pelo usuário, destacando decisões e ações com responsáveis. Use quando o pedido for sintetizar uma reunião; não para enviar mensagens ou criar eventos.
license: MIT
metadata:
  version: "1.0"
---

# Resumir notas de reunião

Receba o texto das notas ou leia o arquivo explicitamente indicado pelo usuário.
Se as notas ainda não foram fornecidas, peça o conteúdo antes de produzir o resumo.

1. Identifique os tópicos discutidos e as decisões registradas.
2. Separe ações das decisões. Copie o responsável e o prazo somente quando constarem nas notas.
3. Se uma decisão estiver ambígua, indique a ambiguidade; não invente um acordo.
4. Formate a saída conforme [o formato de resumo](references/output.md).

Entregue o resumo em Markdown na conversa. A tarefa termina com o resumo e a indicação
das informações ausentes. Enviar mensagens, criar eventos ou alterar as notas originais
exige um pedido separado do usuário.
