#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P4 - Horario dos votos por secao, a partir do log de cada urna (TSE) - v0.1
===========================================================================
ENTRADA : pacote(s) .zip por UF do conjunto "Arquivos transmitidos para totalizacao"
          (bu_imgbu_logjez_rdv_vscmr_2026_1t_UF.zip). O 2o turno entra quando o TSE publicar.
SAIDA   : p4_secoes_UF_Tn.csv   uma linha por secao (horario da urna)
          p4_votos_por_faixa_UF_Tn.csv   votos computados por faixa de 30 min (hora local da urna)
          p4_resumo_UF_Tn.json  validacoes e totais

O QUE E FATO E O QUE NAO E
  FATO     : o log da urna registra "Eleitor foi habilitado" e "O voto do eleitor foi computado"
             com data e hora, e "Operador selecionou: Encerrar votacao". Contamos esses eventos.
  LIMITE   : o log NAO diz em quem o eleitor votou. Da para medir QUANTOS votaram em cada horario
             e ONDE; nao da para saber o voto de quem votou tarde.
  CAVEATS  : (1) a hora e a do relogio da urna (hora local do estado, a confirmar por UF);
             (2) relogio de urna pode estar errado; (3) o evento "voto computado" e o voto
             concluido: eleitor suspenso nao conta.
  Validacao: o numero de votos computados por secao e comparado com QT_COMPARECIMENTO do CSV
             oficial (opcao --detalhe).

Uso:
  python extrai_horarios_urna.py bu_imgbu_logjez_rdv_vscmr_2026_1t_RR.zip --detalhe detalhe_votacao_secao_2026\\detalhe_votacao_secao_2026_BR.csv
  (varios zips: liste todos; --saida PASTA define onde gravar)
"""
import argparse
import collections
import datetime as dt
import io
import json
import platform
import re
import sys
import time
import zipfile
from pathlib import Path

import pandas as pd

VERSAO = "0.1"
FMT = "%d/%m/%Y %H:%M:%S"
NOME = re.compile(r"o(\d{5})([a-z]{2})(\d{5})(\d{4})(\d{4})-log\.jez$", re.I)
SIG_7Z = b"7z\xbc\xaf\x27\x1c"
T0 = time.time()


def log(m):
    print("[{:7.1f}s] {}".format(time.time() - T0, m), flush=True)


def texto(b):
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("latin-1", errors="replace")


def le_log(dados):
    """Bytes de um *-log.jez -> texto do logd.dat."""
    if dados[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(dados))
        nomes = [i for i in z.infolist() if not i.is_dir()]
        i = max(nomes, key=lambda x: x.file_size)
        return texto(z.read(i))
    if dados[:6] == SIG_7Z:
        import py7zr
        with py7zr.SevenZipFile(io.BytesIO(dados)) as z:
            d = z.readall()
            return texto(max((v.read() for v in d.values()), key=len))
    return texto(dados)


def bin30(t):
    return "{:02d}{:02d}".format(t.hour, 0 if t.minute < 30 else 30)


def processa_log(txt, dia):
    """Extrai eventos do dia da eleicao. Retorna dict ou None."""
    hab, votos, pronta, encerra, reinicios, suspensos = [], [], [], [], 0, 0
    for ln in txt.splitlines():
        c = ln.split("\t")
        if len(c) < 5:
            continue
        try:
            t = dt.datetime.strptime(c[0].strip(), FMT)
        except ValueError:
            continue
        if t.date() != dia:
            continue
        m = c[4].lower()
        if m.startswith("o voto do eleitor foi computado"):
            votos.append(t)
        elif m.startswith("eleitor foi habilitado"):
            hab.append(t)
        elif m.startswith("urna pronta para receber votos"):
            pronta.append(t)
        elif m.startswith("operador selecionou: encerrar vota"):
            encerra.append(t)
        elif m.startswith("iniciando aplica") and "turno" in m:
            reinicios += 1
        elif m.startswith("eleitor foi suspenso") or m.startswith("eleitor votou parcialmente"):
            suspensos += 1
    return dict(hab=hab, votos=votos, pronta=pronta, encerra=encerra, reinicios=reinicios, suspensos=suspensos)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pacotes", nargs="+")
    ap.add_argument("--data-eleicao", default="04/10/2026", help="dia da votacao (dd/mm/aaaa)")
    ap.add_argument("--detalhe", default=None, help="CSV detalhe_votacao_secao (para validar comparecimento)")
    ap.add_argument("--saida", default="saida_p4")
    ap.add_argument("--limite", type=int, default=None, help="so as N primeiras urnas (teste)")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    dia = dt.datetime.strptime(a.data_eleicao, "%d/%m/%Y").date()
    out = Path(a.saida)
    out.mkdir(parents=True, exist_ok=True)
    log("Extrator de horarios de urna v{} | Python {} | pandas {} | dia {}".format(
        VERSAO, platform.python_version(), pd.__version__, a.data_eleicao))

    for pac in a.pacotes:
        p = Path(pac)
        if not p.exists():
            sys.exit("ERRO: arquivo nao encontrado: {}".format(p))
        m = re.search(r"_(\d)t_([A-Za-z]{2})\.zip$", p.name)
        turno = int(m.group(1)) if m else 1
        uf_pac = m.group(2).upper() if m else None
        z = zipfile.ZipFile(p)
        logs = [i for i in z.infolist() if NOME.search(i.filename)]
        if a.limite:
            logs = logs[:a.limite]
        log("{}: {:,} logs de urna".format(p.name, len(logs)))
        linhas, faixas = [], collections.Counter()
        erros = []
        for k, i in enumerate(logs, 1):
            mm = NOME.search(i.filename)
            uf, mun, zona, sec = mm.group(2).upper(), int(mm.group(3)), int(mm.group(4)), int(mm.group(5))
            try:
                r = processa_log(le_log(z.read(i)), dia)
            except Exception as e:  # noqa
                erros.append((i.filename, str(e)))
                continue
            v = sorted(r["votos"])
            linhas.append({
                "SG_UF": uf, "CD_MUNICIPIO": mun, "NR_ZONA": zona, "NR_SECAO": sec,
                "T_PRONTA": r["pronta"][0] if r["pronta"] else None,
                "T_PRIMEIRO_VOTO": v[0] if v else None,
                "T_ULTIMO_VOTO": v[-1] if v else None,
                "T_ENCERRAR": r["encerra"][-1] if r["encerra"] else None,
                "N_HABILITADOS": len(r["hab"]), "N_VOTOS_COMPUTADOS": len(v),
                "N_SUSPENSOES": r["suspensos"], "N_REINICIOS_APP": r["reinicios"]})
            for t in v:
                faixas[(uf, bin30(t))] += 1
            if k % 300 == 0:
                log("  {:,} / {:,}".format(k, len(logs)))
        df = pd.DataFrame(linhas)
        for c in ("T_PRONTA", "T_PRIMEIRO_VOTO", "T_ULTIMO_VOTO", "T_ENCERRAR"):
            df[c] = pd.to_datetime(df[c])
        tag = "{}_T{}".format(uf_pac or "UF", turno)
        df.to_csv(out / "p4_secoes_{}.csv".format(tag), index=False, sep=";", encoding="utf-8-sig")
        fx = pd.DataFrame([{"SG_UF": k[0], "FAIXA_30MIN_HORA_URNA": k[1][:2] + ":" + k[1][2:], "VOTOS_COMPUTADOS": n}
                           for k, n in sorted(faixas.items())])
        fx.to_csv(out / "p4_votos_por_faixa_{}.csv".format(tag), index=False, sep=";", encoding="utf-8-sig")

        res = {"versao": VERSAO, "pacote": p.name, "dia": a.data_eleicao, "logs_lidos": len(df), "erros": erros[:10],
               "n_erros": len(erros), "votos_computados": int(df.N_VOTOS_COMPUTADOS.sum()),
               "habilitados": int(df.N_HABILITADOS.sum()),
               "secoes_sem_voto_no_dia": int((df.N_VOTOS_COMPUTADOS == 0).sum()),
               "secoes_sem_encerramento_registrado": int(df.T_ENCERRAR.isna().sum())}
        # validacao contra o CSV oficial
        if a.detalhe and Path(a.detalhe).exists():
            log("Validando contra {} ...".format(Path(a.detalhe).name))
            partes = []
            for ch in pd.read_csv(a.detalhe, sep=";", encoding="latin1", dtype=str, chunksize=300000,
                                  usecols=["NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "CD_CARGO",
                                           "QT_COMPARECIMENTO", "QT_APTOS"]):
                ch = ch[(ch.SG_UF == uf_pac) & (ch.CD_CARGO == "1") & (ch.NR_TURNO == str(turno))]
                if len(ch):
                    partes.append(ch)
            if partes:
                d = pd.concat(partes)
                for c in ("CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "QT_COMPARECIMENTO", "QT_APTOS"):
                    d[c] = d[c].astype(int)
                j = d.merge(df, on=["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO"], how="outer", indicator=True)
                res["secoes_csv"] = int(len(d))
                res["secoes_so_no_csv"] = int((j._merge == "left_only").sum())
                res["secoes_so_nos_logs"] = int((j._merge == "right_only").sum())
                b = j[j._merge == "both"].copy()
                b["DIF"] = b.N_VOTOS_COMPUTADOS - b.QT_COMPARECIMENTO
                res["secoes_comparadas"] = int(len(b))
                res["secoes_com_diferenca"] = int((b.DIF != 0).sum())
                res["soma_comparecimento_csv"] = int(b.QT_COMPARECIMENTO.sum())
                res["soma_votos_logs"] = int(b.N_VOTOS_COMPUTADOS.sum())
                res["diferenca_total"] = int(b.DIF.sum())
                res["diferenca_abs_max"] = int(b.DIF.abs().max())
                b.sort_values("DIF", key=lambda s: s.abs(), ascending=False).head(50).to_csv(
                    out / "p4_validacao_maiores_diferencas_{}.csv".format(tag), index=False, sep=";", encoding="utf-8-sig")
            else:
                res["aviso_validacao"] = "nenhuma secao de {} no CSV".format(uf_pac)
        (out / "p4_resumo_{}.json".format(tag)).write_text(json.dumps(res, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

        # resumo no terminal
        log("RESUMO {} turno {}".format(uf_pac, turno))
        for k, v in res.items():
            if k not in ("erros", "versao"):
                print("  {:<38} {}".format(k, v))
        tot = fx.VOTOS_COMPUTADOS.sum()
        print("\n  Votos computados por faixa de 30 min (hora do relogio da urna):")
        for _, r in fx.iterrows():
            print("    {}  {:>8,}  {:5.1f}%".format(r.FAIXA_30MIN_HORA_URNA, r.VOTOS_COMPUTADOS, 100 * r.VOTOS_COMPUTADOS / tot))
        enc = df.T_ENCERRAR.dropna()
        if len(enc):
            print("\n  Encerramento da votacao (hora da urna): primeiro {}  mediana {}  ultimo {}".format(
                enc.min().strftime("%H:%M"), enc.sort_values().iloc[len(enc) // 2].strftime("%H:%M"), enc.max().strftime("%H:%M")))
        ult = df.T_ULTIMO_VOTO.dropna()
        if len(ult):
            print("  Ultimo voto computado (hora da urna): mediana {}  p95 {}  maximo {}".format(
                ult.sort_values().iloc[len(ult) // 2].strftime("%H:%M"),
                ult.sort_values().iloc[int(len(ult) * .95)].strftime("%H:%M"), ult.max().strftime("%H:%M")))
    log("FIM. Arquivos em: {}".format(out.resolve()))


if __name__ == "__main__":
    main()
