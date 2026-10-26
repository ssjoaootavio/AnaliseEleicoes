#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Explorador dos logs de urna (pacote "Arquivos transmitidos para totalizacao", TSE) - v0.1
=========================================================================================
Objetivo: descobrir, com UM pacote pequeno, se o log de cada urna traz horarios que permitam
responder P4 (quantos eleitores votaram depois das 17h), SEM supor o formato do log.

NAO baixa nada. Voce baixa um pacote por UF no portal de dados abertos (comece pelo menor) e
aponta o arquivo .zip aqui. O script le tudo em memoria; nao extrai arquivos para o disco.

Uso:
  python explora_logs_urna.py bu_imgbu_logjez_rdv_vscmr_2026_1t_RR.zip
  python explora_logs_urna.py PACOTE.zip --amostra 30 --saida explorar_logs.txt

Saida: explorar_logs.txt (pode me enviar). Ele traz
  - tipos de arquivo dentro do pacote e exemplos de nomes;
  - as primeiras e ultimas linhas de um log de urna;
  - as mensagens mais frequentes (numeros trocados por #), as que falam de voto, habilitacao,
    inicio e encerramento, e o intervalo de horarios de cada log da amostra.
Nada aqui identifica eleitor: o log registra eventos da urna, nao quem votou nem em quem.
"""
import argparse
import collections
import datetime as dt
import gzip
import io
import platform
import re
import sys
import zipfile
from pathlib import Path

VERSAO = "0.1"
FMT = "%d/%m/%Y %H:%M:%S"
SIG_7Z = b"7z\xbc\xaf\x27\x1c"


def texto(b):
    for enc in ("utf-8", "latin-1"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("latin-1", errors="replace")


def abre_conteudo(dados, nome, avisos):
    """Retorna lista de (nome_interno, bytes) de um .logjez (zip, 7z, gzip ou texto)."""
    if dados[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(dados))
        return [(i.filename, z.read(i)) for i in z.infolist() if not i.is_dir()]
    if dados[:6] == SIG_7Z:
        try:
            import py7zr
        except ImportError:
            avisos.add("Arquivo em formato 7z. Instale: pip install py7zr  (e rode de novo)")
            return []
        with py7zr.SevenZipFile(io.BytesIO(dados)) as z:
            d = z.readall()
            return [(k, v.read()) for k, v in d.items()]
    if dados[:2] == b"\x1f\x8b":
        return [(nome + ".txt", gzip.decompress(dados))]
    return [(nome, dados)]


def parse_log(txt):
    """Linhas -> lista de (datetime|None, [campos])."""
    out = []
    for ln in txt.splitlines():
        if not ln.strip():
            continue
        campos = ln.rstrip("\r\n").split("\t")
        t = None
        try:
            t = dt.datetime.strptime(campos[0].strip(), FMT)
        except (ValueError, IndexError):
            pass
        out.append((t, campos))
    return out


def mensagem(campos):
    """Heuristica: a mensagem e o campo de texto mais longo que nao e hash nem data."""
    cand = [c for c in campos[1:] if not re.fullmatch(r"[0-9A-Fa-f]{8,}", c.strip()) and c.strip() not in ("INFO", "ALERTA", "ERRO", "DEBUG")]
    return max(cand, key=len) if cand else (campos[-1] if campos else "")


def norm(m):
    m = re.sub(r"[0-9A-Fa-f]{12,}", "<hex>", m)
    m = re.sub(r"\d+", "#", m)
    return m.strip()[:140]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pacote")
    ap.add_argument("--amostra", type=int, default=20, help="quantos logs ler")
    ap.add_argument("--saida", default="explorar_logs.txt")
    ap.add_argument("--ext", default=".logjez,.jez,.log", help="extensoes tratadas como log, separadas por virgula")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    L = []
    P = lambda s="": (print(s), L.append(s))
    P("Explorador de logs de urna v{} | Python {} | {}".format(VERSAO, platform.python_version(), datetime_str()))
    p = Path(a.pacote)
    if not p.exists():
        sys.exit("ERRO: arquivo nao encontrado: {}".format(p))
    P("Pacote: {} ({:,} bytes)".format(p.name, p.stat().st_size))
    try:
        z = zipfile.ZipFile(p)
    except zipfile.BadZipFile:
        sys.exit("ERRO: o arquivo nao e um zip valido (download incompleto?).")
    infos = [i for i in z.infolist() if not i.is_dir()]
    P("Arquivos dentro do pacote: {:,}".format(len(infos)))
    ext = collections.Counter(Path(i.filename).suffix.lower() or "(sem extensao)" for i in infos)
    tam = collections.Counter()
    for i in infos:
        tam[Path(i.filename).suffix.lower() or "(sem extensao)"] += i.file_size
    P("Por extensao (quantidade, tamanho descompactado):")
    for k, v in ext.most_common():
        P("  {:<16} {:>8,}  {:>16,} bytes".format(k, v, tam[k]))
    P("Exemplos de nomes:")
    for i in infos[:8]:
        P("  " + i.filename)

    exts = tuple(e.strip().lower() for e in a.ext.split(","))
    logs = [i for i in infos if i.filename.lower().endswith(exts)]
    P("\nArquivos tratados como log ({}): {:,}".format(", ".join(exts), len(logs)))
    if not logs:
        P("Nenhum log encontrado. Envie este relatorio assim mesmo: a lista acima mostra o que ha no pacote.")
        Path(a.saida).write_text("\n".join(L), encoding="utf-8")
        return
    # amostra espalhada pelo pacote (inicio, meio, fim)
    passo = max(1, len(logs) // a.amostra)
    amostra = logs[::passo][:a.amostra]
    avisos = set()
    msgs = collections.Counter()
    voto_msgs, marcos = collections.Counter(), collections.Counter()
    resumo = []
    primeiro = True
    for i in amostra:
        try:
            internos = abre_conteudo(z.read(i), i.filename, avisos)
        except Exception as e:  # noqa
            avisos.add("falha ao abrir {}: {}".format(i.filename, e))
            continue
        if not internos:
            continue
        nome_i, dados = max(internos, key=lambda x: len(x[1]))
        linhas = parse_log(texto(dados))
        tempos = [t for t, _ in linhas if t]
        if primeiro:
            P("\n--- Primeiro log da amostra: {} -> {} ({:,} linhas) ---".format(i.filename, nome_i, len(linhas)))
            P("Arquivos internos: " + ", ".join("{} ({:,} B)".format(n, len(d)) for n, d in internos))
            P("Primeiras linhas (campos separados por | ):")
            for t, c in linhas[:25]:
                P("  " + " | ".join(x[:70] for x in c))
            P("Ultimas linhas:")
            for t, c in linhas[-15:]:
                P("  " + " | ".join(x[:70] for x in c))
            primeiro = False
        for t, c in linhas:
            m = norm(mensagem(c))
            msgs[m] += 1
            ml = m.lower()
            if "voto" in ml:
                voto_msgs[m] += 1
            if any(k in ml for k in ("habilit", "inici", "encerr", "zer", "fecha", "abert", "libera", "fim")):
                marcos[m] += 1
        if tempos:
            resumo.append((i.filename.split("/")[-1][:48], len(linhas), min(tempos), max(tempos)))
    P("\n--- Mensagens mais frequentes na amostra ({} logs) ---".format(len(resumo)))
    for m, n in msgs.most_common(60):
        P("  {:>8,}  {}".format(n, m))
    P("\n--- Mensagens que falam de VOTO ---")
    for m, n in voto_msgs.most_common(30):
        P("  {:>8,}  {}".format(n, m))
    P("\n--- Mensagens de habilitacao, inicio, encerramento, zeresima ---")
    for m, n in marcos.most_common(40):
        P("  {:>8,}  {}".format(n, m))
    P("\n--- Intervalo de horarios por log (primeiro e ultimo evento) ---")
    for nome, n, t0, t1 in resumo:
        P("  {:<48} {:>7,} linhas  {}  ->  {}".format(nome, n, t0.strftime(FMT), t1.strftime(FMT)))
    for av in sorted(avisos):
        P("AVISO: " + av)
    Path(a.saida).write_text("\n".join(L), encoding="utf-8")
    print("\nRelatorio gravado em: {}".format(Path(a.saida).resolve()))


def datetime_str():
    return dt.datetime.now().strftime(FMT)


if __name__ == "__main__":
    main()