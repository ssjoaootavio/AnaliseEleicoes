# Escopo — Comportamento de voto nas eleições presidenciais de 2026

**Projeto:** pessoal (João) · **Fase:** 0 → 1 (clareza + dados) · **Versão:** 2 · **Data:** 2026-10-26
**Status:** 1º turno com dados prontos e conferidos · 2º turno aguardando publicação do TSE
**Princípios ativos:** Garbage In/Garbage Out · Exploração antes de solução · Documentação viva · IA como amplificador, não substituto
*(adaptado de: 1-Pager e Metadados do playbook APM F.O.D.A)*

---

## 1. Objetivo (uma frase)

Mostrar, com dados oficiais do TSE e método aberto, o que aconteceu com os votos para presidente entre o 1º e o 2º turno de 2026, no Brasil e nos estados e municípios, para que um leitor de qualquer posição política consiga **verificar os números** e entender **o que os dados mostram e o que não mostram**.

**Resultado esperado para o leitor:** "Consigo explicar com números o que mudou entre os turnos sem precisar acreditar em nenhuma campanha."

## 2. Regras de neutralidade (testáveis)

1. Só dados oficiais do TSE + código reprodutível. Nenhum número sem fonte.
2. Cada afirmação é marcada como **fato observado**, **estimativa** ou **hipótese**.
3. Os dois candidatos recebem o mesmo tratamento: mesmas tabelas, mesma ordem, mesmos verbos.
4. Estimativas sempre com intervalo de incerteza e rótulo "estimativa".
5. Sem explicar causas (campanha, economia, rejeição) e sem opinar sobre legitimidade do resultado ou da prorrogação.
6. Cada seção declara seus limites.

## 3. Em escopo (perguntas que o trabalho responde)

| # | Pergunta | Recorte |
|---|---|---|
| P1 | Quantos votos cada candidato teve, e quantas abstenções, brancos e nulos, em cada turno? Como isso variou do 1º para o 2º? | Brasil e 27 UFs |
| P2 | Mesma pergunta, por município, com destaque às capitais, às maiores cidades e aos municípios de margem curta | Municípios |
| P3 | Para onde foram os votos do 1º turno no 2º? **(estimativa)** | Brasil → UF → por candidato do 1º turno (Cury, Renan Santos, Caiado, Zema, demais, brancos/nulos, abstenção) → Lula / Flávio / branco-nulo / abstenção |
| P4 | **(condicional)** A prorrogação do horário (17h → 19h) teve peso mensurável? | Só se os dados abertos permitirem |

## 4. Fora do escopo (nesta versão)

- Causas políticas, pesquisas de opinião e previsões.
- Outros cargos (governador, senador, deputados).
- Auditoria de urnas, fraude, avaliação jurídica da prorrogação ou do pedido de anulação.
- Perfil sociodemográfico (renda, religião, IBGE): candidato à v3.
- Saber "quem votou em quem" de forma individual (voto secreto).

## 5. Premissas metodológicas que precisam ser aceitas

- **Transferência de votos não é observável, só estimável.** Pelos dados agregados (seção/município) dá para estimar fluxos por inferência ecológica, sempre com margem de erro e risco de falácia ecológica. O nome correto é "estimativa de migração de votos".
- **Abstenção, brancos e nulos entram como origem e destino**, não só como resíduo.
- **P4 depende de dado que ainda não achamos:** os arquivos abertos já baixados (votação por seção) não têm horário. É preciso achar hora de encerramento por seção (Boletim de Urna, arquivos transmitidos ou estudo do TSE). Tratado como **spike com go/no-go**.

**Base factual da prorrogação (conferir antes de publicar):** em 25/10 o ministro Zanin (STF) mandou estender a votação até as 19h; o TSE aplicou só nas seções ainda abertas às 17h. Segundo a imprensa, ambas as campanhas pediram extensão (Lula: BA e outros; Flávio: SP, PR, MG, RS, SC). O TSE disse que estuda o impacto e não divulgou quantas seções ou eleitores votaram depois das 17h.

## 6. Dados e dependências

| Item | Fonte | Status | Bloqueia |
|---|---|---|---|
| Votação por seção, presidente, 1º turno | dadosabertos.tse.jus.br → Resultados 2026 | **Pronto** (499.206 linhas; nacional bate com TSE) | — |
| Votação por seção, presidente, 2º turno | mesmo dataset | **Pendente** (arquivo atual gerado em 06/10) | P1, P2, P3 |
| Aptos, comparecimento e abstenção por seção | "Detalhe da apuração por seção" | A confirmar colunas | P1, P3 |
| Horário de encerramento por seção | BU / arquivos transmitidos / TSE | **Desconhecido** | P4 |
| Código de leitura | `analisa_votos_tse.py` | Funciona no 1º turno | — |

## 7. Entregas e marcos

| Marco | Entrega | Gate para avançar |
|---|---|---|
| M1 | P1: Brasil e UFs, 1º × 2º turno | Totais Brasil e UF batem com o TSE (diferença 0) |
| M2 | P2: municípios | Soma dos municípios = total da UF |
| M3 | P3: transferência estimada | Modelo reproduz os totais do 2º turno por UF dentro da margem acordada, com intervalos publicados |
| M4 | P4: pós-17h (condicional) | Spike confirma que existe dado de horário |
| M5 | Relatório em linguagem simples + teste de leitura cruzada | Métricas da seção 8 atingidas |

**Formato proposto:** relatório curto + tabelas CSV + código aberto. *(Decisão pendente: painel interativo.)*

## 8. Métricas de sucesso

1. **Conciliação:** 100% dos totais Brasil/UF iguais aos do TSE (linha de base: 1º turno nacional ✓).
2. **Reprodutibilidade:** uma terceira pessoa roda o código e chega aos mesmos números.
3. **Neutralidade:** ≥ 4 leitores de posições políticas diferentes; ≥ 80% acertam 5 perguntas factuais e a nota de neutralidade fica ≥ 4/5 dos dois lados.
4. **Transparência:** 100% das estimativas com intervalo e rótulo.

## 9. Riscos

| Risco | Impacto | Mitigação |
|---|---|---|
| Relatório usado como arma de narrativa em disputa política ou judicial | Perda de credibilidade | Regras da seção 2, método aberto, nenhuma conclusão sobre legitimidade |
| Estimativa de transferência lida como "fato" | Interpretação errada | Rótulo, intervalo e texto explicando o limite |
| Dados do 2º turno ou de horário indisponíveis | Atraso ou corte de P3/P4 | Escopo em marcos; P4 condicional |

## 10. Decisões

**Tomadas (revisáveis):**
- Decisão: P4 entra como **spike condicional**, não como compromisso. Racional: sem dado de horário, a pergunta não é respondível, e prometer deixaria o escopo frágil.
- Decisão: P3 é **estimativa**, nunca fato. Racional: voto é secreto.

**Pendentes (preciso do João):**
1. **Formato final:** relatório + CSV + código, ou também painel interativo?
2. **Granularidade da transferência no v1:** por UF (mais simples) ou por seção (mais preciso, mais pesado)?
3. **Público ou pessoal?** Publicar muda o rigor exigido (revisão, linguagem, fontes citadas).
4. **P4 (pós-17h):** confirmar spike agora ou só depois de M1.

## 11. Próximos passos

| Ação | Dono | Quando |
|---|---|---|
| Responder as 4 decisões pendentes | João | Hoje |
| Rodar o script no arquivo do 2º turno quando o TSE publicar | João | Quando sair (verificar `NR_TURNO = 2`) |
| Confirmar colunas do "Detalhe da apuração por seção" | João envia amostra, Claude confirma | Após decisão 2 |
| Spike do horário de encerramento (P4) | Claude + João | Após decisão 4 |

**Próxima ação de maior alavancagem:** responder a decisão 3 (público ou pessoal), porque ela define o rigor de todo o resto.

---

### Registro de evolução

| Data | Alteração | Motivo | Autor |
|---|---|---|---|
| 2026-10-26 | v1 | Esboço inicial | João |
| 2026-10-26 | v2 | Objetivo mensurável, regras de neutralidade, escopo × fora de escopo, P3 como estimativa, P4 condicional, marcos, métricas, riscos | João + Claude |