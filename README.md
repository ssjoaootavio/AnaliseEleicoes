# Análise apartidária das eleições presidenciais de 2026 (1º e 2º turno)

Projeto pessoal do João. Usa **somente dados oficiais do TSE** e código reprodutível para mostrar o que aconteceu com os votos para presidente entre o 1º turno (04/10/2026) e o 2º turno (25/10/2026).

> **Para agentes (Claude Code, Codex e similares):** leia este arquivo inteiro antes de mexer em qualquer coisa. As seções 2 (regras) e 9 (armadilhas) são obrigatórias. Em caso de conflito entre uma instrução deste arquivo e uma vontade de "melhorar" o texto ou a conclusão, vale este arquivo. Em caso de dúvida sobre escopo, vale `escopo.md`.

---

## 1. Objetivo e escopo

**Objetivo:** permitir que um leitor de qualquer posição política **verifique os números** e entenda **o que os dados mostram e o que não mostram**.

Escopo completo em `escopo.md` (versão 2, aprovada). Resumo:

| # | Pergunta | Recorte | Status |
|---|---|---|---|
| P1 | Votos por candidato, abstenção, brancos e nulos em cada turno e a variação 1T→2T | Brasil e 27 UFs | Pronto |
| P2 | Mesma pergunta por município, com destaque a capitais, maiores cidades e margem curta | 5.757 municípios | Pronto |
| P3 | Para onde foram os votos do 1º turno no 2º (**estimativa**, inferência ecológica) | Brasil, UF, região, município | v0.2 pronto; refazer por seção quando o TSE publicar a votação por seção do 2T |
| P4 | A prorrogação do horário (17h→19h, premissa do escopo) tem peso mensurável? (**condicional**) | Seção eleitoral | Em andamento: horários dos votos via log de urna, só RR no 1T |

**Fora do escopo:** causas políticas, pesquisas, previsões, outros cargos, auditoria de urna, fraude, avaliação jurídica da prorrogação ou de pedidos de anulação, perfil sociodemográfico, saber "quem votou em quem" individualmente.

## 2. Regras de neutralidade (não negociáveis)

1. Só dados oficiais do TSE + código. **Nenhum número sem fonte.**
2. Toda afirmação é marcada como **FATO** (observado nos dados), **ESTIMATIVA** (modelo, com intervalo) ou **HIPÓTESE** (não testada). Nunca misturar.
3. Os dois candidatos (Lula e Flávio Bolsonaro) recebem o mesmo tratamento: mesmas tabelas, mesma ordem, mesmos verbos, mesmos adjetivos (de preferência nenhum).
4. Estimativas sempre com incerteza e declarando que são estimativas.
5. **Sem causas** (campanha, economia, rejeição) e **sem opinião** sobre a legitimidade do resultado, da prorrogação ou de qualquer ato.
6. Cada seção declara os seus limites.
7. Voto é secreto: nenhum dado aqui liga eleitor a voto. Qualquer ligação entre perfil e voto é inferência agregada.

## 3. Números de referência (para conferir que nada quebrou)

Fonte: totalização oficial TSE, conferida com os CSVs e com o back-end do app Resultados.

- 2º turno: Lula 64.256.232 (51,79% dos válidos) × Flávio 59.826.041 (48,21%). Margem 4.430.191 votos (3,57 p.p. do duelo).
- Abstenção: 19,22% no 2T, 21,08% no 1T.
- Aptos: 158.745.502 registrados; 39 registros de transferência duplicados → 158.745.463 efetivos. Há 423 aptos em 41 seções não instaladas, sem abstenção computada.
- 1º turno, válidos oficiais: 119.300.788.
- Candidato nº 28 (5.246 votos) é contado como **nulo** pelo TSE (campo `vnt`). Essa interpretação é inferida, não documentada. Por isso `analisa_votos_tse_v2_2.py` roda com `--excluir-candidatos 28`.
- Painel da coleta: 28 abrangências (27 UFs + ZZ/exterior), 5.757 municípios, 27 capitais. Coleta validada com 0 erros e painel igual ao CSV.

Se uma alteração mudar esses números, **pare e investigue**; não ajuste o número para bater.

## 4. Estrutura da pasta

```
AnaliseEleicoes/
├─ README.md                          este arquivo
├─ escopo.md                          escopo aprovado (v2) e decisões pendentes
├─ leiame.pdf                         guia de uso anterior (pode estar defasado)
│
├─ coleta_resultados_json.py   v1.1   coleta do back-end do app Resultados (JSON assinado)
├─ analisa_votos_tse_v2_2.py   v2.2   análise dos CSVs oficiais (P1, P2, proxy de P4)
├─ migracao_1t_2t.py           v0.2   P3: estimativa de migração 1T→2T
├─ explora_logs_urna.py        v0.1   explorador do formato dos logs de urna (descartável)
├─ extrai_horarios_urna.py     v0.1   P4: horários dos votos por seção a partir do log da urna
│
├─ saida_json/    saída da coleta (CSVs json_*.csv, coleta_manifesto.csv, cache_bruto/)
├─ saida_v2/      saída da análise dos CSVs (p1_*, p2_*, p4_*, conciliação)
├─ saida_p3/      saída da migração (p3_matriz_e_robustez.csv e demais)
├─ saida_p4/      saída dos horários de urna (p4_*_RR_T1.*)
│
├─ relatorio_eleicoes_2026.html       relatório HTML autônomo (funciona offline)
│
└─ DADOS BRUTOS (não versionar, são grandes):
   ├─ votacao_secao_2026_BR.csv                 ~1 GB, votação por seção
   ├─ detalhe_votacao_secao_2026/               detalhe por seção, um CSV por UF + BR
   └─ bu_imgbu_logjez_rdv_vscmr_2026_1t_RR.zip  260 MB, logs de urna de RR (1T)
```

Pastas `saida_*` são **geradas**; podem ser apagadas e refeitas. Nunca editar saída à mão: mude o script e rode de novo.

## 5. Fontes de dados

### 5.1 Dados Abertos do TSE (CSV)
- Portal: `https://dadosabertos.tse.jus.br`. Download em `https://cdn.tse.jus.br/...`.
- API CKAN (lista de arquivos): `https://dadosabertos.tse.jus.br/api/3/action/package_show?id=<id>`.
- **Votação por seção** (`votacao_secao_2026_*.csv`) e **detalhe da votação por seção** (`detalhe_votacao_secao_2026_*.csv`): Latin-1, separador `;`, tudo entre aspas.
- Chave da seção: `SG_UF + CD_MUNICIPIO + NR_ZONA + NR_SECAO`.
- Estado em 26/10/2026: "Resultados - 2026" só publicado para o **1º turno**. CSVs do 2T e pacotes de urna do 2T **ainda não foram publicados**. Checar de novo antes de assumir.

### 5.2 Back-end do app Resultados (JSON assinado)
- Base: `https://resultados.tse.jus.br/oficial`. Pleito **6257 = 1T**, **6258 = 2T**.
- Arquivos `.jws` (JWS compacto, EdDSA). **A assinatura NÃO é verificada** pelo coletor; só se decodifica o payload. Declare isso em qualquer texto sobre a coleta.
- Cobertura: Brasil, 27 UFs + ZZ, 5.757 municípios.
- É a única fonte com **resultado do 2T por município hoje**.

### 5.3 Pacotes de log de urna (P4)
- Conjunto "Arquivos transmitidos para totalização": `bu_imgbu_logjez_rdv_vscmr_2026_1t_{UF}.zip`, um por UF.
- Dentro: arquivos por seção `o03220{uf}{mun5}{zona4}{secao4}-log.jez` (zip interno com `logd.dat`), além de BU, imagens etc.
- `logd.dat`: TSV com data/hora e mensagens. Eventos usados: `Eleitor foi habilitado`, `O voto do eleitor foi computado`, `Urna pronta para receber votos`, `Operador selecionou: Encerrar votação`.
- O log **não** diz em quem o eleitor votou.

### 5.4 O que NÃO usar
- Nada fora do TSE para números eleitorais (nem pesquisas, nem imprensa, nem redes sociais).
- `DT_RECEBIMENTO_BU_HOR_TSE` (campo da votação por seção) **não é horário de fechamento**: é a chegada do BU no TSE (no 1T, 39,2% de 499.248 seções chegaram depois das 19h). Serve de proxy fraco; **não** use para concluir sobre prorrogação.

## 6. Ambiente e como rodar

- Máquina do João: Windows, Python 3.12.4, pandas 2.3.0, numpy 2.2.6, scipy instalado. Pasta: `C:\Users\ssjoaootavio\Projects\Pessoais\AnaliseEleicoes`.
- Scripts em Python puro (pandas, numpy, scipy; `py7zr` só se aparecer log em 7z). Sem dependência de rede além da coleta.
- Terminal Windows: comandos com `\` nos caminhos. Em Linux/Mac use `/`.
- Reprodutibilidade: os scripts gravam versão, parâmetros e hash do insumo (`fontes_e_parametros.json`, `p3_diagnostico.json`, `p4_resumo_*.json`).

### Ordem de execução do zero

```bash
# 0) Dados brutos: baixar do portal de dados abertos do TSE (CSV por seção e detalhe)

# 1) Coleta do back-end (Brasil, UFs, municípios; 1T e 2T)
python coleta_resultados_json.py --turnos 1 2 --saida saida_json
#    opções úteis: --atualizar, --workers 4, --pausa 0.15, --sem-municipios,
#                  --limite-municipios N (teste), --comparar-csv, --margem-curta-pp, --min-duelo

# 2) Análise dos CSVs oficiais (P1, P2, conciliação, proxy de P4)
python analisa_votos_tse_v2_2.py --excluir-candidatos 28
#    saída: saida_v2/

# 3) P3: migração 1T→2T (estimativa) e teste de validação por simulação
python migracao_1t_2t.py --entrada saida_json\json_p2_municipios_por_turno.csv --saida saida_p3
python migracao_1t_2t.py --validar-simulacao --saida saida_p3

# 4) P4: horários dos votos pela urna (um ou vários pacotes de UF)
python extrai_horarios_urna.py bu_imgbu_logjez_rdv_vscmr_2026_1t_RR.zip ^
    --detalhe detalhe_votacao_secao_2026\detalhe_votacao_secao_2026_BR.csv --saida saida_p4
```

## 7. Scripts: o que cada um faz e o que produz

### `coleta_resultados_json.py` (v1.1)
Baixa os JSON do app Resultados (com cache em `saida_json/cache_bruto/`), valida e monta tabelas. Saídas principais: `json_p1_brasil_por_turno.csv`, `json_p1_uf_por_turno.csv`, `json_p2_municipios_por_turno.csv` e as `*_variacao_1T_2T.csv`, `json_totais_por_escopo.csv`, `json_candidatos_por_escopo.csv`, `coleta_manifesto.csv`, `coleta_erros.csv`, `coleta_resumo.json`.
Cuidado: `CD_MUNICIPIO` é gravado como `Int64` (antes virava float); coluna `CAPITAL` vale `"Sim"`/`"Nao"` (string).

### `analisa_votos_tse_v2_2.py` (v2.2)
Lê os CSVs oficiais. Saída em `saida_v2/`: `p1_*`, `p2_municipios_por_turno.csv`, `votos_por_municipio_candidato.csv`, `conciliacao_votacao_vs_detalhe.csv`, `p4_recebimento_bu_por_faixa.csv`, `p4_resumo_por_turno.csv`, `fontes_e_parametros.json`.

### `migracao_1t_2t.py` (v0.2): P3
- **Modelo:** `y_i = x_i · T`, com `T ≥ 0` e linhas somando 1, por mínimos quadrados ponderados (peso = aptos no 1T), resolvido com SLSQP (scipy). Origens: Lula, Flávio, Outros, Branco/Nulo, Abstenção. Destinos: Lula, Flávio, Branco/Nulo (+Outros do 2T = 0), Abstenção.
- **7 especificações:** Brasil agregado; efeito fixo por UF (desmedianização intra-UF); 5 regiões.
- **Limites determinísticos** por município: `max(0, x+y−1) ≤ fluxo ≤ min(x, y)`. Isso é FATO (aritmética), o resto é ESTIMATIVA.
- **Robustez:** amplitude min–max entre especificações: ≤10 p.p. = robusta (R); ≤25 = moderada (M); acima = X ("não interpretar").
- **Bootstrap** mede só ruído amostral e **sub-cobre** na simulação; não é intervalo de confiança do fluxo. Valores presos em 0 ou 100 podem ser artefato da restrição `T ≥ 0`.
- **Saídas** (`saida_p3/`): `p3_matriz_e_robustez.csv` (36 linhas: 20 no recorte de 5 origens e 16 no de 4), `p3_balanco_por_uf.csv`, `p3_residuos_municipios.csv`, `p3_diagnostico.json` (R² 0,9788), `p3_validacao_simulacao.json`.
- A cobertura do bootstrap na simulação varia entre execuções e versões de numpy (o João obteve 96,7% / 87,5% / 9,2%). O relatório usa os números dele e avisa que variam.
- Fluxos são **proporções estimadas de grupos**, nunca "X% dos eleitores de A votaram em B" como fato individual.

### `extrai_horarios_urna.py` (v0.1): P4
Para cada `-log.jez` do pacote: filtra o dia 04/10/2026, conta votos computados, habilitações, suspensões, reinícios do app; pega horário de pronta, primeiro voto, último voto e encerramento. Valida contra `QT_COMPARECIMENTO` do detalhe por seção. Saídas em `saida_p4/`: `p4_secoes_{UF}_T{n}.csv`, `p4_votos_por_faixa_{UF}_T{n}.csv`, `p4_resumo_{UF}_T{n}.json`, `p4_validacao_maiores_diferencas_{UF}_T{n}.csv`.
O argumento `--data-eleicao` deve ser trocado para `25/10/2026` no 2T. O turno é lido do nome do zip (`_1t_`/`_2t_`).

### `explora_logs_urna.py` (v0.1)
Só para descobrir o formato do log. Não faz parte do pipeline.

## 8. Resultados já estabelecidos

### P1/P2
Painel completo em `saida_json/` e `saida_v2/`, conciliado: JSON e CSV batem.

### P3
Modelo com R² 0,9788. Algumas células são estáveis entre especificações; outras não são identificadas e estão marcadas como X. Ler sempre junto com `ROBUSTEZ` e `CANTO_DO_MODELO_0_OU_100`. Resolução atual: **município**. Quando a votação por seção do 2T sair, refazer por seção (muito mais poder, mas continua sendo inferência ecológica).

### P4 (só RR, 1º turno)
- **FATO:** os logs somam 332.730 votos computados contra 332.772 de comparecimento no CSV (-42, ou 0,01%). 1.519 seções nos dois lados, 3 divergentes (-24, -10, -8), todas com 5 reinícios do app.
- **FATO:** 1,05% dos votos (3.489) ocorreram a partir das 16:00 no relógio da urna; mediana do último voto 15:58; mediana do encerramento 16:02; 16 seções encerraram depois das 17:00 e 6 depois das 18:00; a última às 19:07.
- **HIPÓTESE:** o relógio da urna está na hora local de RR (UTC−4); abrir às 07:00 e fechar às 16:00 locais seria 08:00–17:00 em Brasília. **A confirmar** olhando AC (UTC−5) e SP (UTC−3).
- **Conclusão atual:** NÃO CONCLUSIVO para a prorrogação. Se houve prorrogação, ela só aparece nos logs do 2T, ainda não publicados. O log mede quantos votaram e quando, nunca em quem.

## 9. Armadilhas conhecidas (leia antes de editar)

1. **Encoding:** CSVs do TSE são Latin-1, `;`, aspas. Leitura com `dtype=str` e converter depois.
2. **Sandbox sem acesso ao TSE:** `cdn.tse.jus.br` costuma retornar 403 de ambientes em nuvem. Baixar na máquina do João; não tente contornar.
3. **Candidato 28:** contado como nulo; manter `--excluir-candidatos 28` ao comparar com o oficial.
4. **Municípios:** o código do TSE (`CD_MUNICIPIO`) **não** é o código IBGE. Não juntar com tabelas IBGE sem tabela de correspondência.
5. **Aptos duplicados:** 39 registros de transferência duplicados; use os 158.745.463 efetivos quando precisar do total real.
6. **`CAPITAL`** é `"Sim"`/`"Nao"`. Tratar `"Nao"` como verdadeiro foi um bug real (todos viraram capital).
7. **Relógio da urna ≠ Brasília** até confirmação. Não converter fuso sem checar a UF.
8. **Reinícios do app** podem partir o registro de votos de uma seção; não presumir fraude nem erro, apenas relatar a divergência.
9. **Não usar `pkill -f`** em shell que execute o próprio comando (derruba a sessão).
10. **Não tratar o bootstrap como intervalo de confiança.** Ele sub-cobre.
11. **Não escrever "migraram", "transferiram", "traíram"** em texto sobre P3 sem o rótulo ESTIMATIVA. Preferir "estimativa de composição do voto".
12. **Não inferir causa.** Se o dado mostra diferença, descreva a diferença.

## 10. Convenções para trabalhar no projeto

- Português do Brasil em textos e nomes de coluna; sem emojis; números em formato brasileiro nos textos (`1.234,5`), ponto decimal nos CSVs.
- Colunas em CAIXA_ALTA com `_`, como nos CSVs do TSE.
- Cada script tem `VERSAO` no topo; aumente ao mudar comportamento e registre o que mudou no docstring.
- Todo script grava na saída: versão, parâmetros e o hash (sha256) do insumo principal.
- Mudou um script? Rode do zero e compare com a seção 3. Anexe as validações a `saida_*`.
- Tudo que for dito no relatório HTML precisa ter origem em um CSV de `saida_*`. O HTML não guarda número "à mão".
- Rótulos obrigatórios nos textos: **FATO**, **ESTIMATIVA**, **HIPÓTESE**.
- Formato de decisão que o João usa: tabela `Decisão | Próximos passos | Dono | Data`.

## 11. Relatório HTML

`relatorio_eleicoes_2026.html`: arquivo único (~570 KB), funciona offline. Seções: Brasil, UFs, Municípios, Migração (P3), Horário (P4), Fontes e limites. Os dados estão embutidos (JSON) e **estáticos**: é preciso regenerar quando chegarem os CSVs e pacotes do 2T e quando houver mais UFs no P4. Gráficos em SVG/canvas puros, tema claro/escuro, sem dependências externas. O gerador não faz parte desta pasta (vive na sessão do Claude); se for necessário mantê-lo aqui, peça para exportá-lo (`mkdata.py` + `page_body.html` + `build.py`).

## 12. Pendências e próximos passos

| Item | Detalhe | Dono |
|---|---|---|
| Fuso do relógio da urna | Baixar pacotes 1T de **AC** e **SP**, rodar `extrai_horarios_urna.py`, comparar abertura/fechamento | João baixa; agente roda |
| P4 nacional | Se valer o esforço: 28 pacotes de UF (grandes) | João |
| 2º turno | Monitorar publicação de CSVs e pacotes de urna do 2T; rodar `analisa_votos_tse_v2_2.py`, `migracao_1t_2t.py` (por seção) e `extrai_horarios_urna.py --data-eleicao 25/10/2026` | Agente |
| Relatório HTML | Atualizar a seção Horário e regenerar com dados do 2T | Agente |
| Revisão da página | Aguardar comentários do João (textos, ordem, o que sai) | João |
| Decisões de escopo | Formato final (relatório+CSV+código ou painel), público ou pessoal, granularidade da P3, P4 agora ou depois | João |

## 13. Sobre este projeto

Dados: TSE (domínio público). Análise e código: João Santos com apoio de Claude. Nada aqui é opinião política; qualquer leitor pode refazer tudo com os scripts desta pasta. Se encontrar um erro, abra o `p*_resumo`/`diagnostico` correspondente e compare com a seção 3.
