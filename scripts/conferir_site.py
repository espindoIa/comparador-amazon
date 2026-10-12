"""Confere o site novo antes de publicar: ele não pode ter muito menos livros que o site no ar.

Uso: python scripts/conferir_site.py site/dados/meta.json META_DO_SITE_NO_AR [--minimo 0.7]
Sai com código 1 se o novo tiver menos que MINIMO vezes os livros do atual (sinal de banco
incompleto ou de erro na geração). Sem o meta do site no ar (primeira publicação), passa.
"""

import argparse
import json
import sys

MINIMO = 0.7


def ler(caminho: str) -> dict | None:
    try:
        with open(caminho, encoding="utf-8") as f:
            meta = json.load(f)
        return meta if isinstance(meta, dict) and isinstance(meta.get("itens"), int) else None
    except (OSError, ValueError):
        return None


def conferir(novo: dict, atual: dict | None, minimo: float = MINIMO) -> str | None:
    """Motivo para não publicar, ou None se pode publicar."""
    if not novo or not novo.get("itens"):
        return "o site novo não tem nenhum livro"
    if atual and novo["itens"] < minimo * atual["itens"]:
        return (f"o site novo tem {novo['itens']} livros e o atual tem {atual['itens']} "
                f"(menos de {minimo:.0%}); para publicar assim mesmo, rode o workflow com 'forcar'")
    return None


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("novo")
    p.add_argument("atual")
    p.add_argument("--minimo", type=float, default=MINIMO)
    a = p.parse_args()
    novo, atual = ler(a.novo), ler(a.atual)
    print(f"livros no site novo: {novo and novo.get('itens')}; no site atual: {atual and atual.get('itens')}")
    motivo = conferir(novo, atual, a.minimo)
    if motivo:
        sys.exit(f"recusado: {motivo}")


if __name__ == "__main__":
    main()
