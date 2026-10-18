"""Peças comuns dos scripts da auditoria de UI/UX/motion (reviews/audit-ui-ux-motion.md).

Pré-requisito: o site gerado dos bancos reais servido em BASE, por exemplo
    python scripts/catalogo_release.py baixar vendidos data/vendidos.db      # e vendidos-b, vendidos-c
    python -m comparador site data/vendidos.db data/vendidos-b.db data/vendidos-c.db --saida data/site
    cd data/site && python -m http.server 8765 --bind 127.0.0.1
Depois, de dentro desta pasta: python tema.py, python axe.py etc. (node dias.js RAIZ_DO_REPO PASTA_COM_site).
Variáveis: AUDIT_BASE (padrão http://127.0.0.1:8765), COMPARADOR_NAVEGADOR (padrão /opt/pw-browsers/chromium),
AUDIT_SAIDA (pasta das capturas e dos JSON; padrão data/auditoria, fora do git).
Os ASIN abaixo são dos dados de 2026-10-18: com outro banco, troque-os por casos equivalentes.
"""
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get("AUDIT_BASE", "http://127.0.0.1:8765")
NAV = os.environ.get("COMPARADOR_NAVEGADOR", "/opt/pw-browsers/chromium")
SAIDA = Path(os.environ.get("AUDIT_SAIDA", Path(__file__).resolve().parents[2] / "data" / "auditoria"))
SAIDA.mkdir(parents=True, exist_ok=True)

# livros escolhidos nos dados reais de 2026-10-18 (ver o relatório): histórico mais longo, 3 formatos, 1 dia só,
# título de 244 caracteres, sem capa, sem coleta recente
RICO, FORMATOS, UM_DIA, LONGO, VELHO = "8579604702", "8546908087", "1763628264", "1017254575", "000583919X"
LISTA = [RICO, FORMATOS, VELHO]

LARGURAS = [320, 375, 520, 600, 720, 900, 960, 1280]


def preparar_storage(lista=True, tema=None, alvo=True, recentes=True):
    """Script de init que deixa o localStorage num estado conhecido antes de o app ler."""
    st = {}
    if lista:
        st["lista_v1"] = json.dumps(LISTA)
    if alvo:
        st["alvos_v1"] = json.dumps({RICO: 100})
    if recentes:
        st["recentes_v1"] = json.dumps([{"a": RICO, "t": "Guia de Plantas", "img": "", "p": 0}])
    if tema:
        st["observador-tema"] = tema
    return "try{localStorage.clear();" + "".join(
        f"localStorage.setItem({json.dumps(k)},{json.dumps(v)});" for k, v in st.items()) + "}catch(e){}"


# telas: nome -> (endereço, seletor que diz que a tela terminou de desenhar, precisa de lista no storage)
TELAS = {
    "busca-inicial": ("/", "#res .row", False),
    "busca-texto": ("/?q=harry%20potter", "#res .row", False),
    "busca-vazia": ("/?q=zzqxwvkj", "#res .vazio", False),
    "livro-rico": (f"/?livro={RICO}", "#graf svg", False),
    "livro-formatos": (f"/?livro={FORMATOS}", "#graf svg", False),
    "livro-um-dia": (f"/?livro={UM_DIA}", "#graf svg", False),
    "livro-longo": (f"/?livro={LONGO}", "#graf svg", False),
    "livro-velho": (f"/?livro={VELHO}", "#graf svg", False),
    "livro-inexistente": ("/?livro=0000000000", ".vazio h1", False),
    "lista": ("/?lista", "#lst .row", True),
    "lista-vazia": ("/?lista", ".vazio h1", False),
    "sobre": ("/?sobre", ".prosa h1", False),
    "inicio-antigo": ("/?inicio", ".boas h1", True),
    "404": ("/404.html", ".vazio h1", False),
}


def abrir(p, largura=1280, altura=900, esquema="light", tema=None, lista=False, toque=False, movimento="no-preference",
          cores_forcadas="none"):
    b = p.chromium.launch(executable_path=NAV, args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": largura, "height": altura}, color_scheme=esquema, reduced_motion=movimento,
                        forced_colors=cores_forcadas, has_touch=toque, is_mobile=toque, device_scale_factor=1)
    ctx.add_init_script(preparar_storage(lista=lista, tema=tema, alvo=lista, recentes=lista))
    return b, ctx


def ir(pg, tela):
    url, sel, _ = TELAS[tela]
    pg.goto(BASE + url)
    pg.wait_for_selector(sel, timeout=60000)
    pg.wait_for_timeout(600)        # parecidos, sparks e fontes
    return pg
