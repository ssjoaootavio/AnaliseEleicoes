#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P3 - Migracao estimada de votos entre o 1o e o 2o turno (presidente, 2026)
==========================================================================
Versao 0.2     (requer: numpy, pandas, scipy  ->  pip install scipy)

ENTRADA : json_p2_municipios_por_turno.csv (gerado por coleta_resultados_json.py, dados oficiais do TSE)
SAIDA   : p3_*.csv e p3_diagnostico.json

O QUE ISTO E
  O TSE nao publica como cada eleitor votou nos dois turnos. Publica totais por municipio.
  Este script faz INFERENCIA ECOLOGICA: estima uma matriz de transicao T entre categorias do
  1o turno (origem) e do 2o turno (destino) a partir da variacao entre os municipios.

    Origem (1o turno)                   Destino (2o turno)
    Lula | Flavio | Outros | Branco/Nulo | Abstencao     Lula | Flavio | Branco/Nulo | Abstencao

  Modelo: y_i = x_i . T  (fracoes do eleitorado apto do municipio i), T >= 0, linhas somam 1,
  minimos quadrados ponderados pelos aptos.

TRES CAMADAS DE AFIRMACAO (nao misturar)
  FATO      - balanco aritmetico (variacao por categoria) e LIMITES DETERMINISTICOS dos fluxos.
  ESTIMATIVA- matriz T do modelo. Vale se o comportamento for parecido entre municipios.
  ROBUSTEZ  - a mesma estimativa refeita de 7 jeitos (Brasil; sem o efeito de cada UF; 5 regioes).
              (Teste com dados simulados, --validar-simulacao: o bootstrap cobriu o valor verdadeiro em
              apenas 78-85% dos casos, e 7% quando o comportamento depende do perfil politico do
              municipio. Por isso ele NAO e apresentado como "intervalo de confianca".)
              Se a celula muda muito entre eles, o dado NAO identifica essa celula e ela NAO
              deve ser interpretada. O intervalo de bootstrap mede so o ruido amostral; ele
              pode ser estreito mesmo quando a celula nao e identificada.

LIMITES CONHECIDOS
  - Falacia ecologica: relacao entre municipios nao prova comportamento individual.
  - Eleitorado tratado como o mesmo nos dois turnos (aptos iguais no Brasil: 158.745.502).
  - Nao ha causa: a matriz descreve para onde os numeros foram, nao por que.
  - Mesma regra para os dois candidatos: toda tabela traz Lula e Flavio em colunas simetricas.
  - Valores 0,0 ou 100,0 sao frequentemente "cantos" do modelo (restricao T>=0), nao achados.

Uso:
  python migracao_1t_2t.py --entrada saida_json/json_p2_municipios_por_turno.csv --saida saida_p3
  python migracao_1t_2t.py --validar-simulacao --saida saida_p3
"""
import argparse
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from scipy.optimize import minimize
except ImportError:
    sys.exit("ERRO: este script precisa do scipy. Rode:  pip install scipy")

VERSAO = "0.2"
ORIG5 = ["LULA", "FLAVIO", "OUTROS", "BRANCO_NULO", "ABSTENCAO"]
DEST4 = ["LULA", "FLAVIO", "BRANCO_NULO", "ABSTENCAO"]
ORIG4 = ["LULA", "FLAVIO", "OUTROS_E_BRANCO_NULO", "ABSTENCAO"]

REGIAO = {
    **{u: "Norte" for u in "AC AP AM PA RO RR TO".split()},
    **{u: "Nordeste" for u in "AL BA CE MA PB PE PI RN SE".split()},
    **{u: "Centro-Oeste" for u in "DF GO MT MS".split()},
    **{u: "Sudeste" for u in "ES MG RJ SP".split()},
    **{u: "Sul" for u in "PR RS SC".split()},
    "ZZ": "Exterior",
}
REGIOES = ["Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul"]
LIM_ROBUSTA_PP = 10.0      # diferenca maxima-minima entre especificacoes para "ROBUSTA"
LIM_MODERADA_PP = 25.0     # acima disso: "NAO ROBUSTA"


def log(msg, t0=[time.time()]):
    print("[{:7.1f}s] {}".format(time.time() - t0[0], msg), flush=True)


# --------------------------------------------------------------------------- dados
def carrega(caminho):
    d = pd.read_csv(caminho, sep=";", encoding="utf-8-sig")
    obrig = ["NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO", "APTOS", "COMPARECIMENTO",
             "LULA", "FLAVIO", "OUTROS", "BRANCO", "NULO"]
    faltam = [c for c in obrig if c not in d.columns]
    if faltam:
        sys.exit("ERRO: colunas ausentes na entrada: {}".format(faltam))
    a = d[d.NR_TURNO == 1].set_index(["SG_UF", "CD_MUNICIPIO"]).sort_index()
    b = d[d.NR_TURNO == 2].set_index(["SG_UF", "CD_MUNICIPIO"]).sort_index()
    if len(a) != len(b) or not a.index.equals(b.index):
        sys.exit("ERRO: os dois turnos nao tem o mesmo conjunto de municipios ({} x {}).".format(len(a), len(b)))
    n1 = a["APTOS"].astype(float).to_numpy()
    n2 = b["APTOS"].astype(float).to_numpy()
    X = np.column_stack([a["LULA"], a["FLAVIO"], a["OUTROS"], a["BRANCO"] + a["NULO"],
                         a["APTOS"] - a["COMPARECIMENTO"]]).astype(float) / n1[:, None]
    aviso = None
    if float(b["OUTROS"].sum()) != 0:
        aviso = "2o turno tem votos em OUTROS ({}); somados a Branco/Nulo".format(int(b["OUTROS"].sum()))
    Y = np.column_stack([b["LULA"], b["FLAVIO"], b["BRANCO"] + b["NULO"] + b["OUTROS"],
                         b["APTOS"] - b["COMPARECIMENTO"]]).astype(float) / n2[:, None]
    if np.abs(X.sum(1) - 1).max() > 1e-9 or np.abs(Y.sum(1) - 1).max() > 1e-9:
        sys.exit("ERRO: categorias nao fecham 100% do eleitorado em algum municipio.")
    meta = pd.DataFrame({"SG_UF": [i[0] for i in a.index], "CD_MUNICIPIO": [i[1] for i in a.index],
                         "NM_MUNICIPIO": a["NM_MUNICIPIO"].to_numpy(), "APTOS_1T": n1, "APTOS_2T": n2})
    meta["REGIAO"] = meta.SG_UF.map(REGIAO)
    return meta, X, Y, aviso


def colapsa(X):
    """5 origens -> 4 (Outros + Branco/Nulo juntos)."""
    return np.column_stack([X[:, 0], X[:, 1], X[:, 2] + X[:, 3], X[:, 4]])


# --------------------------------------------------------------------------- modelo
def ajusta(X, Y, w, T0=None):
    """Minimos quadrados ponderados com T>=0 e cada linha somando 1 (SLSQP, exato para 20 parametros)."""
    k, l = X.shape[1], Y.shape[1]
    sw = w.sum()
    Xw = X * w[:, None]
    G = X.T @ Xw / sw
    B = Xw.T @ Y / sw
    c0 = float((Y * Y * w[:, None]).sum() / sw)

    def Q(t):
        T = t.reshape(k, l)
        return float(np.sum(T * (G @ T)) - 2 * np.sum(B * T) + c0)

    def gQ(t):
        return (2 * (G @ t.reshape(k, l) - B)).ravel()

    cons = []
    for i in range(k):
        e = np.zeros((k, l)); e[i] = 1
        cons.append({"type": "eq", "fun": (lambda t, i=i: t.reshape(k, l)[i].sum() - 1.0),
                     "jac": (lambda t, e=e.ravel(): e)})
    if T0 is None:
        T0 = np.tile((w[:, None] * Y).sum(0) / sw, (k, 1))
    r = minimize(Q, T0.ravel(), jac=gQ, bounds=[(0, 1)] * (k * l), constraints=cons, method="SLSQP",
                 options={"maxiter": 500, "ftol": 1e-16})
    T = np.clip(r.x.reshape(k, l), 0, 1)
    T /= T.sum(1, keepdims=True)
    return T, Q(T.ravel()), bool(r.success)


def remove_efeito_grupo(X, Y, w, grupo):
    """Subtrai a media ponderada do grupo (UF) em X e Y: usa so a variacao DENTRO de cada UF."""
    Xd, Yd = X.copy(), Y.copy()
    for g in np.unique(grupo):
        ix = np.where(grupo == g)[0]
        ww = w[ix] / w[ix].sum()
        Xd[ix] = X[ix] - (X[ix] * ww[:, None]).sum(0)
        Yd[ix] = Y[ix] - (Y[ix] * ww[:, None]).sum(0)
    return Xd, Yd


def especificacoes(meta, X, Y):
    """Retorna dict nome -> T para: BRASIL, EFEITO_FIXO_UF, cinco regioes. Todas com os mesmos dados."""
    w = meta.APTOS_1T.to_numpy()
    out, ok = {}, {}
    out["BRASIL"], _, ok["BRASIL"] = ajusta(X, Y, w)
    Xd, Yd = remove_efeito_grupo(X, Y, w, meta.SG_UF.to_numpy())
    out["EFEITO_FIXO_UF"], _, ok["EFEITO_FIXO_UF"] = ajusta(Xd, Yd, w)
    for r in REGIOES:
        m = (meta.REGIAO == r).to_numpy()
        out["REGIAO_" + r], _, ok["REGIAO_" + r] = ajusta(X[m], Y[m], w[m])
    return out, ok


def bootstrap_brasil(X, Y, w, T_hat, reps, rng):
    n = len(w)
    out = np.empty((reps, X.shape[1], Y.shape[1]))
    for r in range(reps):
        c = np.bincount(rng.integers(0, n, n), minlength=n).astype(float)
        out[r], _, _ = ajusta(X, Y, w * c, T0=T_hat)
    return out


def limites_deterministicos(X, Y, n1):
    """Por municipio: max(0, x_i+y_j-1) <= fluxo i->j (fracao dos aptos) <= min(x_i, y_j). Somado em eleitores."""
    lo = np.maximum(0.0, X[:, :, None] + Y[:, None, :] - 1.0)
    hi = np.minimum(X[:, :, None], Y[:, None, :])
    return (lo * n1[:, None, None]).sum(0), (hi * n1[:, None, None]).sum(0)


def classe(spread_pp):
    if spread_pp <= LIM_ROBUSTA_PP:
        return "ROBUSTA"
    if spread_pp <= LIM_MODERADA_PP:
        return "MODERADA"
    return "NAO ROBUSTA (nao interpretar)"


def monta_resultados(rotulo, orig, specs, X, Y, meta, bs, lb, hb):
    """Tabela longa: uma linha por celula com estimativa, bootstrap, faixa entre especificacoes, limites fato."""
    n1 = meta.APTOS_1T.to_numpy()
    origem_cont = (X * n1[:, None]).sum(0)
    nomes = list(specs.keys())
    S = np.stack([specs[k] for k in nomes])           # (n_spec, k, l)
    lo_bs, hi_bs = np.percentile(bs, 2.5, axis=0), np.percentile(bs, 97.5, axis=0)
    linhas = []
    for i, o in enumerate(orig):
        for j, d in enumerate(DEST4):
            v = 100 * S[:, i, j]
            spread = float(v.max() - v.min())
            linhas.append({
                "GRANULARIDADE": rotulo, "ORIGEM_1T": o, "DESTINO_2T": d,
                "ESTIMATIVA_BRASIL_PCT_DA_ORIGEM": round(float(v[0]), 1),
                "BOOTSTRAP_RUIDO_AMOSTRAL_INF": round(100 * float(lo_bs[i, j]), 1),
                "BOOTSTRAP_RUIDO_AMOSTRAL_SUP": round(100 * float(hi_bs[i, j]), 1),
                "MIN_ENTRE_ESPECIFICACOES": round(float(v.min()), 1),
                "MAX_ENTRE_ESPECIFICACOES": round(float(v.max()), 1),
                "AMPLITUDE_PP": round(spread, 1),
                "ROBUSTEZ": classe(spread),
                "CANTO_DO_MODELO_0_OU_100": "sim" if (v[0] <= 0.05 or v[0] >= 99.95) else "nao",
                "ESTIMATIVA_ELEITORES": int(round(float(S[0, i, j]) * origem_cont[i])),
                "LIMITE_MIN_ELEITORES_FATO": int(round(lb[i, j])),
                "LIMITE_MAX_ELEITORES_FATO": int(round(hb[i, j])),
                "ESTIMATIVA_FORA_DOS_LIMITES_FATO": "sim" if (
                    S[0, i, j] * origem_cont[i] > hb[i, j] + 0.5 or S[0, i, j] * origem_cont[i] < lb[i, j] - 0.5)
                    else "nao",
                "ORIGEM_ELEITORES_1T": int(round(origem_cont[i])),
                **{"PCT_" + k: round(float(100 * specs[k][i, j]), 1) for k in nomes},
            })
    return pd.DataFrame(linhas)


# --------------------------------------------------------------------------- balanco (fato)
def balanco(meta, X, Y):
    n1, n2 = meta.APTOS_1T.to_numpy(), meta.APTOS_2T.to_numpy()
    d = pd.DataFrame({"SG_UF": meta.SG_UF})
    d["LULA_1T"], d["FLAVIO_1T"], d["OUTROS_1T"] = X[:, 0] * n1, X[:, 1] * n1, X[:, 2] * n1
    d["BRANCO_NULO_1T"], d["ABSTENCAO_1T"] = X[:, 3] * n1, X[:, 4] * n1
    d["LULA_2T"], d["FLAVIO_2T"] = Y[:, 0] * n2, Y[:, 1] * n2
    d["BRANCO_NULO_2T"], d["ABSTENCAO_2T"] = Y[:, 2] * n2, Y[:, 3] * n2
    g = d.groupby("SG_UF").sum().round().astype(int)
    g.loc["BRASIL"] = g.sum()
    for c in ["LULA", "FLAVIO", "BRANCO_NULO", "ABSTENCAO"]:
        g["VAR_" + c] = g[c + "_2T"] - g[c + "_1T"]
    g["VAR_OUTROS"] = -g["OUTROS_1T"]
    g["VAR_LULA_PCT_DO_GANHO_DOS_DOIS"] = np.where(
        (g.VAR_LULA > 0) & (g.VAR_FLAVIO > 0), (100 * g.VAR_LULA / (g.VAR_LULA + g.VAR_FLAVIO)).round(1), np.nan)
    return g.reset_index()


# --------------------------------------------------------------------------- validacao por simulacao
def simula(X, rng, T_true, conc, vies=0.0):
    n = X.shape[0]
    k = X.shape[1]
    Y = np.zeros((n, 4))
    base = X[:, 0] / np.maximum(X[:, 0] + X[:, 1], 1e-9)
    for i in range(n):
        Ti = np.empty_like(T_true)
        for o in range(k):
            p = T_true[o].copy()
            if vies:
                s = vies * (base[i] - 0.5)
                p[0] = max(p[0] + s, 1e-3); p[1] = max(p[1] - s, 1e-3); p /= p.sum()
            Ti[o] = rng.dirichlet(conc * p + 1e-3)
        Y[i] = X[i] @ Ti
    return Y


def valida_simulacao(meta, X, reps, seed, saida):
    """Gera dados com T verdadeira conhecida e mede: erro medio, cobertura do bootstrap e se a faixa
    entre especificacoes cobre o valor verdadeiro. O objetivo e mostrar COMO o metodo erra."""
    T_true = np.array([[0.88, 0.01, 0.01, 0.10],
                       [0.01, 0.90, 0.01, 0.08],
                       [0.36, 0.38, 0.14, 0.12],
                       [0.15, 0.15, 0.50, 0.20],
                       [0.10, 0.03, 0.04, 0.83]])
    T_true /= T_true.sum(1, keepdims=True)
    w = meta.APTOS_1T.to_numpy()
    res = []
    cenarios = [("homogeneo (conc=400)", 400, 0.0),
                ("heterogeneo (conc=60)", 60, 0.0),
                ("heterogeneo + comportamento depende do perfil politico do municipio", 60, 0.35)]
    for nome, conc, vies in cenarios:
        rng = np.random.default_rng(seed)
        err, cob_bs, cob_sp, rob_ok, n_rob = [], [], [], 0, 0
        n_sim = 6
        for s in range(n_sim):
            Y = simula(X, rng, T_true, conc, vies)
            specs, _ = especificacoes(meta, X, Y)
            T = specs["BRASIL"]
            bs = bootstrap_brasil(X, Y, w, T, max(reps // 5, 30), rng)
            lo, hi = np.percentile(bs, 2.5, axis=0), np.percentile(bs, 97.5, axis=0)
            S = np.stack(list(specs.values()))
            smin, smax = S.min(0), S.max(0)
            err.append(np.abs(T - T_true).mean())
            cob_bs.append(((T_true >= lo) & (T_true <= hi)).mean())
            cob_sp.append(((T_true >= smin - 1e-9) & (T_true <= smax + 1e-9)).mean())
            amp = 100 * (smax - smin)
            rob = amp <= LIM_ROBUSTA_PP
            n_rob += int(rob.sum())
            rob_ok += int((rob & (np.abs(100 * (T - T_true)) <= LIM_ROBUSTA_PP)).sum())
        res.append({"cenario": nome, "simulacoes": n_sim,
                    "erro_medio_abs_pp": round(100 * float(np.mean(err)), 2),
                    "cobertura_IC_bootstrap": round(float(np.mean(cob_bs)), 3),
                    "cobertura_faixa_entre_especificacoes": round(float(np.mean(cob_sp)), 3),
                    "celulas_classificadas_robustas_e_corretas_dentro_de_10pp":
                        "{}/{}".format(rob_ok, n_rob)})
        log("simulacao '{}': erro medio {:.2f} pp | cobertura bootstrap {:.0%} | cobertura faixa {:.0%} | "
            "robustas corretas {}/{}".format(nome, 100 * np.mean(err), np.mean(cob_bs), np.mean(cob_sp), rob_ok, n_rob))
    Path(saida).mkdir(parents=True, exist_ok=True)
    (Path(saida) / "p3_validacao_simulacao.json").write_text(
        json.dumps({"T_verdadeira": T_true.round(4).tolist(), "resultados": res}, indent=2, ensure_ascii=False),
        encoding="utf-8")
    return res


# --------------------------------------------------------------------------- principal
def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--entrada", default="saida_json/json_p2_municipios_por_turno.csv")
    ap.add_argument("--saida", default="saida_p3")
    ap.add_argument("--reps", type=int, default=300, help="repeticoes do bootstrap (Brasil)")
    ap.add_argument("--semente", type=int, default=20261025)
    ap.add_argument("--validar-simulacao", action="store_true")
    a = ap.parse_args()
    log("P3 migracao v{} | Python {} | numpy {} | pandas {}".format(
        VERSAO, platform.python_version(), np.__version__, pd.__version__))
    if not Path(a.entrada).exists():
        sys.exit("ERRO: arquivo de entrada nao encontrado: {}".format(a.entrada))
    meta, X, Y, aviso = carrega(a.entrada)
    if aviso:
        log("AVISO: " + aviso)
    log("Municipios: {} | aptos 1T {:,} | aptos 2T {:,}".format(
        len(meta), int(meta.APTOS_1T.sum()), int(meta.APTOS_2T.sum())))
    out = Path(a.saida)
    out.mkdir(parents=True, exist_ok=True)

    if a.validar_simulacao:
        valida_simulacao(meta, X, a.reps, a.semente, out)
        return

    w = meta.APTOS_1T.to_numpy()
    n1 = w
    rng = np.random.default_rng(a.semente)
    pd.set_option("display.width", 220)

    # FATO: balanco
    bal = balanco(meta, X, Y)
    bal.to_csv(out / "p3_balanco_por_uf.csv", index=False, sep=";", encoding="utf-8-sig")

    todas = []
    nao_conv = []
    for rotulo, orig, Xs in [("5_ORIGENS", ORIG5, X), ("4_ORIGENS_OUTROS_JUNTO_COM_BRANCO_NULO", ORIG4, colapsa(X))]:
        log("Estimando {} (7 especificacoes + bootstrap {})...".format(rotulo, a.reps))
        specs, ok = especificacoes(meta, Xs, Y)
        nao_conv += [rotulo + ":" + k for k, v in ok.items() if not v]
        bs = bootstrap_brasil(Xs, Y, w, specs["BRASIL"], a.reps, rng)
        lb, hb = limites_deterministicos(Xs, Y, n1)
        todas.append(monta_resultados(rotulo, orig, specs, Xs, Y, meta, bs, lb, hb))
        if rotulo == "5_ORIGENS":
            Tb = specs["BRASIL"]
    res = pd.concat(todas, ignore_index=True)
    res.to_csv(out / "p3_matriz_e_robustez.csv", index=False, sep=";", encoding="utf-8-sig")

    # residuos por municipio (auditoria de ajuste)
    Yhat = X @ Tb
    r = pd.DataFrame({"SG_UF": meta.SG_UF, "CD_MUNICIPIO": meta.CD_MUNICIPIO, "NM_MUNICIPIO": meta.NM_MUNICIPIO,
                      "APTOS_1T": meta.APTOS_1T.astype(int)})
    for j, d in enumerate(DEST4):
        r["RESIDUO_PP_" + d] = np.round(100 * (Y[:, j] - Yhat[:, j]), 2)
    r["RESIDUO_ABS_MAX_PP"] = r[[c for c in r.columns if c.startswith("RESIDUO_PP_")]].abs().max(axis=1)
    r.sort_values("RESIDUO_ABS_MAX_PP", ascending=False).to_csv(
        out / "p3_residuos_municipios.csv", index=False, sep=";", encoding="utf-8-sig")
    ssr = float((w[:, None] * (Y - Yhat) ** 2).sum())
    sst = float((w[:, None] * (Y - (w[:, None] * Y).sum(0) / w.sum()) ** 2).sum())

    diag = {"versao": VERSAO, "entrada": str(a.entrada), "sha256_entrada": sha256(a.entrada),
            "parametros": {"reps": a.reps, "semente": a.semente, "limite_robusta_pp": LIM_ROBUSTA_PP,
                           "limite_moderada_pp": LIM_MODERADA_PP},
            "R2_ponderado_5_origens_brasil": round(1 - ssr / sst, 4),
            "especificacoes_sem_convergencia": nao_conv,
            "aviso_entrada": aviso,
            "natureza": "ESTIMATIVA (inferencia ecologica). Colunas LIMITE_*_FATO sao aritmeticas, sem modelo.",
            "ambiente": {"python": platform.python_version(), "numpy": np.__version__,
                         "pandas": pd.__version__}}
    (out / "p3_diagnostico.json").write_text(json.dumps(diag, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n=== FATO: BALANCO 1T -> 2T NO BRASIL (eleitores) ===")
    b = bal[bal.SG_UF == "BRASIL"].iloc[0]
    print("Lula {:+,} | Flavio {:+,} | Outros candidatos {:+,} | Branco/Nulo {:+,} | Abstencao {:+,}".format(
        b.VAR_LULA, b.VAR_FLAVIO, b.VAR_OUTROS, b.VAR_BRANCO_NULO, b.VAR_ABSTENCAO))
    for g in res.GRANULARIDADE.unique():
        t = res[res.GRANULARIDADE == g].copy()
        t["txt"] = t.apply(lambda q: "{:5.1f} [{:5.1f}-{:5.1f}] {}{}".format(
            q.ESTIMATIVA_BRASIL_PCT_DA_ORIGEM, q.MIN_ENTRE_ESPECIFICACOES, q.MAX_ENTRE_ESPECIFICACOES,
            {"ROBUSTA": "R", "MODERADA": "M"}.get(q.ROBUSTEZ, "X"),
            "c" if q.CANTO_DO_MODELO_0_OU_100 == "sim" else " "), axis=1)
        print("\n=== ESTIMATIVA {} (% da origem; [min-max entre especificacoes]; R=robusta M=moderada X=nao robusta; c=colada em 0 ou 100, pode ser artefato) ===".format(g))
        print(t.pivot(index="ORIGEM_1T", columns="DESTINO_2T", values="txt")
              .loc[ORIG5 if g == "5_ORIGENS" else ORIG4, DEST4].to_string())
    log("FIM. Arquivos em: {}".format(out.resolve()))


if __name__ == "__main__":
    main()