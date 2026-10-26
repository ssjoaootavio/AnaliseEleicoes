#!/usr/bin/env python3
"""
Analise de votos para presidente 2026 (TSE) - versao 2.2.

Novidades da v2.2 (sobre a v2.1):
  - Candidato excluido (--excluir-candidatos): o detalhe do TSE conta esses votos como NOMINAIS,
    entao a conciliacao os soma a nominais (antes aparecia divergencia falsa). O resultado oficial
    do TSE os conta como NULOS: coluna NULO_TOTAL = NULO + EXCLUIDO. No 1o turno de 2026, o
    candidato 28 (5.246 votos) explica a diferenca para o total oficial de validos (119.300.788):
    rode com --excluir-candidatos 28 para reproduzir o oficial.

Novidades da v2.1 (sobre a v2):
  - P2 parte do detalhe: municipios sem nenhum voto (secoes nao instaladas, ex.: exterior)
    deixam de sumir. Municipios passam a somar exatamente a UF (inclui aptos e abstencoes).
  - Colunas SECOES, SECOES_NAO_INSTALADAS e APTOS_NAO_INSTALADOS: o TSE registra abstencao 0
    em secao nao instalada, entao APTOS pode superar COMPARECIMENTO + ABSTENCOES.
  - Margem curta definida sem ambiguidade: MARGEM_DUELO_PP = |Lula - Flavio| no duelo, em
    pontos percentuais (opcao --margem-curta-pp, padrao 10). AMOSTRA_PEQUENA marca duelos
    com poucos votos (--min-duelo, padrao 100).
  - P4 (horario de recebimento do BU) sai marcado como NAO CONCLUSIVO e informa o maior
    intervalo sem recebimento. O campo mede chegada ao TSE, nao fechamento da secao.
  - p1_candidatos_brasil_por_turno.csv: votos por candidato no Brasil, para comparar com o
    resultado oficial do TSE.
  - fontes_e_parametros.json: arquivos de entrada (tamanho, SHA-256, data de geracao),
    parametros, versoes e contagens, para reproducao.
  - Validacoes do detalhe: comparecimento = nominais + brancos + nulos (+ anulados).

Le DOIS arquivos abertos do TSE (so presidente, cargo 1):
  - votacao_secao_2026_BR.csv           (votos por candidato, por secao)
  - detalhe_votacao_secao_2026_*.csv    (aptos, comparecimento, abstencao, brancos, nulos)

Uso:
    python analisa_votos_tse_v2.py votacao_secao_2026_BR.csv --detalhe detalhe_votacao_secao_2026_BR.csv

Opcoes:
    --saida PASTA              pasta de saida (padrao: saida_v2)
    --excluir-candidatos 28    numeros de candidatos cujos votos NAO contam como validos
                               (o script sugere quando achar divergencia com o detalhe)
    --margem-curta-pp 10       municipio de margem curta: |Lula - Flavio| no duelo <= X pontos
                               percentuais (10 equivale a Lula entre 45% e 55% no duelo)
    --min-duelo 100            abaixo disso (Lula+Flavio) o municipio e AMOSTRA_PEQUENA
    --sem-hash                 nao calcula SHA-256 dos arquivos de entrada (mais rapido)
    --secoes                   grava tabela por secao do detalhe (aptos, abstencao, horario)
    --secao-candidato          grava votos por candidato em cada secao (base do P3)
    --nrows N                  le so as N primeiras linhas de cada arquivo (teste)
    --encoding latin1          padrao do TSE (Latin 1)

Requisitos: Python 3.9+ e pandas.
"""
import sys
import time
import traceback

T0 = time.time()


def dbg(msg):
    print("[{:7.1f}s] {}".format(time.time() - T0, msg), flush=True)


if sys.version_info < (3, 9):
    print("ERRO: Python " + sys.version.split()[0] + " e antigo. Use 3.9 ou superior.")
    sys.exit(1)

import argparse
import hashlib
import json
import os
import unicodedata
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

VERSAO = "2.2"
LULA, FLAVIO = 13, 22
BRANCO, NULO, ANULADO = 95, 96, 97
CATS = ["LULA", "FLAVIO", "OUTROS", "EXCLUIDO", "BRANCO", "NULO", "ANULADO"]
UFS_VALIDAS = {
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT",
    "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP",
    "TO", "ZZ",
}
CAPITAIS = {
    "AC": "RIO BRANCO", "AL": "MACEIO", "AP": "MACAPA", "AM": "MANAUS",
    "BA": "SALVADOR", "CE": "FORTALEZA", "DF": "BRASILIA", "ES": "VITORIA",
    "GO": "GOIANIA", "MA": "SAO LUIS", "MT": "CUIABA", "MS": "CAMPO GRANDE",
    "MG": "BELO HORIZONTE", "PA": "BELEM", "PB": "JOAO PESSOA", "PR": "CURITIBA",
    "PE": "RECIFE", "PI": "TERESINA", "RJ": "RIO DE JANEIRO", "RN": "NATAL",
    "RS": "PORTO ALEGRE", "RO": "PORTO VELHO", "RR": "BOA VISTA",
    "SC": "FLORIANOPOLIS", "SP": "SAO PAULO", "SE": "ARACAJU", "TO": "PALMAS",
}
METRICAS = ["APTOS", "COMPARECIMENTO", "ABSTENCOES", "BRANCO", "NULO",
            "LULA", "FLAVIO", "OUTROS"]
PCTS = ["PCT_LULA_DUELO", "PCT_LULA_VALIDOS", "PCT_FLAVIO_VALIDOS", "PCT_ABSTENCAO"]


def sem_acento(s):
    s = unicodedata.normalize("NFKD", str(s))
    return "".join(c for c in s if not unicodedata.combining(c)).upper().strip()


def falha(msg):
    dbg("ERRO: " + msg)
    sys.exit(1)


# ----------------------------------------------------------------------------
# Leitura: votos por candidato
# ----------------------------------------------------------------------------
def tipo_votavel(nr, excluidos):
    conds = [nr == LULA, nr == FLAVIO, nr == BRANCO, nr == NULO, nr == ANULADO,
             nr.isin(list(excluidos)) if excluidos else pd.Series(False, index=nr.index)]
    vals = ["LULA", "FLAVIO", "BRANCO", "NULO", "ANULADO", "EXCLUIDO"]
    return np.select(conds, vals, default="OUTROS")


def ler_votacao(caminho, enc, nrows, excluidos, quer_secao):
    cols = ["NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO", "NR_ZONA",
            "NR_SECAO", "CD_CARGO", "NR_VOTAVEL", "NM_VOTAVEL", "QT_VOTOS"]
    dtypes = {"NR_TURNO": "int8", "SG_UF": "category", "CD_MUNICIPIO": "int32",
              "NM_MUNICIPIO": "category", "NR_ZONA": "int16", "NR_SECAO": "int16",
              "CD_CARGO": "int8", "NR_VOTAVEL": "int32", "NM_VOTAVEL": "category",
              "QT_VOTOS": "int32"}
    leitor = pd.read_csv(caminho, sep=";", encoding=enc, usecols=cols, dtype=dtypes,
                         chunksize=500000, nrows=nrows)
    muni, secs, ufs, total = [], [], set(), 0
    for i, p in enumerate(leitor, 1):
        p = p[p["CD_CARGO"] == 1]
        if p.empty:
            continue
        total += len(p)
        if (p["QT_VOTOS"] < 0).any():
            falha("QT_VOTOS negativo (#NULO=-1 ou #NE=-3 segundo o leiame do TSE). "
                  "Confira o arquivo antes de seguir.")
        ufs.update(p["SG_UF"].astype(str).unique())
        p = p.assign(TIPO=tipo_votavel(p["NR_VOTAVEL"], excluidos))
        chave = ["NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO",
                 "NR_VOTAVEL", "NM_VOTAVEL", "TIPO"]
        muni.append(p.groupby(chave, observed=True, as_index=False)["QT_VOTOS"].sum())
        if quer_secao:
            secs.append(p.groupby(["NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NR_ZONA",
                                   "NR_SECAO", "NR_VOTAVEL"], observed=True,
                                  as_index=False)["QT_VOTOS"].sum())
        dbg("  votacao parte {}: {:,} linhas de presidente (acumulado {:,})".format(
            i, len(p), total))
    if not muni:
        falha("nenhuma linha de presidente (CD_CARGO == 1) na votacao.")
    inesperadas = sorted(ufs - UFS_VALIDAS)
    if inesperadas:
        dbg("ATENCAO: UF inesperada na votacao: {} (leiame cita BR e VT)".format(inesperadas))
    mc = pd.concat(muni)
    for c in ("SG_UF", "NM_MUNICIPIO", "NM_VOTAVEL", "TIPO"):
        mc[c] = mc[c].astype(str)
    chave = ["NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO",
             "NR_VOTAVEL", "NM_VOTAVEL", "TIPO"]
    mc = mc.groupby(chave, as_index=False)["QT_VOTOS"].sum()
    sc = None
    if quer_secao:
        sc = pd.concat(secs)
        sc["SG_UF"] = sc["SG_UF"].astype(str)
        sc = sc.groupby(["NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO",
                         "NR_VOTAVEL"], as_index=False)["QT_VOTOS"].sum()
    return mc, sc


# ----------------------------------------------------------------------------
# Leitura: detalhe da apuracao por secao
# ----------------------------------------------------------------------------
def ler_detalhe(caminho, enc, nrows):
    cab = pd.read_csv(caminho, sep=";", encoding=enc, nrows=0).columns.tolist()
    base = ["NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "CD_CARGO",
            "QT_APTOS", "QT_COMPARECIMENTO", "QT_ABSTENCOES", "QT_VOTOS_NOMINAIS",
            "QT_VOTOS_BRANCOS", "QT_VOTOS_NULOS"]
    opc = ["NM_MUNICIPIO", "QT_VOTOS_LEGENDA", "QT_VOTOS_ANULADOS_APU_SEP",
           "ST_SECAO_INSTALADA", "ST_SECAO_ANULADA", "DT_RECEBIMENTO_BU_HOR_TSE"]
    faltam = [c for c in base if c not in cab]
    if faltam:
        falha("colunas ausentes no detalhe: {}".format(faltam))
    cols = base + [c for c in opc if c in cab]
    dtypes = {"NR_TURNO": "int8", "SG_UF": "category", "CD_MUNICIPIO": "int32",
              "NR_ZONA": "int16", "NR_SECAO": "int16", "CD_CARGO": "int8"}
    for c in cols:
        if c.startswith("QT_"):
            dtypes[c] = "int32"
        elif c.startswith("ST_") or c.startswith("DT_"):
            dtypes[c] = "string"
        elif c == "NM_MUNICIPIO":
            dtypes[c] = "category"
    leitor = pd.read_csv(caminho, sep=";", encoding=enc, usecols=cols, dtype=dtypes,
                         chunksize=500000, nrows=nrows)
    partes, total = [], 0
    for i, p in enumerate(leitor, 1):
        p = p[p["CD_CARGO"] == 1]
        if p.empty:
            continue
        total += len(p)
        qt = [c for c in cols if c.startswith("QT_")]
        if (p[qt] < 0).any().any():
            falha("valor negativo no detalhe (#NULO=-1 ou #NE=-3). Confira o arquivo.")
        partes.append(p)
        dbg("  detalhe parte {}: {:,} secoes de presidente (acumulado {:,})".format(
            i, len(p), total))
    if not partes:
        falha("nenhuma linha de presidente (CD_CARGO == 1) no detalhe. "
              "O arquivo pode ser so de outros cargos ou estar incompleto.")
    d = pd.concat(partes)
    d["SG_UF"] = d["SG_UF"].astype(str)
    if "NM_MUNICIPIO" in d.columns:
        d["NM_MUNICIPIO"] = d["NM_MUNICIPIO"].astype(str)
    for st, nome in (("ST_SECAO_INSTALADA", "NAO_INSTALADA"), ("ST_SECAO_ANULADA", "ANULADA")):
        if st in d.columns:
            txt = d[st].fillna("")
            alvo = "NAO" if nome == "NAO_INSTALADA" else "SIM"
            mapa = {v: sem_acento(v) == alvo for v in txt.unique()}
            d[nome] = txt.map(mapa).astype(bool)
    dup = d.duplicated(["NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO"]).sum()
    if dup:
        dbg("ATENCAO: {:,} secoes duplicadas no detalhe (chave turno+UF+municipio+zona+secao)"
            .format(dup))
    return d.rename(columns={
        "QT_APTOS": "APTOS", "QT_COMPARECIMENTO": "COMPARECIMENTO",
        "QT_ABSTENCOES": "ABSTENCOES", "QT_VOTOS_NOMINAIS": "DET_NOMINAIS",
        "QT_VOTOS_BRANCOS": "DET_BRANCOS", "QT_VOTOS_NULOS": "DET_NULOS",
        "QT_VOTOS_LEGENDA": "DET_LEGENDA", "QT_VOTOS_ANULADOS_APU_SEP": "DET_ANULADOS"})


# ----------------------------------------------------------------------------
# Tabelas
# ----------------------------------------------------------------------------
def derivar(t):
    nz = lambda s: s.replace(0, np.nan)
    t["VALIDOS"] = t["LULA"] + t["FLAVIO"] + t["OUTROS"]
    t["DUELO"] = t["LULA"] + t["FLAVIO"]
    t["PCT_LULA_VALIDOS"] = t["LULA"] / nz(t["VALIDOS"]) * 100
    t["PCT_FLAVIO_VALIDOS"] = t["FLAVIO"] / nz(t["VALIDOS"]) * 100
    t["PCT_LULA_DUELO"] = t["LULA"] / nz(t["DUELO"]) * 100
    t["MARGEM_LULA_MENOS_FLAVIO"] = t["LULA"] - t["FLAVIO"]
    if "NULO" in t.columns and "EXCLUIDO" in t.columns:
        t["NULO_TOTAL"] = t["NULO"] + t["EXCLUIDO"]   # igual ao total de nulos do TSE
    if "APTOS" in t.columns:
        t["PCT_ABSTENCAO"] = t["ABSTENCOES"] / nz(t["APTOS"]) * 100
    return t.round(2)


def cat_wide(mc, chaves):
    w = mc.pivot_table(index=chaves, columns="TIPO", values="QT_VOTOS",
                       aggfunc="sum", fill_value=0).reset_index()
    for c in CATS:
        if c not in w.columns:
            w[c] = 0
    return w[chaves + CATS]


COLS_DET = ["APTOS", "COMPARECIMENTO", "ABSTENCOES", "SECOES",
            "SECOES_NAO_INSTALADAS", "APTOS_NAO_INSTALADOS"]


def somas_detalhe(det, chaves):
    """Soma do detalhe por chave. Inclui contagem de secoes e de secoes nao instaladas."""
    d = det[chaves + ["APTOS", "COMPARECIMENTO", "ABSTENCOES"]].copy()
    d["SECOES"] = 1
    if "NAO_INSTALADA" in det.columns:
        ni = det["NAO_INSTALADA"].values
        d["SECOES_NAO_INSTALADAS"] = ni.astype(int)
        d["APTOS_NAO_INSTALADOS"] = np.where(ni, d["APTOS"].values, 0)
    else:
        d["SECOES_NAO_INSTALADAS"] = 0
        d["APTOS_NAO_INSTALADOS"] = 0
    return d.groupby(chaves, as_index=False)[COLS_DET].sum()


def juntar_detalhe(votos, det, chaves):
    """Junta votos e detalhe por OUTER join: quem tem secao mas nenhum voto (secao nao
    instalada, exterior) continua na tabela, com votos = 0. Era o defeito do p2 na v2."""
    m = votos.merge(somas_detalhe(det, chaves), on=chaves, how="outer")
    for c in CATS:
        m[c] = m[c].fillna(0).astype("int64")
    sem_det = m["APTOS"].isna().sum()
    if sem_det:
        dbg("ATENCAO: {:,} linhas com votos mas sem secao no detalhe (chave {})".format(
            sem_det, chaves))
    return m


def preenche_nomes(mun, det):
    """Municipio so existente no detalhe nao tem nome vindo da votacao: usa o do detalhe."""
    if "NM_MUNICIPIO" in det.columns:
        nomes = (det[["SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO"]].drop_duplicates(
            ["SG_UF", "CD_MUNICIPIO"]).rename(columns={"NM_MUNICIPIO": "_NM_DET"}))
        mun = mun.merge(nomes, on=["SG_UF", "CD_MUNICIPIO"], how="left")
        mun["NM_MUNICIPIO"] = mun["NM_MUNICIPIO"].fillna(mun["_NM_DET"])
        mun = mun.drop(columns="_NM_DET")
    mun["NM_MUNICIPIO"] = mun["NM_MUNICIPIO"].fillna("(SEM NOME)")
    return mun


def marca_margem(t, limite_pp, min_duelo):
    """MARGEM_DUELO_PP = |Lula - Flavio| / (Lula + Flavio) * 100, em pontos percentuais.
    MARGEM_CURTA: margem <= limite. AMOSTRA_PEQUENA: duelo com menos de min_duelo votos
    (percentuais de municipios assim variam muito com poucos votos)."""
    duelo = (t["LULA"] + t["FLAVIO"]).replace(0, np.nan)
    t["MARGEM_DUELO_PP"] = ((t["LULA"] - t["FLAVIO"]).abs() / duelo * 100).round(2)
    t["MARGEM_CURTA"] = (t["MARGEM_DUELO_PP"] <= limite_pp).fillna(False)
    t["AMOSTRA_PEQUENA"] = (t["LULA"] + t["FLAVIO"]) < min_duelo
    return t


def valida_detalhe(det):
    """Identidades que o proprio TSE deveria respeitar. Avisa, nao interrompe."""
    nominais = det["DET_NOMINAIS"] + det["DET_BRANCOS"] + det["DET_NULOS"]
    for extra in ("DET_ANULADOS",):
        if extra in det.columns:
            nominais = nominais + det[extra]
    n1 = int((nominais != det["COMPARECIMENTO"]).sum())
    dbg("VALIDACAO detalhe: comparecimento != nominais+brancos+nulos(+anulados) em {:,} "
        "secoes".format(n1))
    dif = det["APTOS"] - det["COMPARECIMENTO"] - det["ABSTENCOES"]
    n2 = int((dif != 0).sum())
    if "NAO_INSTALADA" in det.columns:
        ni = det["NAO_INSTALADA"]
        dbg("VALIDACAO detalhe: aptos != comparecimento+abstencoes em {:,} secoes "
            "({:,} delas nao instaladas; {:,} eleitores aptos nelas sem abstencao "
            "registrada)".format(n2, int(((dif != 0) & ni).sum()),
                                 int(det.loc[ni, "APTOS"].sum())))
        dbg("VALIDACAO detalhe: {:,} secoes nao instaladas | {:,} secoes anuladas".format(
            int(ni.sum()), int(det["ANULADA"].sum()) if "ANULADA" in det.columns else 0))
    else:
        dbg("VALIDACAO detalhe: aptos != comparecimento+abstencoes em {:,} secoes".format(n2))
    if int((det["COMPARECIMENTO"] > det["APTOS"]).sum()):
        dbg("ATENCAO: ha secoes com comparecimento maior que aptos")


def variacao(t, idx):
    if not {1, 2}.issubset(set(t["NR_TURNO"].unique())):
        return None
    cols = [c for c in METRICAS + PCTS if c in t.columns]
    w = t.pivot_table(index=idx, columns="NR_TURNO", values=cols, aggfunc="first")
    w.columns = ["{}_{}T".format(c, int(n)) for c, n in w.columns]
    for c in cols:
        w["DELTA_" + c] = (w[c + "_2T"] - w[c + "_1T"]).round(2)
    return w.reset_index()


def mostrar(df, titulo, cols=None, n=None):
    print("\n=== " + titulo + " ===", flush=True)
    d = df if cols is None else df[[c for c in cols if c in df.columns]]
    print((d if n is None else d.head(n)).to_string(index=False), flush=True)


def conciliar(mc, det, saida):
    """Compara votos da votacao_secao com os totais do detalhe, por turno e UF."""
    a = cat_wide(mc, ["NR_TURNO", "SG_UF"])
    # o detalhe do TSE conta TODOS os votos nominais, inclusive os do candidato excluido
    # dos validos (que o resultado oficial classifica como nulos): somamos EXCLUIDO aqui
    a["VOT_CANDIDATOS"] = a["LULA"] + a["FLAVIO"] + a["OUTROS"] + a["EXCLUIDO"]
    cols = {"DET_NOMINAIS": "sum", "DET_BRANCOS": "sum", "DET_NULOS": "sum"}
    if "DET_ANULADOS" in det.columns:
        cols["DET_ANULADOS"] = "sum"
    b = det.groupby(["NR_TURNO", "SG_UF"], as_index=False).agg(cols)
    c = a.merge(b, on=["NR_TURNO", "SG_UF"], how="outer").fillna(0)
    c["DIF_NOMINAIS"] = c["VOT_CANDIDATOS"] - c["DET_NOMINAIS"]
    c["DIF_BRANCOS"] = c["BRANCO"] - c["DET_BRANCOS"]
    c["DIF_NULOS"] = c["NULO"] - c["DET_NULOS"]
    if "DET_ANULADOS" in c.columns:
        c["DIF_ANULADOS"] = c["ANULADO"] - c["DET_ANULADOS"]
    c.to_csv(saida / "conciliacao_votacao_vs_detalhe.csv", index=False, sep=";",
             encoding="utf-8-sig")
    difs = [x for x in c.columns if x.startswith("DIF_")]
    for turno, g in c.groupby("NR_TURNO"):
        tot = g[difs].sum()
        if (tot == 0).all():
            dbg("CONCILIACAO turno {}: OK (votacao = detalhe em nominais, brancos, nulos"
                "{})".format(int(turno), ", anulados" if "DIF_ANULADOS" in difs else ""))
            continue
        dbg("CONCILIACAO turno {}: DIVERGENCIA {}".format(int(turno), tot.to_dict()))
        dbg("  -> confira o arquivo: votacao e detalhe deveriam coincidir em nominais, brancos e nulos")
    return c


def analisa_horario(det, saida):
    """P4. STATUS: NAO CONCLUSIVO. DT_RECEBIMENTO_BU_HOR_TSE e a hora em que o boletim chegou
    ao TSE, nao a hora em que a secao fechou nem a hora de cada voto. No 1o turno, com
    fechamento normal, cerca de 4 em cada 10 secoes chegam depois das 19h, e o recebimento
    pode parar e voltar em lote. No 2o turno o recebimento foi pausado ate depois das 19h."""
    col = "DT_RECEBIMENTO_BU_HOR_TSE"
    if col not in det.columns:
        dbg("Detalhe sem coluna de horario de recebimento do BU: teste P4 pulado.")
        return
    rec = pd.to_datetime(det[col], format="%d/%m/%Y %H:%M:%S", errors="coerce")
    d = pd.DataFrame({"NR_TURNO": det["NR_TURNO"].values, "REC": rec.values}).dropna()
    if d.empty:
        dbg("Horario de recebimento vazio: teste P4 pulado.")
        return
    d["FAIXA_30MIN"] = d["REC"].dt.floor("30min").dt.strftime("%d/%m %H:%M")
    tab = d.groupby(["NR_TURNO", "FAIXA_30MIN"]).size().rename("SECOES").reset_index()
    tab.to_csv(saida / "p4_recebimento_bu_por_faixa.csv", index=False, sep=";",
               encoding="utf-8-sig")
    print("\n=== P4: HORARIO DE RECEBIMENTO DO BU (hora do TSE) - NAO CONCLUSIVO ===",
          flush=True)
    resumo = []
    for turno, g in d.groupby("NR_TURNO"):
        dia = g["REC"].dt.date.mode().iloc[0]
        gd = g[g["REC"].dt.date == dia]
        p19 = (gd["REC"].dt.hour >= 19).mean() * 100
        # maior intervalo sem nenhum recebimento entre 17h30 e 22h (minuto a minuto)
        minutos = gd["REC"].dt.floor("min").drop_duplicates().sort_values()
        ini_j = pd.Timestamp(dia) + pd.Timedelta(hours=17, minutes=30)
        fim_j = pd.Timestamp(dia) + pd.Timedelta(hours=22)
        jan = minutos[(minutos >= ini_j) & (minutos <= fim_j)].values
        gap_min, gap_ini, gap_fim = 0, None, None
        if len(jan) > 1:
            difs = np.diff(jan).astype("timedelta64[m]").astype(int)
            k = int(difs.argmax())
            gap_min = int(difs[k])
            gap_ini = pd.Timestamp(jan[k]).strftime("%H:%M")
            gap_fim = pd.Timestamp(jan[k + 1]).strftime("%H:%M")
        print("turno {}: {:,} secoes | primeiro {} | mediana {} | p95 {} | ultimo {} | "
              "{:.1f}% recebidas a partir das 19h no dia {} | maior intervalo sem "
              "recebimento (17h30-22h): {} min{}".format(
                  int(turno), len(g), g["REC"].min().strftime("%d/%m %H:%M"),
                  g["REC"].median().strftime("%d/%m %H:%M"),
                  g["REC"].quantile(0.95).strftime("%d/%m %H:%M"),
                  g["REC"].max().strftime("%d/%m %H:%M"), p19, dia, gap_min,
                  " (das {} as {})".format(gap_ini, gap_fim) if gap_min >= 10 else ""),
              flush=True)
        resumo.append({"NR_TURNO": int(turno), "SECOES": len(g), "DIA_PRINCIPAL": str(dia),
                       "PCT_RECEBIDAS_APOS_19H": round(p19, 1),
                       "MAIOR_INTERVALO_SEM_RECEBIMENTO_MIN": gap_min,
                       "INTERVALO_INICIO": gap_ini, "INTERVALO_FIM": gap_fim})
    pd.DataFrame(resumo).to_csv(saida / "p4_resumo_por_turno.csv", index=False, sep=";",
                                encoding="utf-8-sig")
    print("STATUS P4: NAO CONCLUSIVO. O campo mede a chegada do boletim ao TSE, nao o "
          "fechamento da secao: nao serve para contar votos dados depois das 17h. "
          "Outra fonte seria necessaria (boletins de urna originais com horario de "
          "abertura e encerramento).", flush=True)


def tabela_candidatos(mc, saida):
    """Votos por candidato no Brasil, para comparar com o resultado oficial do TSE."""
    c = mc.groupby(["NR_TURNO", "NR_VOTAVEL", "NM_VOTAVEL", "TIPO"],
                   as_index=False)["QT_VOTOS"].sum()
    val = c[c["TIPO"].isin(["LULA", "FLAVIO", "OUTROS"])]
    tot = val.groupby("NR_TURNO")["QT_VOTOS"].sum().rename("TOTAL_CANDIDATOS_TURNO")
    c = c.merge(tot, on="NR_TURNO", how="left")
    c["PCT_SOBRE_CANDIDATOS"] = np.where(
        c["TIPO"].isin(["LULA", "FLAVIO", "OUTROS"]),
        (c["QT_VOTOS"] / c["TOTAL_CANDIDATOS_TURNO"] * 100).round(2), np.nan)
    c = c.sort_values(["NR_TURNO", "QT_VOTOS"], ascending=[True, False])
    c.to_csv(saida / "p1_candidatos_brasil_por_turno.csv", index=False, sep=";",
             encoding="utf-8-sig")
    return c


def _sha256(caminho):
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def info_fonte(caminho, enc, com_hash):
    p = Path(caminho)
    r = {"arquivo": p.name, "tamanho_bytes": p.stat().st_size}
    try:
        h = pd.read_csv(caminho, sep=";", encoding=enc, nrows=1, dtype=str,
                        usecols=["DT_GERACAO", "HH_GERACAO"])
        r["DT_GERACAO"], r["HH_GERACAO"] = h.iloc[0, 0], h.iloc[0, 1]
    except Exception as e:  # cabecalho diferente: nao impede a analise
        r["DT_GERACAO"] = "indisponivel ({})".format(type(e).__name__)
    r["sha256"] = _sha256(caminho) if com_hash else "nao calculado (--sem-hash)"
    return r


def grava_fontes(a, saida, mc, det, com_hash):
    j = {
        "versao_script": VERSAO,
        "executado_em": datetime.now().isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "pandas": pd.__version__,
        "parametros": {k: v for k, v in vars(a).items()},
        "fontes": {"votacao_secao": info_fonte(a.votacao, a.encoding, com_hash)},
        "turnos_votacao": sorted(int(t) for t in mc["NR_TURNO"].unique()),
    }
    if a.detalhe:
        j["fontes"]["detalhe_votacao_secao"] = info_fonte(a.detalhe, a.encoding, com_hash)
    if det is not None:
        j["turnos_detalhe"] = sorted(int(t) for t in det["NR_TURNO"].unique())
        j["secoes_por_turno"] = {str(int(t)): int(n) for t, n in
                                 det.groupby("NR_TURNO").size().items()}
    with open(saida / "fontes_e_parametros.json", "w", encoding="utf-8") as f:
        json.dump(j, f, ensure_ascii=False, indent=2, default=str)
    dbg("Gravado fontes_e_parametros.json")


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("votacao")
    ap.add_argument("--detalhe")
    ap.add_argument("--saida", default="saida_v2")
    ap.add_argument("--excluir-candidatos", type=int, nargs="*", default=[])
    ap.add_argument("--margem-curta-pp", type=float, default=10.0)
    ap.add_argument("--min-duelo", type=int, default=100)
    ap.add_argument("--sem-hash", action="store_true")
    ap.add_argument("--secoes", action="store_true")
    ap.add_argument("--secao-candidato", action="store_true")
    ap.add_argument("--nrows", type=int, default=None)
    ap.add_argument("--encoding", default="latin1")
    a = ap.parse_args()
    dbg("Script v{} | Python {} | opcoes: {}".format(VERSAO, sys.version.split()[0], vars(a)))

    for f in (a.votacao, a.detalhe):
        if f and not os.path.exists(f):
            falha("arquivo nao encontrado: " + f)
    saida = Path(a.saida)
    saida.mkdir(parents=True, exist_ok=True)
    excl = set(a.excluir_candidatos)

    dbg("Lendo votacao por secao...")
    mc, sc = ler_votacao(a.votacao, a.encoding, a.nrows, excl, a.secao_candidato)
    turnos_v = sorted(mc["NR_TURNO"].unique().tolist())
    dbg("Turnos na votacao: {}".format(turnos_v))

    det = None
    if a.detalhe:
        dbg("Lendo detalhe por secao...")
        det = ler_detalhe(a.detalhe, a.encoding, a.nrows)
        turnos_d = sorted(det["NR_TURNO"].unique().tolist())
        dbg("Turnos no detalhe: {}".format(turnos_d))
        if turnos_d != turnos_v:
            dbg("ATENCAO: turnos diferentes entre votacao {} e detalhe {}. "
                "Comparacoes usam so o que existe nos dois.".format(turnos_v, turnos_d))
        valida_detalhe(det)
        conciliar(mc, det, saida)

    mc.to_csv(saida / "votos_por_municipio_candidato.csv", index=False, sep=";",
              encoding="utf-8-sig")

    # ---- P1: Brasil e UF ----
    cat_uf = cat_wide(mc, ["NR_TURNO", "SG_UF"])
    uf = cat_uf.copy()
    if det is not None:
        uf = juntar_detalhe(uf, det, ["NR_TURNO", "SG_UF"])
    uf = derivar(uf).sort_values(["NR_TURNO", "SG_UF"])
    uf.to_csv(saida / "p1_uf_por_turno.csv", index=False, sep=";", encoding="utf-8-sig")

    br = uf.groupby("NR_TURNO", as_index=False)[
        CATS + [c for c in COLS_DET if c in uf.columns]].sum()
    br = derivar(br)
    br.to_csv(saida / "p1_brasil_por_turno.csv", index=False, sep=";", encoding="utf-8-sig")
    mostrar(br, "P1: BRASIL POR TURNO (inclui exterior)",
            ["NR_TURNO", "APTOS", "COMPARECIMENTO", "ABSTENCOES", "PCT_ABSTENCAO",
             "LULA", "FLAVIO", "OUTROS", "EXCLUIDO", "BRANCO", "NULO", "ANULADO",
             "PCT_LULA_VALIDOS", "PCT_FLAVIO_VALIDOS"])
    mostrar(uf, "P1: UF POR TURNO (ZZ = exterior)",
            ["SG_UF", "NR_TURNO", "LULA", "FLAVIO", "OUTROS", "BRANCO", "NULO",
             "ABSTENCOES", "PCT_ABSTENCAO", "PCT_LULA_DUELO"])

    cand = tabela_candidatos(mc, saida)
    mostrar(cand[cand["TIPO"].isin(["LULA", "FLAVIO", "OUTROS"])],
            "P1: VOTOS POR CANDIDATO NO BRASIL (compare com o resultado oficial do TSE)",
            ["NR_TURNO", "NR_VOTAVEL", "NM_VOTAVEL", "QT_VOTOS", "PCT_SOBRE_CANDIDATOS"])

    br["ESCOPO"] = "BRASIL"
    vb = variacao(br, ["ESCOPO"])
    vu = variacao(uf, ["SG_UF"])
    if vu is not None:
        vb.to_csv(saida / "p1_brasil_variacao_1T_2T.csv", index=False, sep=";",
                  encoding="utf-8-sig")
        vu.to_csv(saida / "p1_uf_variacao_1T_2T.csv", index=False, sep=";",
                  encoding="utf-8-sig")
        mostrar(vu.sort_values("DELTA_LULA", ascending=False),
                "P1: VARIACAO 1T -> 2T POR UF (ordenado por ganho de votos de Lula)",
                ["SG_UF", "DELTA_LULA", "DELTA_FLAVIO", "DELTA_BRANCO", "DELTA_NULO",
                 "DELTA_ABSTENCOES", "DELTA_PCT_LULA_DUELO"])
    else:
        dbg("So ha um turno nos dados: sem variacao 1T -> 2T.")

    # ---- P2: municipios ----
    ids = ["NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO"]
    mun = cat_wide(mc, ids)
    if det is not None:
        mun = juntar_detalhe(mun.drop(columns="NM_MUNICIPIO").merge(
            mc[["NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO"]].drop_duplicates(
                ["NR_TURNO", "SG_UF", "CD_MUNICIPIO"]),
            on=["NR_TURNO", "SG_UF", "CD_MUNICIPIO"], how="left"),
            det, ["NR_TURNO", "SG_UF", "CD_MUNICIPIO"])
        mun = preenche_nomes(mun, det)
    mun = derivar(mun)
    mun["CAPITAL"] = [
        "Sim" if CAPITAIS.get(u) == sem_acento(n) else "Nao"
        for u, n in zip(mun["SG_UF"], mun["NM_MUNICIPIO"])]
    mun = marca_margem(mun, a.margem_curta_pp, a.min_duelo)
    mun.to_csv(saida / "p2_municipios_por_turno.csv", index=False, sep=";",
               encoding="utf-8-sig")
    # checagem: municipios somam o total da UF
    cks = ["LULA", "FLAVIO", "OUTROS", "BRANCO", "NULO"] + (
        ["APTOS", "COMPARECIMENTO", "ABSTENCOES"] if det is not None else [])
    soma = mun.groupby(["NR_TURNO", "SG_UF"])[cks].sum()
    ref = uf.set_index(["NR_TURNO", "SG_UF"])[cks]
    dif = (soma.reindex(ref.index) - ref).abs().sum()
    ruins = dif[dif != 0]
    dbg("Checagem municipios somam UF ({}): {}".format(
        ", ".join(cks), "OK" if ruins.empty else "DIVERGENTE em " + str(ruins.to_dict())))
    for t, g in mun[mun["SG_UF"] != "ZZ"].groupby("NR_TURNO"):
        dbg("Municipios fora do exterior no turno {}: {:,} (conferir com a lista oficial; "
            "chave correta e UF + CD_MUNICIPIO, nomes se repetem)".format(int(t), len(g)))
    ni = mun["SECOES_NAO_INSTALADAS"].sum() if "SECOES_NAO_INSTALADAS" in mun else 0
    if ni:
        dbg("Locais com secoes nao instaladas: {:,} secoes em {:,} municipios".format(
            int(ni), int((mun["SECOES_NAO_INSTALADAS"] > 0).sum())))
    vm = variacao(mun, ["SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO"])
    if vm is not None:
        vm.to_csv(saida / "p2_municipios_variacao_1T_2T.csv", index=False, sep=";",
                  encoding="utf-8-sig")
    caps = mun[mun["CAPITAL"] == "Sim"]
    mostrar(caps.sort_values(["NR_TURNO", "SG_UF"]), "P2: CAPITAIS",
            ["NR_TURNO", "SG_UF", "NM_MUNICIPIO", "LULA", "FLAVIO", "PCT_LULA_DUELO",
             "PCT_ABSTENCAO"])
    curtos = mun[mun["MARGEM_CURTA"]]
    print("\nMunicipios de margem curta (|Lula - Flavio| no duelo <= {:g} pontos "
          "percentuais, ou seja, Lula entre {:g}% e {:g}% do duelo): {}".format(
              a.margem_curta_pp, 50 - a.margem_curta_pp / 2, 50 + a.margem_curta_pp / 2,
              curtos.groupby("NR_TURNO").size().to_dict()), flush=True)
    pq = mun[mun["AMOSTRA_PEQUENA"]]
    print("Municipios com duelo menor que {} votos (AMOSTRA_PEQUENA; evite ranquear por %): {}"
          .format(a.min_duelo, pq.groupby("NR_TURNO").size().to_dict()), flush=True)

    # ---- P3 (insumos) e P4 (teste) ----
    if det is not None:
        if a.secoes:
            colsd = [c for c in ["NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO",
                                 "APTOS", "COMPARECIMENTO", "ABSTENCOES", "DET_NOMINAIS",
                                 "DET_BRANCOS", "DET_NULOS", "DET_ANULADOS",
                                 "ST_SECAO_INSTALADA", "ST_SECAO_ANULADA",
                                 "DT_RECEBIMENTO_BU_HOR_TSE"] if c in det.columns]
            det[colsd].to_csv(saida / "secoes_detalhe.csv", index=False, sep=";",
                              encoding="utf-8-sig")
            dbg("Gravado secoes_detalhe.csv ({:,} linhas)".format(len(det)))
        analisa_horario(det, saida)
    if sc is not None:
        w = sc.pivot_table(index=["NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO"],
                           columns="NR_VOTAVEL", values="QT_VOTOS", aggfunc="sum",
                           fill_value=0)
        w.columns = ["V_{}".format(c) for c in w.columns]
        w.reset_index().to_csv(saida / "votos_secao_candidato.csv", index=False, sep=";",
                               encoding="utf-8-sig")
        dbg("Gravado votos_secao_candidato.csv ({:,} linhas)".format(len(w)))

    grava_fontes(a, saida, mc, det, not a.sem_hash)
    dbg("FIM. Arquivos em: " + str(saida.resolve()))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        dbg("ERRO NAO TRATADO:")
        traceback.print_exc()
        sys.exit(1)