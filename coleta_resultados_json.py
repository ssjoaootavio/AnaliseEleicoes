#!/usr/bin/env python3
"""
Coletor dos resultados de presidente (1o e 2o turnos) publicados no painel do TSE.

De onde vem: o painel https://resultados.tse.jus.br/oficial/app/ consulta arquivos .jws
(JSON assinado, NAO criptografado) no mesmo site. Este script baixa os mesmos arquivos:
  - config   : /oficial/ele2026/<pleito>/config/mun-e<pleito>-cm.jws    (UFs e municipios)
  - Brasil   : /oficial/ele2026/<pleito>/dados/br/br-c0001-e<pleito>-u.jws
  - UF       : /oficial/ele2026/<pleito>/dados/<uf>/<uf>-c0001-e<pleito>-u.jws
  - municipio: /oficial/ele2026/<pleito>/dados/<uf>/<uf><cd>-c0001-e<pleito>-u.jws
Pleitos (CD_ELEICAO): 6257 = 1o turno, 6258 = 2o turno (presidente = cargo 1).

ATENCAO: nao e uma API documentada. E o back-end do painel e o formato pode mudar. A fonte
oficial para citacao continua sendo os CSVs dos dados abertos. Use este coletor como ponte e
confira os totais do Brasil contra o painel. A assinatura (EdDSA) NAO e verificada aqui.

Uso:
    python coleta_resultados_json.py --turnos 1 2 --saida saida_json
    python coleta_resultados_json.py --turnos 2 --limite-municipios 20     (teste rapido)

Opcoes:
    --turnos 1 2               turnos a coletar (padrao: 1 2)
    --saida PASTA              pasta de saida (padrao: saida_json); cache dos arquivos brutos em
                               PASTA/cache_bruto (reexecutar nao baixa de novo o que ja existe)
    --atualizar                ignora o cache e baixa tudo de novo
    --workers 4                pedidos simultaneos (padrao 4; seja educado, nao passe de 8)
    --pausa 0.15               pausa (s) apos cada pedido, por worker
    --sem-municipios           so Brasil e UFs
    --limite-municipios N      baixa so os N primeiros municipios de cada turno (teste)
    --comparar-csv PASTA       compara o 1o turno com p1_uf_por_turno.csv da v2.x do script
    --margem-curta-pp 10       igual ao script de analise
    --min-duelo 100            igual ao script de analise
    --pleito-1 6257 --pleito-2 6258 --ano 2026 --base URL   (avancado)

Saidas (em PASTA):
    json_totais_por_escopo.csv, json_candidatos_por_escopo.csv,
    json_p1_brasil_por_turno.csv, json_p1_uf_por_turno.csv, json_p2_municipios_por_turno.csv,
    json_*_variacao_1T_2T.csv (se houver os dois turnos), coleta_manifesto.csv (url, bytes,
    sha256, data de geracao), coleta_erros.csv (se houver) e coleta_resumo.json.

Requisitos: Python 3.9+ e pandas.
"""
import sys

if sys.version_info < (3, 9):
    print("ERRO: Python " + sys.version.split()[0] + " e antigo. Use 3.9 ou superior.")
    sys.exit(1)

import argparse
import base64
import hashlib
import json
import time
import traceback
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

VERSAO = "1.1"
T0 = time.time()
BASE_PADRAO = "https://resultados.tse.jus.br/oficial"
LULA, FLAVIO = 13, 22
UA = "AnaliseEleicoes-coletor/{} (pesquisa independente; dados publicos do TSE)".format(VERSAO)
SOMAVEIS = ["SECOES", "SECOES_NAO_INSTALADAS", "APTOS", "APTOS_NAO_INSTALADOS", "COMPARECIMENTO",
            "ABSTENCOES", "VOTOS_VALIDOS", "BRANCO", "NULO", "LULA", "FLAVIO", "OUTROS"]


def dbg(msg):
    print("[{:7.1f}s] {}".format(time.time() - T0, msg), flush=True)


def falha(msg):
    dbg("ERRO: " + msg)
    sys.exit(1)


# ----------------------------------------------------------------------------
# Download e decodificacao
# ----------------------------------------------------------------------------
def baixar(url, cache, atualizar, pausa, tentativas=4):
    """Devolve (bytes, origem). Usa o cache em disco, salvo se atualizar=True."""
    if cache.exists() and not atualizar:
        return cache.read_bytes(), "cache"
    alvo = url + ("?nocache={}".format(int(time.time() * 1000)) if atualizar else "")
    ultimo = None
    for i in range(tentativas):
        try:
            req = urllib.request.Request(alvo, headers={"User-Agent": UA,
                                                       "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                dados = r.read()
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(dados)
            time.sleep(pausa)
            return dados, "rede"
        except urllib.error.HTTPError as e:
            ultimo = "HTTP {}".format(e.code)
            if e.code in (403, 404):      # nao adianta repetir
                break
        except Exception as e:            # rede, timeout...
            ultimo = "{}: {}".format(type(e).__name__, e)
        time.sleep(2 ** i)
    raise RuntimeError("falha ao baixar {} ({})".format(url, ultimo))


def _b64(s):
    s = s.replace("-", "+").replace("_", "/")
    return base64.b64decode(s + "=" * (-len(s) % 4))


def decodifica_jws(dados):
    """JWS compacto = cabecalho.conteudo.assinatura (base64url). Nao ha criptografia."""
    partes = dados.decode("utf-8").strip().split(".")
    if len(partes) != 3:
        raise ValueError("arquivo nao parece JWS ({} partes)".format(len(partes)))
    return json.loads(_b64(partes[0])), json.loads(_b64(partes[1]).decode("utf-8"))


def n(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------------------
# Extracao
# ----------------------------------------------------------------------------
def candidatos_do_payload(p):
    """Candidatos aparecem aninhados (federacao/partido); busca qualquer objeto com n e vap."""
    achados = []

    def anda(o):
        if isinstance(o, list):
            for i in o:
                anda(i)
        elif isinstance(o, dict):
            if "vap" in o and "n" in o:
                achados.append(o)
            else:
                for v in o.values():
                    anda(v)

    anda(p.get("carg", []))
    return achados


def linha_totais(p):
    s, e, v = p.get("s", {}), p.get("e", {}), p.get("v", {})
    return {
        "DG": p.get("dg"), "HG": p.get("hg"), "TURNO_ARQUIVO": n(p.get("t")),
        "SECOES": n(s.get("ts")), "SECOES_TOTALIZADAS": n(s.get("st")),
        "SECOES_NAO_INSTALADAS": n(s.get("sni")),
        "APTOS": n(e.get("te")), "APTOS_NAO_INSTALADOS": n(e.get("esni")),
        "COMPARECIMENTO": n(e.get("c")), "ABSTENCOES": n(e.get("a")),
        "TOTAL_VOTOS": n(v.get("tv")), "VOTOS_VALIDOS": n(v.get("vvc")),
        "BRANCO": n(v.get("vb")),
        "NULO_DIGITADO": n(v.get("vn")),
        "NULO_VNT": n(v.get("vnt")),   # parcela dos nulos que o TSE lista a parte (ver LEIAME)
        "NULO": n(v.get("tvn")),       # total de nulos oficial = digitados + VNT
        "ANULADO": n(v.get("van")), "ANULADO_SUB_JUDICE": n(v.get("vansj")),
    }


def processa(tarefa, payload):
    t = linha_totais(payload)
    cands = candidatos_do_payload(payload)
    por_nr = {}
    for c in cands:
        nr = n(c.get("n"))
        por_nr[nr] = por_nr.get(nr, 0) + (n(c.get("vap")) or 0)
    t.update({"NR_TURNO": tarefa["turno"], "ESCOPO": tarefa["escopo"], "SG_UF": tarefa["uf"],
              "CD_MUNICIPIO": tarefa["cd"], "NM_MUNICIPIO": tarefa["nome"],
              "CAPITAL": tarefa["capital"]})
    t["LULA"] = por_nr.get(LULA, 0)
    t["FLAVIO"] = por_nr.get(FLAVIO, 0)
    t["OUTROS"] = sum(v for k, v in por_nr.items() if k not in (LULA, FLAVIO))
    t["SOMA_CANDIDATOS"] = sum(por_nr.values())
    linhas_c = []
    for c in cands:
        linhas_c.append({
            "NR_TURNO": tarefa["turno"], "ESCOPO": tarefa["escopo"], "SG_UF": tarefa["uf"],
            "CD_MUNICIPIO": tarefa["cd"], "NR_VOTAVEL": n(c.get("n")), "NM_VOTAVEL": c.get("nm"),
            "SQ_CANDIDATO": c.get("sqcand"), "ELEITO": c.get("e"), "SITUACAO": c.get("st"),
            "QT_VOTOS": n(c.get("vap"))})
    return t, linhas_c


# ----------------------------------------------------------------------------
# Plano de coleta
# ----------------------------------------------------------------------------
def plano(a, turno, pleito, saida):
    base = "{}/ele{}/{}".format(a.base, a.ano, pleito)
    cod = "e{:06d}".format(pleito)
    cache = saida / "cache_bruto" / str(pleito)

    def tarefa(escopo, uf, cd, nome, capital, caminho):
        return {"turno": turno, "escopo": escopo, "uf": uf, "cd": cd, "nome": nome,
                "capital": capital, "url": "{}/{}".format(base, caminho),
                "cache": cache / caminho}

    cfg_url = "{}/config/mun-{}-cm.jws".format(base, cod)
    dados, orig = baixar(cfg_url, cache / "config" / "mun-{}-cm.jws".format(cod), a.atualizar,
                         a.pausa)
    _, cfg = decodifica_jws(dados)
    ufs = cfg.get("abr", [])
    if not ufs:
        falha("configuracao sem lista de UFs (formato mudou?) em " + cfg_url)
    dbg("Turno {} (pleito {}): configuracao {} | {} UFs | {} municipios".format(
        turno, pleito, orig, len(ufs), sum(len(u.get("mu", [])) for u in ufs)))
    ts = [tarefa("BR", "BR", None, "BRASIL", "", "dados/br/br-c0001-{}-u.jws".format(cod))]
    mun = []
    for u in ufs:
        uf = u["cd"].lower()
        ts.append(tarefa("UF", uf.upper(), None, u.get("ds", uf.upper()), "",
                         "dados/{0}/{0}-c0001-{1}-u.jws".format(uf, cod)))
        for m in u.get("mu", []):
            mun.append(tarefa("MUN", uf.upper(), int(m["cd"]), m.get("nm", ""),
                              "Sim" if m.get("c") == "s" else "Nao",
                              "dados/{0}/{0}{1}-c0001-{2}-u.jws".format(uf, m["cd"], cod)))
    if a.limite_municipios:
        mun = mun[:a.limite_municipios]
    if not a.sem_municipios:
        ts += mun
    return ts


def executa(tarefa, a):
    try:
        dados, orig = baixar(tarefa["url"], tarefa["cache"], a.atualizar, a.pausa)
        cab, payload = decodifica_jws(dados)
        t, c = processa(tarefa, payload)
        man = {"NR_TURNO": tarefa["turno"], "ESCOPO": tarefa["escopo"], "SG_UF": tarefa["uf"],
               "CD_MUNICIPIO": tarefa["cd"], "URL": tarefa["url"], "ORIGEM": orig,
               "BYTES": len(dados), "SHA256": hashlib.sha256(dados).hexdigest(),
               "DG": t["DG"], "HG": t["HG"], "ALG": cab.get("alg"), "KID": cab.get("kid")}
        return {"ok": True, "t": t, "c": c, "man": man}
    except Exception as e:
        return {"ok": False, "erro": "{}: {}".format(type(e).__name__, e), "tarefa": tarefa}


# ----------------------------------------------------------------------------
# Tabelas derivadas
# ----------------------------------------------------------------------------
def deriva(t, limite_pp, min_duelo):
    nz = lambda s: s.replace(0, np.nan)
    t["VALIDOS"] = t["VOTOS_VALIDOS"]
    t["DUELO"] = t["LULA"] + t["FLAVIO"]
    t["PCT_LULA_VALIDOS"] = t["LULA"] / nz(t["VALIDOS"]) * 100
    t["PCT_FLAVIO_VALIDOS"] = t["FLAVIO"] / nz(t["VALIDOS"]) * 100
    t["PCT_LULA_DUELO"] = t["LULA"] / nz(t["DUELO"]) * 100
    t["MARGEM_LULA_MENOS_FLAVIO"] = t["LULA"] - t["FLAVIO"]
    t["MARGEM_DUELO_PP"] = (t["MARGEM_LULA_MENOS_FLAVIO"].abs() / nz(t["DUELO"]) * 100)
    t["PCT_ABSTENCAO"] = t["ABSTENCOES"] / nz(t["APTOS"]) * 100
    t = t.round(2)
    t["MARGEM_CURTA"] = (t["MARGEM_DUELO_PP"] <= limite_pp).fillna(False)
    t["AMOSTRA_PEQUENA"] = t["DUELO"] < min_duelo
    return t


def variacao(t, idx):
    if not {1, 2}.issubset(set(t["NR_TURNO"].unique())):
        return None
    cols = [c for c in SOMAVEIS + ["PCT_LULA_DUELO", "PCT_LULA_VALIDOS", "PCT_FLAVIO_VALIDOS",
                                   "PCT_ABSTENCAO"] if c in t.columns]
    w = t.pivot_table(index=idx, columns="NR_TURNO", values=cols, aggfunc="first")
    w.columns = ["{}_{}T".format(c, int(k)) for c, k in w.columns]
    for c in cols:
        w["DELTA_" + c] = (w[c + "_2T"] - w[c + "_1T"]).round(2)
    return w.reset_index()


# ----------------------------------------------------------------------------
# Validacoes
# ----------------------------------------------------------------------------
def valida(tot, completo):
    """Identidades internas e somas entre niveis. Imprime e devolve numero de problemas."""
    prob = 0
    for turno, g in tot.groupby("NR_TURNO"):
        # 1. identidade em cada linha
        id1 = g["VOTOS_VALIDOS"] + g["BRANCO"] + g["NULO"] + g["ANULADO"].fillna(0)
        ruim = g[id1 != g["COMPARECIMENTO"]]
        dbg("VALIDACAO turno {}: validos+brancos+nulos(+anulados) = comparecimento em "
            "{:,} de {:,} linhas".format(int(turno), len(g) - len(ruim), len(g)))
        prob += len(ruim)
        # 2. soma dos candidatos = validos
        ruim2 = g[g["SOMA_CANDIDATOS"] != g["VOTOS_VALIDOS"]]
        dbg("VALIDACAO turno {}: soma dos candidatos = votos validos em {:,} de {:,} linhas"
            .format(int(turno), len(g) - len(ruim2), len(g)))
        prob += len(ruim2)
        # 3. UFs somam o Brasil
        br = g[g["ESCOPO"] == "BR"]
        uf = g[g["ESCOPO"] == "UF"]
        if len(br) == 1 and len(uf):
            difs = {c: int(uf[c].sum() - br.iloc[0][c]) for c in SOMAVEIS
                    if uf[c].sum() != br.iloc[0][c]}
            dbg("VALIDACAO turno {}: UFs somam o Brasil: {}".format(
                int(turno), "OK" if not difs else "DIVERGENTE " + str(difs)))
            prob += len(difs)
        # 4. municipios somam a UF
        mun = g[g["ESCOPO"] == "MUN"]
        if len(mun) and len(uf):
            if not completo:
                dbg("VALIDACAO turno {}: soma dos municipios nao conferida (coleta parcial)"
                    .format(int(turno)))
                continue
            s = mun.groupby("SG_UF")[SOMAVEIS].sum()
            r = uf.set_index("SG_UF")[SOMAVEIS]
            comp = (s.reindex(r.index) - r).abs().sum()
            ruins = comp[comp != 0]
            dbg("VALIDACAO turno {}: municipios somam as UFs: {}".format(
                int(turno), "OK" if ruins.empty else
                "DIVERGENTE em " + str({k: int(v) for k, v in ruins.items()})))
            prob += 0 if ruins.empty else len(ruins)
    return prob


def compara_csv(tot, pasta):
    """Compara o 1o turno do painel com p1_uf_por_turno.csv gerado pelo script de analise."""
    arq = Path(pasta) / "p1_uf_por_turno.csv"
    if not arq.exists():
        dbg("--comparar-csv: {} nao encontrado; comparacao pulada".format(arq))
        return
    c = pd.read_csv(arq, sep=";", encoding="utf-8-sig")
    c = c[c["NR_TURNO"] == 1].set_index("SG_UF")
    j = tot[(tot["NR_TURNO"] == 1) & (tot["ESCOPO"] == "UF")].set_index("SG_UF")
    if c.empty or j.empty:
        dbg("--comparar-csv: sem 1o turno em um dos lados; pulada")
        return
    exc = c["EXCLUIDO"] if "EXCLUIDO" in c.columns else 0
    pares = {
        "LULA": (c["LULA"], j["LULA"]), "FLAVIO": (c["FLAVIO"], j["FLAVIO"]),
        "BRANCO": (c["BRANCO"], j["BRANCO"]),
        "APTOS": (c["APTOS"], j["APTOS"]), "COMPARECIMENTO": (c["COMPARECIMENTO"],
                                                              j["COMPARECIMENTO"]),
        "ABSTENCOES": (c["ABSTENCOES"], j["ABSTENCOES"]),
        # candidatos + nulos: invariante a tratar o candidato excluido como valido ou nulo
        "CANDIDATOS+NULOS": (c["LULA"] + c["FLAVIO"] + c["OUTROS"] + exc + c["NULO"],
                             j["LULA"] + j["FLAVIO"] + j["OUTROS"] + j["NULO"]),
    }
    for nome, (x, y) in pares.items():
        d = (x.sort_index() - y.sort_index()).abs()
        dbg("COMPARACAO csv x painel (1o turno, por UF) {}: {}".format(
            nome, "OK" if d.sum() == 0 else "DIVERGENTE em {} UFs, soma {:,}".format(
                int((d != 0).sum()), int(d.sum()))))
    vc = int(c["VALIDOS"].sum()) if "VALIDOS" in c.columns else None
    vj = int(j["VOTOS_VALIDOS"].sum())
    if vc is not None:
        dbg("COMPARACAO validos: csv {:,} | painel {:,} | diferenca {:,}{}".format(
            vc, vj, vc - vj, "" if vc == vj else
            " (se for igual aos votos de um candidato, rode a analise com --excluir-candidatos)"))


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--turnos", type=int, nargs="+", default=[1, 2], choices=[1, 2])
    ap.add_argument("--saida", default="saida_json")
    ap.add_argument("--atualizar", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--pausa", type=float, default=0.15)
    ap.add_argument("--sem-municipios", action="store_true")
    ap.add_argument("--limite-municipios", type=int, default=None)
    ap.add_argument("--comparar-csv", default=None)
    ap.add_argument("--margem-curta-pp", type=float, default=10.0)
    ap.add_argument("--min-duelo", type=int, default=100)
    ap.add_argument("--pleito-1", type=int, default=6257)
    ap.add_argument("--pleito-2", type=int, default=6258)
    ap.add_argument("--ano", type=int, default=2026)
    ap.add_argument("--base", default=BASE_PADRAO)
    a = ap.parse_args()
    a.base = a.base.rstrip("/")
    a.workers = max(1, min(a.workers, 8))
    dbg("Coletor v{} | Python {} | opcoes: {}".format(VERSAO, sys.version.split()[0], vars(a)))
    saida = Path(a.saida)
    saida.mkdir(parents=True, exist_ok=True)
    pleitos = {1: a.pleito_1, 2: a.pleito_2}

    tarefas = []
    for turno in sorted(set(a.turnos)):
        tarefas += plano(a, turno, pleitos[turno], saida)
    dbg("Arquivos a obter: {:,} (workers {}, pausa {}s)".format(len(tarefas), a.workers,
                                                                 a.pausa))

    resultados, feitos = [], 0
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for r in ex.map(lambda t: executa(t, a), tarefas):
            resultados.append(r)
            feitos += 1
            if feitos % 500 == 0 or feitos == len(tarefas):
                dbg("  {:,} / {:,}".format(feitos, len(tarefas)))

    ok = [r for r in resultados if r["ok"]]
    erros = [r for r in resultados if not r["ok"]]
    if erros:
        pd.DataFrame([{"NR_TURNO": r["tarefa"]["turno"], "ESCOPO": r["tarefa"]["escopo"],
                       "SG_UF": r["tarefa"]["uf"], "CD_MUNICIPIO": r["tarefa"]["cd"],
                       "URL": r["tarefa"]["url"], "ERRO": r["erro"]} for r in erros]
                     ).to_csv(saida / "coleta_erros.csv", index=False, sep=";",
                              encoding="utf-8-sig")
        dbg("ATENCAO: {:,} arquivos com erro (ver coleta_erros.csv). Exemplo: {}".format(
            len(erros), erros[0]["erro"]))
    if not ok:
        falha("nenhum arquivo obtido.")

    tot = pd.DataFrame([r["t"] for r in ok])
    cand = pd.DataFrame([c for r in ok for c in r["c"]])
    for df in (tot, cand):
        df["CD_MUNICIPIO"] = df["CD_MUNICIPIO"].astype("Int64")   # vazio para Brasil e UF
    man = pd.DataFrame([r["man"] for r in ok])
    if "CD_MUNICIPIO" in man.columns:
        man["CD_MUNICIPIO"] = man["CD_MUNICIPIO"].astype("Int64")
    man.to_csv(saida / "coleta_manifesto.csv", index=False, sep=";", encoding="utf-8-sig")
    tot.to_csv(saida / "json_totais_por_escopo.csv", index=False, sep=";", encoding="utf-8-sig")
    cand.to_csv(saida / "json_candidatos_por_escopo.csv", index=False, sep=";",
                encoding="utf-8-sig")

    # conferencia do turno que o arquivo diz ser (protege contra pleito trocado)
    for turno, g in tot.groupby("NR_TURNO"):
        diz = sorted(g["TURNO_ARQUIVO"].dropna().unique().tolist())
        if diz != [turno]:
            dbg("ATENCAO: turno {} pedido, mas os arquivos dizem turno {}".format(turno, diz))

    problemas = valida(tot, not a.limite_municipios)
    if a.comparar_csv:
        compara_csv(tot, a.comparar_csv)

    # tabelas no formato do script de analise
    ids = ["NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO"]
    br = deriva(tot[tot["ESCOPO"] == "BR"].drop(columns=["CD_MUNICIPIO", "NM_MUNICIPIO"]).copy(),
                a.margem_curta_pp, a.min_duelo)
    uf = deriva(tot[tot["ESCOPO"] == "UF"].drop(columns=["CD_MUNICIPIO", "NM_MUNICIPIO"]).copy(),
                a.margem_curta_pp, a.min_duelo).sort_values(["NR_TURNO", "SG_UF"])
    br.to_csv(saida / "json_p1_brasil_por_turno.csv", index=False, sep=";", encoding="utf-8-sig")
    uf.to_csv(saida / "json_p1_uf_por_turno.csv", index=False, sep=";", encoding="utf-8-sig")
    print("\n=== BRASIL POR TURNO (painel do TSE) ===", flush=True)
    print(br[["NR_TURNO", "DG", "HG", "APTOS", "COMPARECIMENTO", "ABSTENCOES", "PCT_ABSTENCAO",
              "LULA", "FLAVIO", "OUTROS", "BRANCO", "NULO", "PCT_LULA_VALIDOS",
              "PCT_FLAVIO_VALIDOS"]].to_string(index=False), flush=True)
    vb = variacao(br.assign(SG_UF="BR"), ["SG_UF"])
    vu = variacao(uf, ["SG_UF"])
    if vu is not None:
        vb.to_csv(saida / "json_p1_brasil_variacao_1T_2T.csv", index=False, sep=";",
                  encoding="utf-8-sig")
        vu.to_csv(saida / "json_p1_uf_variacao_1T_2T.csv", index=False, sep=";",
                  encoding="utf-8-sig")
        print("\n=== VARIACAO 1T -> 2T POR UF (ordenado por ganho de Lula) ===", flush=True)
        print(vu.sort_values("DELTA_LULA", ascending=False)[
            ["SG_UF", "DELTA_LULA", "DELTA_FLAVIO", "DELTA_BRANCO", "DELTA_NULO",
             "DELTA_ABSTENCOES", "DELTA_PCT_LULA_DUELO"]].to_string(index=False), flush=True)

    if (tot["ESCOPO"] == "MUN").any():
        mun = tot[tot["ESCOPO"] == "MUN"].copy()
        mun["CD_MUNICIPIO"] = mun["CD_MUNICIPIO"].astype(int)
        mun = deriva(mun, a.margem_curta_pp, a.min_duelo)
        mun = mun.sort_values(["NR_TURNO", "SG_UF", "CD_MUNICIPIO"])
        mun.to_csv(saida / "json_p2_municipios_por_turno.csv", index=False, sep=";",
                   encoding="utf-8-sig")
        vm = variacao(mun, ["SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO"])
        if vm is not None:
            vm.to_csv(saida / "json_p2_municipios_variacao_1T_2T.csv", index=False, sep=";",
                      encoding="utf-8-sig")
            dbg("Gravado json_p2_municipios_variacao_1T_2T.csv ({:,} municipios)".format(len(vm)))

    resumo = {"coletor": VERSAO, "executado_em": datetime.now().isoformat(timespec="seconds"),
              "base": a.base, "pleitos": {str(k): v for k, v in pleitos.items()
                                          if k in a.turnos},
              "arquivos_ok": len(ok), "arquivos_erro": len(erros),
              "problemas_de_validacao": int(problemas),
              "geracao_por_turno": {str(int(t)): sorted(set(g["DG"] + " " + g["HG"]))[-1]
                                    for t, g in tot[tot["ESCOPO"] == "BR"].groupby("NR_TURNO")},
              "assinatura_verificada": False}
    (saida / "coleta_resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=2),
                                              encoding="utf-8")
    dbg("FIM. {:,} arquivos ok, {:,} com erro, {} problemas de validacao. Saida em: {}".format(
        len(ok), len(erros), problemas, saida.resolve()))
    if erros or problemas:
        sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        dbg("ERRO NAO TRATADO:")
        traceback.print_exc()
        sys.exit(1)