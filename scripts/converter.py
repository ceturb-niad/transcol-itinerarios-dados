#!/usr/bin/env python3
"""Converte o KML de itinerários do Transcol GV em GeoJSON e manifesto.

Contrato de dados: ver README.md e a seção "Contrato de dados" do documento
do projeto. Só usa a biblioteca padrão do Python (sem GDAL).

Uso:
    python scripts/converter.py --kml itinerarios.kml --saida _site --estado manifest.json

Saídas:
    <saida>/itinerarios.geojson   GeoJSON 2D, coordenadas com 6 casas
    <saida>/manifest.json         manifesto completo (com verificado_em)
    <estado>                      manifesto de estado (sem verificado_em); só é
                                  regravado quando o hash do KML muda

Código de saída: 0 em sucesso; 1 em qualquer falha de leitura ou validação
(nesse caso nada é gravado, e o Pages mantém o último deploy bom).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

CASAS_DECIMAIS = 6
SEM_NOME = "(sem nome)"

# 735I | 735V | 735I_A | 649I_B (Pleno Voo)
RE_NOME = re.compile(r"^(\d+)([IV])(?:_(\w+))?(?:\s*\((.*)\))?$")
RE_CODIGO_INICIAL = re.compile(r"^(\d+)")

# Campos que toda feature deve ter (valor pode ser nulo, exceto nome e linha).
CAMPOS = (
    "caminho", "grupo", "subgrupo", "pasta_linha", "linha",
    "nome", "codigo", "sentido", "variante", "obs", "chave",
)


class ErroConversao(Exception):
    """Falha que deve interromper o pipeline sem publicar."""


# --------------------------------------------------------------------------
# Leitura do KML
# --------------------------------------------------------------------------

def _tag(el: ET.Element) -> str:
    return el.tag.rsplit("}", 1)[-1]


def _filhos(el: ET.Element, tag: str) -> list[ET.Element]:
    return [c for c in el if _tag(c) == tag]


def _nome(el: ET.Element) -> str | None:
    for c in el:
        if _tag(c) == "name":
            texto = (c.text or "").strip()
            return texto or None
    return None


def _raiz_unica(kml: ET.Element) -> ET.Element:
    """Devolve a pasta raiz (o KML do técnico tem uma pasta com a data)."""
    if _tag(kml) != "kml":
        raise ErroConversao(f"Raiz do XML é <{_tag(kml)}>, esperado <kml>.")
    docs = _filhos(kml, "Document")
    if len(docs) != 1:
        raise ErroConversao(f"Esperado 1 <Document>, encontrado {len(docs)}.")
    doc = docs[0]
    pastas = _filhos(doc, "Folder")
    soltos = _filhos(doc, "Placemark")
    if len(pastas) != 1 or soltos:
        raise ErroConversao(
            "Esperada exatamente uma pasta raiz sob <Document> e nenhum "
            f"placemark solto; encontradas {len(pastas)} pasta(s) e "
            f"{len(soltos)} placemark(s) soltos."
        )
    return pastas[0]


def _percorrer(pasta: ET.Element, caminho: tuple[str, ...]):
    """Gera (caminho_de_pastas, placemark), em ordem de documento."""
    for c in pasta:
        t = _tag(c)
        if t == "Folder":
            nome = _nome(c)
            if nome is None:
                aviso(f"Pasta sem nome dentro de '{'/'.join(caminho)}'.")
                nome = SEM_NOME
            yield from _percorrer(c, caminho + (nome,))
        elif t == "Placemark":
            yield caminho, c


def _coordenadas(placemark: ET.Element, rotulo: str) -> list[tuple[float, float]] | None:
    """Coordenadas 2D arredondadas; None se o placemark não for LineString."""
    linhas = [e for e in placemark.iter() if _tag(e) == "LineString"]
    if not linhas:
        return None
    coords = [e for e in linhas[0].iter() if _tag(e) == "coordinates"]
    if not coords or not (coords[0].text or "").strip():
        raise ErroConversao(f"{rotulo}: LineString sem coordenadas.")
    pontos: list[tuple[float, float]] = []
    for token in coords[0].text.split():
        partes = token.split(",")
        try:
            lon, lat = float(partes[0]), float(partes[1])
        except (ValueError, IndexError):
            raise ErroConversao(f"{rotulo}: coordenada inválida '{token[:40]}'.")
        if not (math.isfinite(lon) and math.isfinite(lat)
                and -180 <= lon <= 180 and -90 <= lat <= 90):
            raise ErroConversao(f"{rotulo}: coordenada fora do intervalo '{token[:40]}'.")
        # "+ 0.0" normaliza -0.0
        pontos.append((round(lon, CASAS_DECIMAIS) + 0.0, round(lat, CASAS_DECIMAIS) + 0.0))
    if len(pontos) < 2:
        raise ErroConversao(f"{rotulo}: LineString com menos de 2 pontos.")
    # Remove vértices consecutivos idênticos (após o arredondamento).
    sem_repeticao = [p for i, p in enumerate(pontos) if i == 0 or p != pontos[i - 1]]
    return sem_repeticao if len(sem_repeticao) >= 2 else pontos


# --------------------------------------------------------------------------
# Atributos
# --------------------------------------------------------------------------

def atributos(pastas: tuple[str, ...], nome: str) -> dict:
    """Atributos de uma feature, sem a pasta raiz (que é um carimbo de data).

    pastas = (grupo,)                      placemark direto no grupo
    pastas = (grupo, pasta_linha)          caso comum
    pastas = (grupo, subgrupo, pasta_linha)  Noturno e Praias
    """
    grupo = pastas[0] if pastas else None
    subgrupo = pastas[1] if len(pastas) >= 3 else None
    pasta_linha = pastas[-1] if len(pastas) >= 2 else None

    m = RE_NOME.match(nome)
    if m:
        codigo, sentido, variante, obs = m.groups()
    else:
        mc = RE_CODIGO_INICIAL.match(nome)
        codigo, sentido, variante, obs = (mc.group(1) if mc else None), None, None, None

    return {
        "caminho": "/".join(pastas),
        "grupo": grupo,
        "subgrupo": subgrupo,
        "pasta_linha": pasta_linha,
        "linha": pasta_linha or codigo or nome,
        "nome": nome,
        "codigo": codigo,
        "sentido": sentido,
        "variante": variante,
        "obs": obs,
    }


def converter(caminho_kml: Path) -> tuple[dict, str | None, dict]:
    """Devolve (FeatureCollection, versao_kml, estatísticas)."""
    try:
        kml = ET.parse(caminho_kml).getroot()
    except ET.ParseError as e:
        raise ErroConversao(f"KML não é um XML válido: {e}")

    raiz = _raiz_unica(kml)
    versao_kml = _nome(raiz)

    features: list[dict] = []
    usadas: Counter = Counter()
    ignorados = 0
    fora_do_padrao = 0

    for pastas, pm in _percorrer(raiz, ()):
        nome = _nome(pm)
        if nome is None:
            aviso(f"Placemark sem nome em '{'/'.join(pastas)}'.")
            nome = SEM_NOME
        rotulo = f"{'/'.join(pastas)}/{nome}".strip("/")
        pontos = _coordenadas(pm, rotulo)
        if pontos is None:
            aviso(f"{rotulo}: geometria que não é LineString, ignorada.")
            ignorados += 1
            continue

        props = atributos(pastas, nome)
        if not RE_NOME.match(nome):
            fora_do_padrao += 1
        base = f"{props['caminho']}/{nome}" if props["caminho"] else nome
        usadas[base] += 1
        props["chave"] = base if usadas[base] == 1 else f"{base}#{usadas[base]}"
        if usadas[base] > 1:
            aviso(f"{rotulo}: nome repetido na mesma pasta; chave '{props['chave']}'.")

        features.append({
            "type": "Feature",
            "properties": props,
            "geometry": {"type": "LineString", "coordinates": [list(p) for p in pontos]},
        })

    stats = {"ignorados": ignorados, "fora_do_padrao": fora_do_padrao}
    return {"type": "FeatureCollection", "features": features}, versao_kml, stats


# --------------------------------------------------------------------------
# Validação (piso da V1)
# --------------------------------------------------------------------------

def validar(fc: dict) -> None:
    """GeoJSON válido, ao menos uma feature e campos obrigatórios presentes."""
    erros: list[str] = []
    if fc.get("type") != "FeatureCollection":
        erros.append("type diferente de FeatureCollection")
    feats = fc.get("features") or []
    if len(feats) < 1:
        erros.append("nenhuma feature")
    for i, f in enumerate(feats):
        p = f.get("properties") or {}
        falta = [c for c in CAMPOS if c not in p]
        if falta:
            erros.append(f"feature {i}: faltam campos {falta}")
        for obrigatorio in ("nome", "linha", "chave"):
            if not isinstance(p.get(obrigatorio), str) or not p[obrigatorio]:
                erros.append(f"feature {i}: '{obrigatorio}' vazio")
        g = f.get("geometry") or {}
        c = g.get("coordinates")
        if g.get("type") != "LineString" or not isinstance(c, list) or len(c) < 2:
            erros.append(f"feature {i} ({p.get('chave')}): geometria inválida")
        if len(erros) >= 10:
            break
    if erros:
        raise ErroConversao("Validação falhou: " + "; ".join(erros))


# --------------------------------------------------------------------------
# Manifesto
# --------------------------------------------------------------------------

def agora_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ler_estado(caminho: Path | None) -> dict | None:
    if caminho is None or not caminho.exists():
        return None
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) else None
    except (ValueError, OSError):
        aviso(f"Manifesto de estado ilegível ({caminho}); tratado como primeira execução.")
        return None


def montar_manifesto(hash_origem: str, n_features: int, versao_kml: str | None,
                     anterior: dict | None, agora: str) -> tuple[dict, bool]:
    """Devolve (manifesto completo, kml_mudou)."""
    mudou = anterior is None or anterior.get("hash_origem") != hash_origem
    if mudou or not anterior.get("dados_atualizados_em"):
        atualizado = agora
    else:
        atualizado = anterior["dados_atualizados_em"]
    return {
        "dados_atualizados_em": atualizado,
        "verificado_em": agora,
        "hash_origem": hash_origem,
        "n_features": n_features,
        "versao_kml": versao_kml,
    }, mudou


# --------------------------------------------------------------------------
# Execução
# --------------------------------------------------------------------------

def aviso(msg: str) -> None:
    print(f"::warning::{msg}", file=sys.stderr)


def gravar_json(caminho: Path, dados: dict, compacto: bool) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    if compacto:
        texto = json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
    else:
        texto = json.dumps(dados, ensure_ascii=False, indent=2) + "\n"
    caminho.write_text(texto, encoding="utf-8")


def executar(kml: Path, saida: Path, estado: Path | None) -> int:
    t0 = time.perf_counter()
    bruto = kml.read_bytes()
    hash_origem = hashlib.sha256(bruto).hexdigest()

    fc, versao_kml, stats = converter(kml)
    validar(fc)

    manifesto, mudou = montar_manifesto(
        hash_origem, len(fc["features"]), versao_kml, ler_estado(estado), agora_utc()
    )

    gravar_json(saida / "itinerarios.geojson", fc, compacto=True)
    gravar_json(saida / "manifest.json", manifesto, compacto=False)
    if estado is not None and mudou:
        gravar_json(estado, {k: v for k, v in manifesto.items() if k != "verificado_em"}, compacto=False)

    tam = (saida / "itinerarios.geojson").stat().st_size / 1e6
    por_grupo = Counter(f["properties"]["grupo"] for f in fc["features"])
    print(f"KML: {len(bruto) / 1e6:.1f} MB  sha256={hash_origem[:12]}  raiz='{versao_kml}'")
    print(f"GeoJSON: {len(fc['features'])} features, {tam:.1f} MB, em {time.perf_counter() - t0:.1f} s")
    print(f"KML mudou desde a última execução: {'sim' if mudou else 'não'}")
    print(f"Fora do padrão de nome: {stats['fora_do_padrao']}; ignorados: {stats['ignorados']}")
    print("Por grupo:", dict(sorted(por_grupo.items(), key=lambda kv: str(kv[0]))))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kml", required=True, type=Path)
    ap.add_argument("--saida", required=True, type=Path)
    ap.add_argument("--estado", type=Path, default=None)
    args = ap.parse_args(argv)
    try:
        return executar(args.kml, args.saida, args.estado)
    except ErroConversao as e:
        print(f"::error::{e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
