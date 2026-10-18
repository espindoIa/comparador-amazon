# Auditoria de UI, UX e motion design: site (`comparador/web`) com dados reais

**Perspective**: Design Engineer (UI, UX e movimento)
**Date**: 2026-10-18
**Plan**: nenhum plano foi indicado. Auditei o estado de `claude/elegant-keller-4e83wg` = `main` em `4bd96a4` ("Atualiza o layout do observador de preços de livros"), que acrescentou `referencia.css` (visual escuro e dourado) e reorganizou a página do livro. Nenhum arquivo do app foi alterado nesta tarefa.

## Plan Summary
Não há mudança proposta; é uma auditoria do que está publicado. O visual escuro e dourado foi escolhido pelo dono do projeto (comentário na 1ª linha de `referencia.css`), então os achados abaixo são correções **dentro** desse visual, não um pedido para voltar ao "livraria". O problema central é estrutural: a camada nova (`referencia.css`, 19 linhas) redefine os tokens e boa parte dos componentes **fora do alcance de todas as regras 🔒** de `TestFolhaDeEstilo`, que só lê `estilo.css`. Por isso a suíte passa enquanto o contraste, o tamanho dos campos no iPhone, os alvos de toque e o hover em tela de toque voltaram a falhar. Na UX, a página do livro deixou de mostrar as comparações que respondem à pergunta principal do site ("o preço de hoje é bom?"), e a página inicial antiga ficou sem nenhum link.

## Como foi feito (e o que não foi)
**Material de partida (bruto)**
- Bancos reais da release `catalogo`, baixados com `python scripts/catalogo_release.py baixar ALVO DESTINO.db`:
  - `catalogo-vendidos-2026-10-18-0840.db.gz`: a cópia de 11:14 deu 403 no proxy do ambiente e o script caiu na anterior.
  - `catalogo-vendidos-b-2026-10-17-0850.db.gz`.
  - `catalogo-vendidos-c-2026-10-18-0901.db.gz`.
- Site gerado com `python -m comparador site vendidos.db vendidos-b.db vendidos-c.db --saida site`, **sem `--subgeneros`**:
  - 211.559 livros e 152.224 obras;
  - `gerado_em` 2026-10-18T16:03:34Z, `lido_ate` 2026-10-17T08:49:54Z.
  - Foi servido com `python -m http.server`.
- Li inteiros, linha a linha: `app.js` (899 linhas), `livro.js`, `busca.js`, `lista.js`, `recomenda.js`, `estilo.css`, `referencia.css`, `index.html`, `404.html`, `manifest.json` e os SVG de ícone. Os estilos foram julgados pelo valor computado na página.
- Os livros de teste foram escolhidos nos dados reais:

  | ASIN | Caso |
  |---|---|
  | `8579604702` | o histórico com mais trechos |
  | `8546908087` | 3 formatos |
  | `1763628264` | 1 dia de preço, sem capa |
  | `1017254575` | título de 244 caracteres |
  | `000583919X` | sem coleta recente |

  Busca de exemplo: "harry potter".

**Ferramentas e parâmetros**
- Playwright 1.64 com o Chromium de `/opt/pw-browsers/chromium`.
- Larguras: 320, 375, 520, 600, 720, 900, 960 e 1280 px. São os pontos de quebra de `estilo.css` e `referencia.css`, mais 320 e 1280.
- Tema escuro (o padrão) e claro (pelo `localStorage`, como o botão `#tema` faz).
- `color_scheme` light e dark. **A emulação funciona neste ambiente**: `matchMedia('(prefers-color-scheme: dark)')` muda e os tokens que seguem o sistema mudam junto. Isso desmente a ressalva da auditoria anterior, que forçou o bloco escuro como `:root`.
- `forced_colors="active"`, `reduced_motion="reduce"`, `has_touch` + `is_mobile` (confirmado: `pointer: coarse` casa).
- Página de 640 px no lugar do zoom de 200%; CSS do critério 1.4.12 injetado na página.
- axe-core 4.10.2 (cdnjs), injetado na página e fora do repositório. Tags: `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, `wcag22aa` e `best-practice`. Rodou em 19 telas e estados × 2 larguras × 2 temas.
- Contraste medido de dois jeitos:
  1. nas cores computadas de cada texto contra o fundo efetivo, compondo o alfa;
  2. pela fórmula dos tokens, a mesma de `test_contraste_dos_pares_de_texto_nos_dois_temas`.
- Movimento:
  - `document.getAnimations()` durante as interações e inventário de `transition`/`animation` no estilo computado;
  - CPU 4× mais lenta (`Emulation.setCPUThrottlingRate`), com `PerformanceObserver` de `long-animation-frame`, `layout-shift` e `event` (Event Timing).
- Piscada do tema: `Page.startScreencast` com a rede emulada a 300 ms de latência e 160 KB/s.

**Escala de severidade**: Nielsen, de 0 (não é problema) a 4 (catástrofe). **Etiquetas**: [medido] (número tirado da página ou dos dados), [renderizado] (visto em captura ou na árvore de acessibilidade), [julgamento] (opinião de design, sem verificação externa).

**Não feito**: ver "O que não pôde ser verificado aqui", no fim.

## Linha de base
- **Suíte**: `COMPARADOR_NAVEGADOR=/opt/pw-browsers/chromium python -m unittest discover -s tests` rodou 348 testes em 113,8 s.
  - Resultado: **1 erro**. `TestSiteNoNavegador` rodou de fato, sem pulos: os 13 testes de navegador aparecem no log.
  - O erro é em `test_livro_sem_coleta_recente_continua_na_lista` (`tests/test_site.py:787`), com `TypeError: Cannot read properties of null (reading 'textContent')`.
  - Rodado sozinho, passou 3 vezes em 3.
  - **Causa**: o predicado de `wait_for_function` lê `#res` antes de a busca criar o elemento, e uma exceção no predicado derruba a espera. É uma corrida do teste, não do app. Basta trocar por `document.querySelector('#res')?.textContent.includes(...)`.
- O commit `4bd96a4` trocou `pg.goto(f"{base}/")` por `?inicio` em 8 testes de navegador. Esses testes passaram a cobrir uma tela que nenhum link do site abre (ver U2).

## Files Reviewed
| File | Visual Role | Risk |
|------|-------------|------|
| `comparador/web/referencia.css` | Camada nova: redefine tokens, fontes, cabeçalho, busca, linhas de resultado, página do livro | **Alto** (fora das regras 🔒) |
| `comparador/web/estilo.css` | Tokens originais, componentes, temas, toque, movimento reduzido, alto contraste | Médio |
| `comparador/web/app.js` | Rotas, todas as telas, foco, aviso rápido, `organizarLivro` (reordena a página do livro depois de desenhada) | Alto |
| `comparador/web/livro.js` | Gráfico SVG, estatísticas, eventos | Baixo |
| `comparador/web/index.html`, `404.html`, `manifest.json`, `*.svg` | Cabeçalho, busca, ícones de imagem, cores do tema do navegador | Médio |
| `busca.js`, `lista.js`, `recomenda.js` | Lógica pura (busca, lista, parecidos) | Baixo |

## Verdict: REQUEST CHANGES
O app funciona com 211 mil livros:
- não houve erro de JavaScript em 92 capturas;
- nenhum elemento sai da janela em 320 px;
- a rolagem volta certa no "voltar" do navegador;
- a busca por ISBN vai direto ao livro;
- o movimento é curto, só em `opacity`/`transform`/cores, e respeita `prefers-reduced-motion`.

O que impede aprovar:
1. **Duas camadas de tokens que se misturam.** Os tokens que `referencia.css` não redefine continuam seguindo o tema do **sistema**, enquanto os outros seguem `data-theme`. Num sistema claro com o tema padrão (escuro), as pílulas "caiu"/"subiu" medem 2,03:1 e 2,77:1.
2. **Falhas WCAG AA medidas no tema claro**: rótulos das estatísticas a 1,58–3,07:1, "Filtros" e contagem a 3,31:1, linha do gráfico a 1,57:1, contorno dos campos a 1,56:1.
3. **A comparação com o "preço mais comum" e com o preço de capa sumiu da página do livro**: o CSS esconde e o JS remove.

## Critical Issues (Must Fix)
| # | Issue | File(s) | Impact | Fix |
|---|-------|---------|--------|-----|
| C1 | **Tokens de duas fontes.** `referencia.css:2` redefine no `:root` só uma parte dos tokens. `--dns`, `--ups`, `--wr`, `--wrs`, `--evl`, `--ev`, `--capa` e `--filete` ainda vêm de `estilo.css:10-34` e seguem `prefers-color-scheme`, não o `data-theme` do botão. **[medido]** em `saida/tema.json`: sistema claro + tema escuro dá `--dns:#e1f0e5` (fundo de pílula claro) com `--dn:#71b77c`. **[renderizado]** na lista com mudanças de preço (`conferencia-lista-pilulas-sistema-claro.png`): "▼ 1 ficou mais barato" e "chegou" a 2,03:1; "▲ … mais caros" a 2,77:1. Com o sistema escuro, `.pill.up` fica em 4,43:1. **[derivado dos tokens]**, porque nenhum evento cai na janela de dados: `--evl` (nome da promoção no gráfico) dá 2,58:1 no tema escuro com sistema claro e 1,83:1 no tema claro com sistema escuro. Severidade **4**. | `referencia.css:2-3`; `estilo.css:10-34`; `app.js:6` | O caso mais comum (sistema claro, tema padrão) é justamente o que quebra. Verde e vermelho são o sinal de "caiu/subiu" da lista. | Redefinir todos os tokens de cor nos dois blocos de `referencia.css` (`:root` e `:root[data-theme=light]`), e tirar de `estilo.css` o bloco `prefers-color-scheme` ou fazê-lo valer só sem `data-theme`. Ver também C4. |
| C2 | **Contraste de texto no tema claro.** **[medido]** nas cores computadas e confirmado pelo axe (`color-contrast` em 26 combinações de tela, largura e tema): rótulos das estatísticas do livro "Menor preço" 2,19, "Maior preço" 3,07 e "Preço atual" 1,58, pintados por posição em hexadecimal (`.stats>div:nth-child(n) span`); "Filtros" e a contagem "106 livros até agora" em `--mu2` a 3,31; erro de campo do preço-alvo (`--up` `#ef5657` sobre `#fffdf8`) a 3,37; "Ver todos" e chip ligado (`--ac` `#936822` sobre `--bg`) a 4,46. No tema escuro, só `.pill.up` fica abaixo de 4,5 (4,43). Severidade **3**. | `referencia.css:3,8,11` | Os números que dão sentido ao preço (menor e maior) e o aviso de erro de campo estão entre os textos de menor contraste. | Cores das estatísticas vindas de tokens (`--dn`, `--up`, `--ac`), com versão clara própria (por exemplo `--dn:#146c43` e `--up:#a8321c`, que `estilo.css` já usava). "Filtros" e `.cont` em `--mu`. Escurecer `--ac` claro para ≥ 4,5 sobre `--bg`. |
| C3 | **A página do livro não responde mais "o preço de hoje é bom?".** `.compra .fat{display:none}` esconde a comparação com o preço mais comum, "Menor preço registrado", "Sem coleta recente" e "Preço de capa R$ 49,99 (39% abaixo)". `organizarLivro` tira da grade a célula "Preço mais comum" e "Acompanhado desde". `.l-cab .det,.l-gens{display:none}` esconde nota, avaliações, data e gêneros. **[renderizado]** em `8595205760`: o texto "39% abaixo" está no DOM e invisível. **[medido]** com `livro.js` sobre os 212.072 históricos (`scripts/dias.js`): **hoje nenhum livro tem 14 dias com preço** (o maior intervalo é de 7 dias), então a mediana ainda não aparece em lugar nenhum. O custo de esconder a comparação é pequeno hoje e cresce com a coleta a partir do 14º dia. Já o preço de capa riscado e a nota valem desde já. Severidade **3** (pode ser decisão de produto; confirme com o dono). | `referencia.css:11`; `app.js:632-639` | Sem as pílulas, sobra um número e um gráfico. O MASTER manda a comparação vir em texto ("12% abaixo do comum") porque cor sozinha não basta. | Manter `.fat` visível no visual novo (pílulas abaixo do preço grande) e a célula "Preço mais comum" na grade. Se a ideia é enxugar, a célula "Preço atual" repete o preço grande e pode sair no lugar dela. |
| C4 | **Contorno de campo abaixo de 3:1 (WCAG 1.4.11) nos dois temas.** `referencia.css:8` usa `--ln2` na borda de `.sel select` e de `.chip` (1,62:1 no escuro, 1,56:1 no claro). O fundo desses controles é o mesmo da página (`--bg`), então só a borda mostra o controle. Até o `--ln3` novo do escuro (`#46545f`) dá **2,34:1** sobre `--sf`: o teste de contraste o aprovaria pelo valor de `estilo.css` (`#85796a`, 4,0:1), mas a página renderiza o de `referencia.css`. O campo de busca no tema claro (`#faf9f6` com borda `#e8c98e` sobre `#f6f3eb`) também não chega a 3:1. **[medido]** `saida/contraste.json`, seção "campos". Severidade **3**. | `referencia.css:2,7,8` | É a regressão de R6 da auditoria anterior. Os seletores de ordem e de gênero quase somem no escuro. | `--ln3` escuro em torno de `#6b7a86` (≥ 3:1 sobre `--bg` e `--sf`) e borda de campo e chip em `--ln3`. |

## Recommendations
| # | Issue | File(s) | Why | Fix |
|---|-------|---------|-----|-----|
| U1 | **As regras 🔒 não alcançam `referencia.css`.** `TestFolhaDeEstilo` (`tests/test_site.py:522`) lê só `estilo.css`. **[medido]** com as mesmas expressões regulares sobre `referencia.css`: 56 `font-size` em px e 9 `font:` com px; 18 `border-radius` em px; 22 cores hexadecimais soltas fora de tokens; `z-index:45` solto; 4 regras de `:hover` fora de `@media(hover:hover)` (`a:hover`, `.hint:hover::after`, `.resultado-livro:hover`, `.resultado-livro .row:hover`); borda de select em `--ln2`. O `MASTER.md` diz que, se o texto e o CSS discordarem, vale o CSS e corrige-se o texto. Hoje os dois lados divergem: o MASTER descreve Cormorant, Crimson e o tema "livraria", e as travas não cobrem o CSS em vigor. Severidade **3**. | `tests/test_site.py:522`; `referencia.css`; `MASTER.md` | É a raiz de C1, C2, C4, U4, U6 e U7: a suíte não tem como avisar. | Fundir `referencia.css` em `estilo.css` (tokens nos dois temas, componentes no lugar) ou fazer `TestFolhaDeEstilo` ler as duas folhas; depois atualizar o MASTER (direção, fontes, tokens). |
| U2 | **A página inicial antiga ficou órfã.** `rota()` (`app.js:245-246`) manda `./` para a busca; `?inicio` só abre digitando o endereço (nenhum link, nem o da marca nem o "Ir para o início" do 404). Saíram do caminho de quem usa: "Baixaram de preço", "No menor preço registrado", "Gêneros", "Vistos recentemente", "Sua lista" e "Parecidos com os seus livros". Os 8 testes que agora abrem `?inicio` cobrem uma tela invisível. **[medido]** por busca no código. Severidade **2** (decisão de produto declarada no commit; confirmar). | `app.js:244-246`, `index.html:25` | Navegar por gênero e "parecidos com os seus livros" são as únicas entradas sem saber o título. Na busca, o gênero ficou dentro de "Filtros", fechado. | Ou um link visível para `?inicio` ("Explorar"), ou trazer as estantes para a busca vazia. Senão, apagar `inicio()` e os testes que só servem a ele. |
| U3 | **Tema: padrão ignora o sistema, pisca e não diz o estado.** `app.js:6` abre em `'dark'` sem olhar `prefers-color-scheme`. **[medido]** `piscada.json`: com o tema claro salvo e a rede lenta, a página pinta **escura** em 1,35 s e só fica clara em 1,96 s, porque `data-theme` é aplicado no fim do `body`. O botão `#tema` é "Alternar tema" sem `aria-pressed` nem nome que diga o tema atual, e o ícone é sempre o sol (**[renderizado]** na árvore de acessibilidade). `meta theme-color` (`index.html:12-13`) e `manifest.json` (`#faf5ea`) seguem as cores antigas: barra do navegador e tela de abertura creme num app escuro. Severidade **2**. | `app.js:6,814`; `index.html:12-13`; `manifest.json` | Quem usa o sistema claro recebe o escuro, e quem escolheu o claro vê o escuro a cada carga lenta. | `<script>` inline no `<head>` lendo `observador-tema` e, sem valor salvo, `matchMedia('(prefers-color-scheme: dark)')`. No botão, `aria-pressed` ("Tema escuro") ou nome com o destino ("Usar tema claro"), e o ícone trocando. Atualizar `theme-color` no clique e alinhar o manifesto. |
| U4 | **Campos menores que 16 px voltaram (V1 regrediu).** `.sel select` tem 14 px (`referencia.css:8`), 12 px até 719 px (`:13`) e 11 px até 419 px (`:17`). **[medido]** valor computado. O zoom em si é comportamento do Safari, não reproduzido aqui. Severidade **3**. | `referencia.css:8,13,17` | Ordenar e escolher gênero são os controles mais usados no celular, e o Safari amplia a página ao focar e não volta. | `font-size:16px` em `select` em qualquer largura. Se o rótulo não couber, encurtar o texto da opção, não a fonte. |
| U5 | **Cada resultado tem 4 paradas de Tab, 3 para o mesmo endereço.** **[medido]** `foco.json`: o link da linha, "Ver histórico de preço" (mesmo `href`), o sino e "Ver detalhes" (mesmo `href`, 16×16 px). São 120 paradas para 30 resultados. "Ver detalhes" falha no **WCAG 2.5.8** (axe `target-size` em 30 nós; meu cálculo de espaçamento confirma). As dicas (`data-tip`) dizem outra coisa que o nome acessível ("Evolução de preço na Amazon" × "Ver histórico de preço"). Severidade **2**. | `app.js:163`; `referencia.css:9` | Leitor de tela e teclado andam 4× mais. O "Ver detalhes" pequeno é a seta `›`, que repete a outra seta decorativa (`.row-dir`) da mesma linha. | Tirar `.row-fim` e o link de histórico (a linha inteira já leva lá); manter só o sino como segundo controle. |
| U6 | **Dicas (`.hint::after`) não fecham com Esc e não são alcançáveis pelo ponteiro (WCAG 1.4.13).** **[medido]** a opacidade continua 1 depois de Esc. Com `pointer-events:none`, não dá para passar o mouse sobre a dica. `.busca-dica` é um `span` com `tabindex=0` e `aria-label`, sem papel: o axe marca `aria-prohibited-attr` em **todas** as telas que têm cabeçalho (68 combinações). Na página do livro, a dica da data da coleta tem nome acessível "Data da coleta" e **a data não chega ao leitor de tela**: ela só existe no `content` do pseudo-elemento. Em tela de toque, `.hint:hover` fica preso (hover fora de `@media(hover:hover)`). Severidade **3**. | `index.html:30`; `app.js:635`; `referencia.css:7` | Informação só visual (a data da coleta) e um alvo de Tab que não faz nada. | Na busca, texto de ajuda fixo abaixo do campo (ou nada, já que o placeholder diz o mesmo). No livro, a data no texto visível ("Preço atual na Amazon · coletado em 18/10"). Se ficar a dica, `role="button"` + `aria-describedby`, Esc fecha, hover só com `hover:hover`. |
| U7 | **Alvos de toque abaixo da regra do MASTER (≥ 40 px no toque).** **[medido]** `alvos.json` em 375 px com `pointer:coarse`: "Como funciona" e o tema com 30×34, "Minha lista" com 26×36, ações da linha com 32×36, alternância lista/grade com 32×40, "Definir preço-alvo" com 111×20 e "Mudar" com 39×20. Todos passam os 24 px do 2.5.8, menos "Ver detalhes" (U5). Como `referencia.css` tem seletores mais específicos, a regra `@media(pointer:coarse){.ib{44px}}` de `estilo.css:369` perde. Severidade **2**. | `referencia.css:13,16` | Os três ícones do cabeçalho ficam colados no canto, com 2 a 4 px entre eles. | Área de toque de 44 px com padding ou `::before`, mantendo o desenho. |
| U8 | **Foco perdido ao fechar os filtros e "Filtros" que fecha sozinho.** **[medido]** com o filtro aberto, ligar e desligar "Kindle" redesenha `<details>` fechado (`app.js:468`, aberto só se houver filtro), e o foco vai para o `body`. Com "Filtros" aberto e sem filtro ativo, digitar uma letra na busca também fecha o painel. Severidade **2**. | `app.js:468,472` | Viola a regra do MASTER ("o controle recriado recebe o foco de volta") e faz a pessoa reabrir o painel a cada tecla. | Guardar o estado aberto (uma variável como `verPreco`) e passar `open` quando a pessoa abriu. |
| U9 | **O sino da busca leva embora da busca.** **[medido]** `[data-watch]` (`app.js:812`) salva o livro na lista **sem aviso** e navega para `?lista` com o campo de preço-alvo aberto. O "voltar" do navegador devolve a busca na mesma rolagem (**[medido]**, 1500 → 1500 px). A dica diz "Acompanhar com preço-alvo", mas não diz que vai trocar de tela nem que já salvou. Severidade **2**. | `app.js:163,812` | Na busca, o normal é marcar vários livros sem sair da lista de resultados. | Abrir o campo de preço-alvo no lugar (num popover) ou salvar e mostrar o toast "Salvo · Definir preço-alvo". |
| U10 | **Depois do "voltar", o foco vai ao topo e não ao livro de onde a pessoa veio.** **[medido]** a rolagem é restaurada (1500 px), mas o foco vai ao `h1` escondido (`#bh`), no alto da página. O próximo Tab volta ao começo dos resultados. O botão "Voltar aos resultados" diz "resultados" mesmo quando a pessoa chegou por link e ele leva à busca vazia. Severidade **2**. | `app.js:264-272,604` | Quem navega por teclado perde o lugar a cada livro aberto. | Guardar o `href` ativado no `history.state` e focá-lo ao voltar; rótulo "Voltar" quando `history.state.n` é 0. |
| U11 | **Ordem do Tab ≠ ordem visual no cabeçalho.** **[medido]** na tela, a ordem é marca, Minha lista, Como funciona, tema. No Tab é marca, Como funciona, tema, busca (5 paradas, incluindo a dica) e só então Minha lista (`index.html:26-31`, com a posição feita em grid no CSS). Severidade **1** (WCAG 2.4.3 só se a ordem confundir; aqui confunde pouco). | `index.html:26-31`; `referencia.css:6` | | Pôr o link da lista antes de `nav.header-tools` no HTML. |
| U12 | **Cores forçadas (Windows alto contraste).** **[renderizado]** `extra-forced-busca-texto.png`: os ícones são `<img>` com traço fixo (`sun.svg` e `help-circle.svg` em `#f4f3f1`, `info.svg` e `book-open.svg` em `#efca82`) e quase somem no fundo branco. O estado ligado da alternância lista/grade não tem contorno (`outline: none`; o fundo dourado é removido). A sparkline continua azul. Severidade **2**. | `index.html:25-30`; `referencia.css:8`; `estilo.css:380-384` | O N1 anterior foi feito para os controles antigos; os novos ficaram de fora. | SVG em linha com `stroke="currentColor"` (como os de `IC` em `app.js`) e `.view-switch [aria-pressed=true]` na regra de `forced-colors`. |
| U13 | **Desempenho de interação (laboratório).** **[medido]** com CPU 4× e servidor local sem latência (não é INP de campo): primeiros resultados em 2,9–3,3 s e índice completo em 10,4–11,2 s; cerca de 100 *long animation frames*, o maior com 0,75–1,2 s (em `app.js`, ao carregar); o atraso de entrada de uma tecla na busca chegou a 395 ms (interação de 432 ms, faixa "precisa melhorar" do INP, que é 200–500 ms). CLS 0,018–0,063, abaixo de 0,1: o rodapé desce quando a busca desenha. Severidade **2**. | `app.js:61-104`; `busca.js:119-127` | Num celular médio, digitar enquanto o índice chega engasga, e "Buscando no restante do catálogo…" fica cerca de 10 s na tela. | Medir em aparelho; avaliar mover `lerObras` e o vocabulário para um Web Worker. Reservar a altura dos resultados para o rodapé não pular. |

## Nice-to-Haves
| # | Suggestion | Rationale |
|---|------------|-----------|
| N1 | Tirar o `preload` de `cormorant-600.woff2` (`index.html:18`) | **[medido]** a fonte é baixada (21 KB) e não usada: `--display` agora é Georgia (`referencia.css:2`) e `document.fonts` não tem nenhuma face carregada. O Chromium não avisou no console nesta execução. As outras três `woff2` não são baixadas. |
| N2 | Um só "Ver na Amazon" na página do livro | **[renderizado]** há dois botões primários iguais (`app.js:607` e `:638`), um no topo e outro em "Informações do livro". "Compartilhar" foi removido por `organizarLivro` (`app.js:633`) e só existe na lista. Confirmar se foi de propósito. |
| N3 | Data de publicação formatada | **[renderizado]** "Data de publicação 2023-09-01" (ISO cru, `app.js:637`); o resto do site usa "1 set 2023". "Editora: Não informado" aparece em quase todos os livros (o banco não tem editora): melhor omitir a linha. |
| N4 | Borda dourada do 1º resultado | **[julgamento]** `.resultado-livro:first-child{border-color:#dfbf82}` parece seleção ou foco, mas é só o primeiro da lista. Em "Menor preço" ele não é o destaque de nada. |
| N5 | Sparkline sem informação | **[medido]** com no máximo 7 dias, quase todas as sparklines são retas. Ocupam 140 px por linha e usam um azul (`#678bee`) que não está em nenhum token. Esconder com menos de 2 preços diferentes. |
| N6 | `.row .pr .pill{font-size:9px}` e `.stats small{font-size:9px}` | **[medido]** "preço de 15 out" e as datas das estatísticas com 9–10 px no celular. É legível no limite e fica fora da escala. |
| N7 | Marca "Observador de preços da amazon" | **[julgamento]** "amazon" em minúscula e um nome diferente do `<title>`, do manifesto e do rodapé ("Preços de livros"). Usar o nome da loja na marca reforça uma ligação que o rodapé nega. |

## Status da auditoria anterior (`audit-as-design-eng.md`)
| # | Estado | Evidência |
|---|---|---|
| V1 campos a 14 px | **Voltou** | Selects com 14/12/11 px em `referencia.css:8,13,17` (U4). Faixa de preço e preço-alvo seguem com 16 px. |
| V2 texto em `--mu2` | **Voltou** | `.cont`, `.filtros-extra summary` (`referencia.css:8`): 3,31:1 no claro; passam no escuro (5,14). |
| R1 foco da linha da lista | Corrigido, conferido | Pelo Tab, a linha ganha contorno sólido de 2 px e o link fica sem anel (`conferencia-R1-foco-lista.png`). |
| R2 escala sem tokens | Corrigido em `estilo.css`, **voltou** pela camada nova | 12 degraus `--fs-*` travados; `referencia.css` tem 56 `font-size` em px e 18 raios em px. |
| R3 tokens sem uso | Corrigido | Travado pelo teste em `estilo.css`. |
| R4 hover fora de `hover:hover` | Corrigido em `estilo.css`, **voltou** | 4 regras em `referencia.css` (U1). |
| R5 alvos de toque | Corrigido em `estilo.css`, **voltou** | U7. |
| R6 borda de campo | Corrigido em `estilo.css`, **voltou** | C4. |
| R7 `viewport-fit=cover` | Corrigido | Removido de `index.html:4`. |
| R8 ícones PNG | Corrigido; a cor ficou aberta | PNG de 180, 192 e 512 px (mais o maskable); `theme_color` do manifesto não bate com o app escuro (U3). |
| N1 cores forçadas | Parcial | Os controles novos ficaram de fora (U12). |
| N2 movimento reduzido no `.giro` | Corrigido | Gira em 2,4 s com `reduce` (medido). |
| N3 regras sem uso | Aberto | `.btn.salvar svg{transition:transform .2s}` (`estilo.css:277`, nada muda o `transform`) e `.seg button:disabled` (`:126`). |
| N4 texto de 9 px na capa gerada | Aceito | Exceção documentada (`estilo.css:143`). |
| N5 `style=` nos modelos | Corrigido | Travado pelo teste. |

## Percurso cognitivo (cognitive walkthrough)
Cinco tarefas reais em 375 e 1280 px, tema padrão. Para cada passo: a pessoa sabe o que fazer, vê o controle, entende a resposta?

1. **Achar um livro pela busca** ("harry potter").
   - Campo grande e óbvio; primeiros resultados em 2,9 s com CPU 4× (não medi sem desaceleração).
   - Hesitação: o ⓘ solto acima do campo parece um aviso, mas é só a dica (U6).
   - "Buscando no restante do catálogo…" dura cerca de 10 s em aparelho lento, e a contagem diz "até agora" (U13).
   - ISBN (`9788532530783`) vai direto ao livro, um ótimo atalho.
   - Heurísticas: 1 (visibilidade do estado), boa; 8 (estético e minimalista), duas setas e dois ícones por linha (U5).
2. **Decidir pelo histórico se o preço de hoje é bom** (`?livro=`).
   - O preço grande e o gráfico aparecem, mas a resposta não: sem pílulas nem "Preço mais comum" (C3).
   - A pessoa tem de comparar a olho os números "Menor" e "Maior", coloridos por posição (C2).
   - A data da coleta fica atrás de um ⓘ (U6).
   - Com 7 dias de dados, o seletor de período não existe (só aparece com mais de 30 dias) e não há linha do preço mais comum.
   - Heurísticas: 6 (reconhecer em vez de lembrar) e 10 (ajuda): **severidade 3**.
3. **Salvar e rever a lista** (`?lista`).
   - Salvar: o coração dá um toast "Salvo na sua lista · Ver lista", claro.
   - Pelo sino na busca, a pessoa é levada à lista sem aviso de que salvou (U9).
   - Na lista: "Desde sua visita de …" e as pílulas funcionam, mas ficam ilegíveis com o sistema claro (C1).
   - "Definir preço-alvo" é um link de 20 px de altura (U7).
   - Heurística 4 (consistência): o sino tem dois comportamentos (livro: lista + alvo; busca: o mesmo, mas sai da tela).
4. **Chegar a um parecido.**
   - Só pela página do livro ("Parecidos com este livro", no fim). "Parecidos com os seus livros" existe só em `?inicio`, sem link (U2).
   - Heurística 7 (flexibilidade): a exploração sem título ficou difícil.
5. **Voltar com o botão do navegador.**
   - A rolagem volta exata (1500 px) e o endereço da busca é mantido.
   - O foco vai ao topo (U10).
   - Do sino, o voltar também restaura a busca.

## Motion
**Inventário [medido]** (`saida/motion.json`):

| Peça | Propriedade | Duração / curva | Função |
|---|---|---|---|
| `.btn` | `background`, `border-color`, `transform` (scale .98 no `:active`) | 150 / 150 / 100 ms, `ease` | feedback de toque |
| `.chip`, `.leg button` | `border-color`, `transform` | 150 / 100 ms | feedback |
| `.row`, `.resultado-livro`, campos | `border-color`, `box-shadow` | 150 ms | feedback de hover e foco |
| `.toast` | `opacity` + `translateY(20px)` | 200 ms, `ease` | entrada de mensagem (mudança de estado) |
| `.sk` (esqueleto) | `background-position` | 1,2 s linear, infinito | carregando |
| `.giro` | `rotate` | 0,8 s linear, infinito (2,4 s com `reduce`) | "buscando no restante" |
| `.btn.salvar svg` | `transform` 200 ms | nada muda o `transform` | regra morta (N3) |

- **Referência**: os tokens de duração do Material Design 3 (*short* 50–200 ms para feedback de controle; *medium* 250–400 ms para elementos que entram) e as Apple HIG (movimento breve, com propósito). Tudo fica entre 100 e 200 ms. O toast entra em 200 ms com `ease`; o M3 usaria uma curva de desaceleração "emphasized" e 250–300 ms para algo que entra. A divergência é defensável num aviso pequeno **[julgamento]**.
- **Só propriedades baratas**: `transform`/`opacity` no que se mexe e cor nas bordas. Nenhuma transição mexe em layout.
- **Troca de tema [medido]**: o clique dispara 27 transições de `border-color` (150 ms) em botões e na legenda, enquanto fundo e texto trocam na hora. As bordas "atrasam" o resto **[julgamento: pequeno, mas é ruído]**. Para trocar de vez, desligar as transições durante a troca (`:root.trocando *{transition:none}` por um quadro).
- **Onde falta movimento [julgamento]**:
  - Troca de tela, entrada de resultados e aparição do gráfico são trocas de `innerHTML`, sem transição. Para uma ferramenta de consulta isso é aceitável: o esqueleto e o foco no título já dão continuidade.
  - O único ponto em que movimento ajudaria é a abertura de "Filtros" (`<details>` abre seco, e U8 o fecha sozinho).
  - Não recomendo View Transitions entre telas: o custo de JS na carga (U13) é o gargalo, não a falta de animação.
- **Custo [medido]**: CLS de 0,018 a 0,063, causado pelo rodapé, não por animação. Os *long animation frames* vêm de JS (`lerObras`, montagem do vocabulário, `innerHTML` de 30 linhas), não de movimento. Ver U13.
- **`prefers-reduced-motion: reduce` [medido]**:
  - todas as transições vão a 0 s e `scroll-behavior` fica `auto`;
  - o esqueleto para (nenhuma animação em `getAnimations()`);
  - o `.giro` continua a 2,4 s.
  - O toast aparece e some sem transição, mas continua sendo anunciado (`role="status"`, `aria-live="polite"`), então nenhum estado deixa de ser comunicado.
  - Hover em tela de toque (`.resultado-livro:hover` fora de `hover:hover`) deixa a linha "acesa" depois do toque, com ou sem `reduce` (U1).

## Design System Compliance
- **Cores**: duas fontes de token com prioridades diferentes (C1). `referencia.css` tem 22 hexadecimais fora de tokens: busca `#faf9f6`/`#e8c98e`/`#f0ca86`, dicas `#111a24`/`#475561`, estatísticas `#79bd83`/`#ef6565`/`#edc77f`, sparklines, linha do gráfico `#f1c778` (1,57:1 sobre o cartão claro, abaixo dos 3:1 do 1.4.11 para objeto gráfico) e o 1º resultado.
- **Série por cor**: `--med` (`#f0c97f`) passou a ser o mesmo dourado da linha de preço (`#f1c778`), nos dois temas. O MASTER pede `--med` frio "para não se confundir com o marrom". Hoje a linha só aparece com 14 dias, então não foi renderizado; o tracejado diferencia, mas a cor não.
- **Tipografia**: Georgia e Arial no lugar de Cormorant, Crimson e a fonte do sistema. Os `h1` com `font-weight:400`. Todos os tamanhos em px (56). Com a fonte do navegador em 200%, o corpo continua em 15 px **[medido]**. O zoom de página funciona (WCAG 1.4.4 atendido pelo zoom), mas quem só aumenta a fonte padrão não ganha nada.
- **Ícones**: dois sistemas, SVG em linha com `currentColor` (`IC`) e `<img>` com cor fixa, que não seguem o tema (o claro usa `filter:invert(1)` só em `.header-tools`) nem o alto contraste (U12). `info.svg` dourado sobre o fundo claro dá 1,41:1, e ele é o único sinal visual de um controle focável.
- **Paridade claro/escuro**: o escuro foi desenhado e o claro foi derivado. Quase todas as falhas de contraste são do claro (C2, C4).

## Visual State Coverage
"n/a" = o estado não existe para o elemento. "✗" = existe e não tem tratamento.

| Component/Element | Hover | Focus | Active | Disabled | Loading | Empty | Error | Dark Mode |
|-------------------|-------|-------|--------|----------|---------|-------|-------|-----------|
| Linha de resultado (`.resultado-livro`) | ✓ (fora de `hover:hover`, U1) | ✓ | n/a | n/a | ✓ esqueleto | ✓ `.vazio` | ✓ "Parte do catálogo não carregou" | ✓ |
| Ações da linha (`.row-acoes .ib`) | ✓ dica | ✓ | ✗ | n/a | n/a | n/a | n/a | ✓ |
| Alternância lista/grade | ✗ | ✓ | ✗ | n/a | n/a | n/a | n/a | ✓ (✗ em cores forçadas) |
| `select` (ordem, gênero) | ✓ | ✓ | n/a | n/a | n/a | n/a | n/a | ✗ contorno 1,62:1 |
| Botão de tema | ✓ dica | ✓ | ✗ | n/a | n/a | n/a | n/a | ✗ sem estado anunciado |
| Dica `.hint` | ✓ | ✓ | n/a | n/a | n/a | n/a | n/a | ✗ não fecha com Esc |
| Página do livro | n/a | ✓ região | n/a | n/a | ✓ esqueleto | ✓ "Livro não encontrado" | ✓ `erro()` | ✓ |
| Lista | n/a | ✓ | n/a | n/a | ✓ | ✓ | ✓ campo (`role=alert`) | ✗ pílulas (C1) |
| Busca vazia, 404, erro de carga | n/a | ✓ `h1` | n/a | n/a | n/a | ✓ | ✓ | ✓ (axe sem violação de contraste) |

## Verdict Details
- Design Token Fidelity: **FAIL** (C1, U1)
- Visual State Coverage: CONCERNS (U6, U8, U12)
- Dark Mode Parity: **FAIL** (o claro reprova em C2 e C4; o escuro depende do tema do sistema em C1)
- Animation Quality: PASS (curta, barata, respeita `reduce`; ressalvas na troca de tema e na regra morta N3)
- Visual Consistency: CONCERNS (dois sistemas de ícone, 56 tamanhos em px, cores por posição)
- UX da tarefa principal: **FAIL** (C3)

## O que foi verificado externamente, o que é julgamento e o que não foi verificado
**Verificado por fonte externa**
- Suíte do repositório: 347 de 348, com o erro instável explicado acima.
- axe-core 4.10.2: `aria-prohibited-attr` (68 combinações), `color-contrast` (26), `target-size` (6, os mesmos 30 nós de U5), `landmark-complementary-is-top-level` (o `aside` da capa dentro da região do livro, 24) e `page-has-heading-one` (esqueleto de carga, 4).
- Critérios WCAG 2.2 AA conferidos à mão:
  - 1.4.10 (reflow): **passa**, nenhum elemento sai da janela em 320 px. O `scrollWidth` passa de 6 a 45 px em 520–960 px (as estantes e possivelmente dicas de canto, escondidas por `html{overflow-x:clip}`); não confirmei se alguma dica visível é cortada.
  - 1.4.12 (espaçamento de texto): **passa**, sem texto novo cortado nas três telas principais.
  - 2.4.7: **passa**, todo controle alcançado pelo Tab tem anel.
  - 2.4.11: **passa** no que testei; 40 Tabs com o toast aberto em 375 px e nada coberto.
  - 2.5.8: falha só em "Ver detalhes".
  - 4.1.3: **passa**; contagem em `#cont-res`, toast `role=status`, valor do gráfico em `aria-live`.
  - 1.4.13: **falha** (U6).
- Medições do navegador: valores computados, `getAnimations()`, Event Timing, LoAF, layout shift, screencast.
- Contraste por dois métodos. Onde divergem, o teste dos tokens aprova e a página reprova: o teste lê `estilo.css` e a página pinta `referencia.css` (o caso do `--ln3` escuro em C4).

**Só julgamento**: N4, N7, a leitura de severidade de cada item, a avaliação do motion contra o M3 e as HIG, e se C3, U2 e N2 são decisões de produto.

**O que não pôde ser verificado aqui**
- Safari no iPhone: o zoom ao focar (U4) é comportamento conhecido, não reproduzido.
- Leitores de tela reais (VoiceOver, NVDA, TalkBack): usei a árvore de acessibilidade do Playwright (`aria_snapshot`) como substituto.
- Aparelhos lentos de verdade: U13 é laboratório (CPU 4×, rede local).
- Pessoas reais usando o site: o percurso cognitivo é uma simulação.
- Com os dados de hoje (no máximo 7 dias por livro), não aparecem e não foram renderizados:
  - o seletor de período do gráfico (pede mais de 30 dias);
  - a linha e a célula do preço mais comum (14 dias);
  - a faixa e o nome das promoções no gráfico (nenhum evento na janela);
  - `--evl` saiu só da conta dos tokens.
- Os subgêneros (`.sec-h .nota`) ficaram fora porque o site foi gerado sem `--subgeneros`.

## Como refazer
Os scripts ficaram na scratchpad desta sessão e não foram para o repositório. Peça se quiser que eu os ponha em `scripts/auditoria/`. Para refazer, gere e sirva o site como descrito em "Como foi feito" e rode os scripts com `AUDIT_BASE=http://127.0.0.1:8765`:

| Script | O que mede |
|---|---|
| `comum.py` | Livros, telas e estado do `localStorage` |
| `tema.py`, `piscada.py` | C1 e U3 |
| `capturas.py` | 92 capturas e transbordamento horizontal |
| `axe.py` | axe-core em 19 telas e estados |
| `contraste.py` | C2 e C4 |
| `alvos.py` | 2.5.8 e U7 |
| `foco.py` | U5, U6, U8 a U11 |
| `motion.py` | Inventário, CPU 4× e `reduce` |
| `extras.py` | 1.4.12, cores forçadas, zoom |
| `conferencias.py` | Voltar do navegador, pílulas, R1, preload |
| `dias.js` | Contagem de dias por livro com o `livro.js` do repositório |

Entradas fixas: os ASIN da tabela de "Como foi feito", axe-core 4.10.2 com as tags listadas, larguras de 320 a 1280 px e CPU 4×.
