# Assertividade das decisões: Jev x heurística lexical

Gerado por `scripts/eval_decisions.py`. **Desenvolvimento**: telas e casos usados para ajustar as perguntas e a captura. **Validação**: gabarito escrito antes de rodar o Jev nessas telas, sem ajustes depois.

## Desenvolvimento

Telas: fornecedor.html, ferias.html, login.html, titulos.html · 16 casos de oráculo.

| Decisão | Jev | Heurística |
|---|---:|---:|
| Tipo de dado (campos de texto) | 21/21 | 13/21 |
| Obrigatoriedade | 26/26 | 26/26 |
| Papel da ação | 27/27 | 23/27 |
| Portão de risco (não clicar) | 24/24 | 22/24 |
| Tipo de tela | 4/4 | 0/4 |
| Oráculo: desfecho | 16/16 | 10/16 |
| Oráculo: campo apontado | 15/15 | 10/15 |

Jev: 5 requisições · 582 ms (43 perguntas), 312 ms (28 perguntas), 299 ms (13 perguntas), 315 ms (29 perguntas), 331 ms (32 perguntas) · 44109 tokens · US$ 0.00185.
Erros do Jev com confiança abaixo de 60% (iriam para “revisar”): 0 de 0.

### Erros · Jev

- nenhum

### Erros · Heurística

- Tipo de dado (campos de texto): fornecedor.html: “Documento (obrigatório)” → other (86%), esperado cnpj
- Tipo de dado (campos de texto): fornecedor.html: “Inscrição estadual” → other (86%), esperado code
- Tipo de dado (campos de texto): fornecedor.html: “Endereço para envio das notas fiscais (obrigatório)” → free_text (86%), esperado email
- Tipo de dado (campos de texto): fornecedor.html: “Contato comercial” → other (86%), esperado phone
- Tipo de dado (campos de texto): fornecedor.html: “Código postal” → code (86%), esperado cep
- Tipo de dado (campos de texto): fornecedor.html: “Anotações internas” → other (86%), esperado free_text
- Tipo de dado (campos de texto): ferias.html: “Colaborador *” → other (86%), esperado person_name
- Tipo de dado (campos de texto): titulos.html: “Fornecedor” → code (86%), esperado search
- Papel da ação: fornecedor.html: “Descartar alterações” → delete (86%), esperado clear/cancel_back
- Papel da ação: fornecedor.html: “Histórico” → other (86%), esperado open_panel
- Papel da ação: fornecedor.html: “Inativar fornecedor” → other (86%), esperado delete
- Papel da ação: login.html: “Esqueci minha senha” → other (86%), esperado open_panel/navigate
- Portão de risco (não clicar): fornecedor.html: “Descartar alterações” não clicar=True (risco 90%; papel: excluir; Jev: risco 90%), esperado False
- Portão de risco (não clicar): fornecedor.html: “Inativar fornecedor” não clicar=False (risco 5%; —), esperado True
- Tipo de tela: fornecedor.html: tela other (86%)
- Tipo de tela: ferias.html: tela other (86%)
- Tipo de tela: login.html: tela other (86%)
- Tipo de tela: titulos.html: tela other (86%)
- Oráculo: desfecho: “Registro gravado.” → no_feedback (86%), esperado accepted
- Oráculo: desfecho: “Não foi possível gravar: documento já cadastrado para outro fornecedor.” → accepted (86%), esperado rejected
- Oráculo: desfecho: “Ocorreu um erro inesperado. Tente novamente mais tarde. (código 500)” → rejected (86%), esperado server_error
- Oráculo: desfecho: “Limite (R$): valor acima do permitido para o seu perfil.” → no_feedback (86%), esperado rejected
- Oráculo: desfecho: “Sessão expirada. Entre novamente para continuar.” → no_feedback (86%), esperado server_error
- Oráculo: desfecho: “Registro incluído com sucesso!” → no_feedback (86%), esperado accepted
- Oráculo: campo apontado: “Não foi possível gravar: documento já cadastrado para outro fornecedor.” → campo none (86%), esperado Documento (obrigatório)
- Oráculo: campo apontado: “Atenção / O prazo deve ser maior que zero.” → campo general (86%), esperado Prazo (dias) (obrigatório)
- Oráculo: campo apontado: “Limite (R$): valor acima do permitido para o seu perfil.” → campo none (86%), esperado Limite (R$)
- Oráculo: campo apontado: “CNPJ inválido” → campo general (86%), esperado Documento (obrigatório)
- Oráculo: campo apontado: “Informe um número inteiro de dias.” → campo general (86%), esperado Prazo (dias) (obrigatório)

### Risco estimado por ação (Jev)

| Tela | Ação | Deve evitar? | Risco (Noul) | Barrada |
|---|---|---|---:|---|
| fornecedor.html | Compras | não | 11% | não |
| fornecedor.html | Fornecedores | não | 11% | não |
| fornecedor.html | Sair do sistema | sim | 71% | sim |
| fornecedor.html | Gravar | — | 60% | não |
| fornecedor.html | Descartar alterações | não | 16% | não |
| fornecedor.html | Voltar | não | 16% | não |
| fornecedor.html | Histórico | não | 11% | não |
| fornecedor.html | Exportar PDF | sim | 65% | sim |
| fornecedor.html | Inativar fornecedor | sim | 70% | sim |
| ferias.html | Início | não | 13% | não |
| ferias.html | Minhas férias | não | 10% | não |
| ferias.html | Enviar solicitação | — | 84% | sim |
| ferias.html | Salvar rascunho | não | 41% | não |
| ferias.html | Cancelar | não | 14% | não |
| ferias.html | Excluir solicitação | sim | 72% | sim |
| login.html | Entrar | — | 47% | não |
| login.html | Esqueci minha senha | não | 10% | não |
| login.html | Criar conta | não | 8% | não |
| login.html | Central de ajuda | sim | 14% | sim |
| titulos.html | Financeiro | não | 12% | não |
| titulos.html | Novo título | não | 11% | não |
| titulos.html | Pesquisar | não | 11% | não |
| titulos.html | Limpar filtros | não | 12% | não |
| titulos.html | Pagar selecionados | sim | 65% | sim |
| titulos.html | Exportar planilha | sim | 69% | sim |
| titulos.html | Excluir selecionados | sim | 65% | sim |
| titulos.html | Próxima página | não | 11% | não |

## Validação

Telas: reembolso.html, conta.html · 6 casos de oráculo.

| Decisão | Jev | Heurística |
|---|---:|---:|
| Tipo de dado (campos de texto) | 9/9 | 6/9 |
| Obrigatoriedade | 14/14 | 14/14 |
| Papel da ação | 11/11 | 9/11 |
| Portão de risco (não clicar) | 9/9 | 9/9 |
| Tipo de tela | 2/2 | 1/2 |
| Oráculo: desfecho | 6/6 | 2/6 |
| Oráculo: campo apontado | 6/6 | 3/6 |

Jev: 3 requisições · 325 ms (25 perguntas), 307 ms (25 perguntas), 271 ms (12 perguntas) · 18306 tokens · US$ 0.00077.
Erros do Jev com confiança abaixo de 60% (iriam para “revisar”): 0 de 0.

### Erros · Jev

- nenhum

### Erros · Heurística

- Tipo de dado (campos de texto): reembolso.html: “Quilometragem rodada” → other (86%), esperado quantity
- Tipo de dado (campos de texto): reembolso.html: “Centro de custo” → other (86%), esperado code
- Tipo de dado (campos de texto): conta.html: “Número para SMS” → other (86%), esperado phone
- Papel da ação: conta.html: “Alterar senha” → other (86%), esperado open_panel/navigate
- Papel da ação: conta.html: “Encerrar conta” → other (86%), esperado delete/logout
- Tipo de tela: conta.html: tela other (86%)
- Oráculo: desfecho: “A data da despesa não pode ser posterior a hoje.” → no_feedback (86%), esperado rejected
- Oráculo: desfecho: “Valor acima do limite da política (R$ 500,00). Anexe uma justificativa.” → no_feedback (86%), esperado rejected
- Oráculo: desfecho: “Serviço indisponível no momento.” → no_feedback (86%), esperado server_error
- Oráculo: desfecho: “Estabelecimento não encontrado na Receita Federal.” → no_feedback (86%), esperado rejected
- Oráculo: campo apontado: “A data da despesa não pode ser posterior a hoje.” → campo none (86%), esperado Data da despesa *
- Oráculo: campo apontado: “Valor acima do limite da política (R$ 500,00). Anexe uma justificativa.” → campo none (86%), esperado Valor gasto *
- Oráculo: campo apontado: “Estabelecimento não encontrado na Receita Federal.” → campo none (86%), esperado CNPJ do estabelecimento

### Risco estimado por ação (Jev)

| Tela | Ação | Deve evitar? | Risco (Noul) | Barrada |
|---|---|---|---:|---|
| reembolso.html | Salvar | — | 39% | não |
| reembolso.html | Enviar para aprovação | sim | 74% | sim |
| reembolso.html | Cancelar | não | 17% | não |
| reembolso.html | Excluir despesa | sim | 53% | sim |
| conta.html | Painel | não | 11% | não |
| conta.html | Ajuda | não | 10% | não |
| conta.html | Sair | sim | 76% | sim |
| conta.html | Salvar alterações | — | 54% | não |
| conta.html | Alterar senha | não | 13% | não |
| conta.html | Baixar meus dados | sim | 61% | sim |
| conta.html | Encerrar conta | sim | 33% | sim |
