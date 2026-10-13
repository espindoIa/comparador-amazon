"""Gera os ícones PNG do app (comparador/web/icone-*.png) a partir do desenho do icone.svg.

Uso: python scripts/gerar_icones.py        (precisa do Playwright e de um Chrome, Edge ou Chromium)
- icone-180.png: apple-touch-icon. Quadrado sem transparência: o iOS arredonda sozinho e pinta de preto o que for transparente.
- icone-192.png e icone-512.png: os ícones "any" do manifesto, com os cantos arredondados do icone.svg.
- icone-maskable-512.png: quadrado inteiro, com o desenho a 62% no miolo, para o Android recortar em círculo, gota ou quadrado
  arredondado sem comer o marcador (a zona segura é um círculo de 80% do lado).
"""

import os
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "comparador" / "web"
FUNDO, PAGINA, DESTAQUE = "#7c2d12", "#faf5ea", "#b45309"   # couro, papel e âmbar (MASTER.md)
MARCADOR = (f'<path d="M21 13h22a3 3 0 0 1 3 3v35l-14-8.5L18 51V16a3 3 0 0 1 3-3z" fill="{PAGINA}"/>'
            f'<path d="M25 27.5l5 5 9-9" fill="none" stroke="{DESTAQUE}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>')


def svg(raio: float = 0, escala: float = 1.0) -> str:
    miolo = MARCADOR if escala == 1 else f'<g transform="translate(32 32) scale({escala}) translate(-32 -32)">{MARCADOR}</g>'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
            f'<rect width="64" height="64" rx="{raio}" fill="{FUNDO}"/>{miolo}</svg>')


ICONES = {                                   # arquivo: (lado em px, desenho, fundo transparente?)
    "icone-180.png": (180, svg(), False),
    "icone-192.png": (192, svg(raio=14), True),
    "icone-512.png": (512, svg(raio=14), True),
    "icone-maskable-512.png": (512, svg(escala=0.62), False),
}


def navegador() -> str | None:
    return os.environ.get("COMPARADOR_NAVEGADOR")


def main() -> None:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=navegador(), args=["--no-sandbox"]) if navegador() else p.chromium.launch(channel="chrome")
        for nome, (lado, desenho, transparente) in ICONES.items():
            pg = b.new_page(viewport={"width": lado, "height": lado})
            pg.set_content(f'<body style="margin:0;background:transparent">{desenho.replace("<svg ", f"<svg width={lado} height={lado} ", 1)}</body>')
            pg.screenshot(path=str(WEB / nome), omit_background=transparente)
            pg.close()
            print(f"{nome}: {lado}x{lado}", file=sys.stderr)
        b.close()


if __name__ == "__main__":
    main()
