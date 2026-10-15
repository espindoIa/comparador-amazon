# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

O repositório, os comentários, os testes e as mensagens ao usuário são em português; escreva na mesma língua.

- Consulte o advisor antes de fechar um plano, depois de o mesmo erro aparecer duas vezes e antes de dar uma tarefa por concluída.

## O que é

Coletor de preços dos livros mais vendidos da Amazon.com.br (Python + Playwright) e um site estático que mostra o histórico (JavaScript sem build). Tudo roda no GitHub: o coletor no Actions, o banco como arquivos de uma release, o site no Pages. Não há servidor. O `README.md` descreve a coleta (ritmo, ciclo, o que acontece num bloqueio) e os limites; leia-o antes de mexer em `varredura.py`, `ritmo.py` ou nos workflows.

## Comandos

```bash
pip install -r requirements.txt                       # Playwright usa o Chrome/Edge instalado; sem eles: python -m playwright install chromium
python -m unittest discover -s tests                  # tudo: Python, os testes de JS (via node) e os de navegador
python -m unittest tests.test_site.TestFolhaDeEstilo  # uma classe; também vale tests.test_site.TestSite.test_cli_site
node tests/busca.test.js                              # só a busca (também livro.test.js, lista.test.js e recomenda.test.js)
python -m comparador varrer --dry-run                 # confere opções e mostra o plano, sem pedir nada à Amazon
python -m comparador site data/vendidos.db --saida site   # gera o site; sirva com: cd site && python -m http.server 8000
```

- Os testes de navegador (`TestSiteNoNavegador`) são pulados se não houver Chromium. Aponte `COMPARADOR_NAVEGADOR` para o executável (no ambiente de nuvem: `/opt/pw-browsers/chromium`); sem isso, eles não rodam e a suíte passa em falso.
- `data/` (bancos, HTML de páginas com problema) não vai para o git. Não há linter nem formatador configurados.
- O CI (`.github/workflows/testes.yml`) roda a suíte inteira em todo PR.

## Arquitetura

**Dois mundos que só se encontram no banco SQLite e no JSON gerado.**

1. **Coleta** (`comparador/`): `varredura.py` lê as listas de mais vendidos por gênero e faixa de preço com um navegador sem janela (`cliente_http.py`) e grava intervalos de preço no banco (`schema_catalogo.sql`, `db.py`). `ritmo.py` guarda no próprio banco o teto de requisições, o degrau de ciclo (12/6/3 h) e o último ritmo limpo (bloqueio não muda nada disso desde 15/10/2026); a Amazon bloqueia clientes simples, então não troque o navegador por `requests`. `__main__.py` é a CLI (`varrer`, `catalogo`, `grafico`, `site` e `subgeneros`, um experimento sem coleta recorrente: `subgeneros.py` descobre a árvore de subcategorias e mede o custo de rotular, guardando o HTML lido para refazer tudo sem pedir de novo; `subgeneros atualizar` é a coleta recorrente da ficção, que roda em `subgeneros.yml` só com a variável `SUBGENEROS_ATIVO=true`, guarda o estado e o snapshot na release `catalogo` (`scripts/subgeneros_release.py`) e só entra no site com `SUBGENEROS_NO_SITE=true`).
2. **Agendamento**: o cron do GitHub atrasa horas, então a coleta é um anel de workflows: `varredura.yml` → `scripts/proximo_ciclo.py` marca a próxima leitura → `espera.yml` dorme → dispara `varredura.yml`; `vigia.yml` reinicia sequências paradas. São três sequências independentes (`PARTICOES_VENDIDOS`), cada uma com banco, teto e ciclo próprios, publicados na release `catalogo` (`scripts/catalogo_release.py`, com `verificar_banco.py` e `verificar_precos.py` como travas antes de publicar). `COLETA_PAUSADA=true` desliga tudo.
3. **Site** (`comparador/site.py`): junta os três bancos pelo ASIN e gera `dados/*.json`. **O formato de cada JSON está no docstring do começo de `site.py`**: o índice vai em listas posicionais, e `web/app.js`, `busca.js` e `livro.js` leem por posição. Mudar um lado exige mudar o outro, e `tests/test_site.py` cobre os dois. Os parecidos de cada livro são calculados aqui (`parecidos.py`, exato e testado contra força bruta; usa vários processos com mais de 20 mil livros) e vão para `dados/p/`; a mesma `parecidos.py` decide quem é o mesmo autor em "Mais de …" (`chaves_do_autor`); `scripts/medir_parecidos.py` mede tempo, tamanho e livros-sonda (com `--subgeneros`, cada sonda antes e depois). `site --subgeneros ARQUIVO` põe os subgêneros da ficção (snapshot de `subgeneros.py`) na conta; ausente ou ilegível, o site sai sem eles. `site.yml` publica no Pages e recusa um site com menos de 70% dos livros do atual (`forcar` ignora a trava).
4. **Front-end** (`comparador/web/`): app de página única sem framework e sem build. As rotas são query strings no mesmo `index.html` (`?q=`, `?livro=ASIN`, `?lista`, `?sobre`; `livro.html` só redireciona). `app.js` desenha todas as telas montando HTML em string dentro de `#app`; `livro.js` tem os cálculos e o gráfico SVG (rodam no Node nos testes e também na página avulsa do comando `grafico`, cujo CSS é embutido por `relatorio.py` sem as fontes); `busca.js`, `lista.js` e `recomenda.js` (junta as listas de parecidos dos livros de partida no início) são lógica pura. Todo arquivo novo que o site serve precisa entrar em `ARQUIVOS_WEB` (`site.py`), senão não é publicado nem versionado (`?v=` por hash).

## Convenções que os testes impõem

`tests/test_site.py` trava regras de interface; quebrar uma delas faz a suíte falhar, e a mensagem diz qual:

- Em `estilo.css`, toda cor tem token no tema claro **e** no escuro; tokens definidos precisam ser usados; `font-size` e `border-radius` vêm de `--fs-*` e `--r*`; `z-index` vem de `--z*`; `:hover` só dentro de `@media(hover:hover)`; o contraste dos pares de texto é medido (≥ 4,5:1, e ≥ 3:1 no contorno de campo).
- Nos modelos em JS (`app.js`, `livro.js`), `style="…"` só para largura, altura e `margin-top` de esqueleto e o `--h` da capa gerada.
- O foco depois de redesenhar uma tela é responsabilidade da tela (`focarTela`, `focoApos`): ao recriar ou remover um controle com `innerHTML`, devolva o foco a um equivalente.
- Os valores e as regras de cada componente estão em `design-system/precos-de-livros/MASTER.md` (e `pages/`); o CSS vence se discordarem.

## Outros

- `.claude/agents/` tem subagentes só de leitura (`search`, `grep`, `docs`); `.claude/skills/` tem as skills de design (`ui-ux-pro-max`, `design-taste-frontend`). Os scripts de `ui-ux-pro-max` rodam com `python3 -sE` (com `-I` a pasta do script sai do `sys.path`).
- `reviews/` guarda as auditorias de design e de DX já feitas; `docs/roadmap.md` explica por que o app é assim e o que ficou de fora de propósito (conta, alerta por e-mail, modo offline).
- Não há dependências de JavaScript: `node` só roda os `tests/*.test.js`.
