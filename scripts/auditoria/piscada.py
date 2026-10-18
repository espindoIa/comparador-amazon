"""Piscada do tema salvo: com o tema claro salvo e a rede lenta (CDP Network.emulateNetworkConditions), grava os quadros
da tela (Page.startScreencast) do pedido até o fim da carga e diz a cor do fundo de cada quadro.
Saída (em AUDIT_SAIDA): piscada.json e piscada-quadro-*.png (os primeiros)."""
import base64
import io
import json
import time

from comum import BASE, SAIDA, abrir, sync_playwright

try:
    from PIL import Image
except ImportError:
    Image = None

out = {}
with sync_playwright() as p:
    for nome, tema in (("claro-salvo", "light"), ("sem-tema-salvo", None)):
        b, ctx = abrir(p, largura=390, altura=800, esquema="light", tema=tema)
        pg = ctx.new_page()
        cdp = ctx.new_cdp_session(pg)
        cdp.send("Network.enable")
        cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
        cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": 300, "downloadThroughput": 160 * 1024, "uploadThroughput": 80 * 1024})
        quadros = []
        t0 = time.time()

        def quadro(ev):
            quadros.append((round(time.time() - t0, 2), ev["data"]))
            cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})
        cdp.on("Page.screencastFrame", quadro)
        cdp.send("Page.startScreencast", {"format": "png", "everyNthFrame": 1})
        pg.goto(BASE + "/", wait_until="load", timeout=120000)
        pg.wait_for_timeout(800)
        cdp.send("Page.stopScreencast")
        cores = []
        for i, (t, dados) in enumerate(quadros):
            png = base64.b64decode(dados)
            if Image:
                im = Image.open(io.BytesIO(png)).convert("RGB")
                cor = im.getpixel((im.width - 5, im.height // 2))          # margem direita, longe do conteúdo
            else:
                cor = None
            if not cores or cores[-1]["fundo"] != cor:      # guarda o quadro de cada troca de cor do fundo
                (SAIDA / f"piscada-{nome}-{t:.2f}s.png").write_bytes(png)
            cores.append({"t": t, "fundo": cor})
        out[nome] = cores
        b.close()
(SAIDA / "piscada.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out, indent=1))
