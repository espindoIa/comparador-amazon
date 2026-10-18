# Preços de livros: design system (MASTER)

Fonte da verdade do visual do site (`comparador/web`). Uma página com regras próprias tem um arquivo em `pages/`, que vale por cima deste.
Os valores moram em `comparador/web/estilo.css` (`:root` e o bloco `prefers-color-scheme: dark`). Se este texto e o CSS discordarem, vale o CSS: corrija o texto.
`tests/test_site.py::TestFolhaDeEstilo` trava as regras marcadas com 🔒.

## Camada em vigor: `referencia.css`
O visual publicado é o **escuro e dourado** escolhido pelo dono (2026-10-16), e vem de `comparador/web/referencia.css`, carregado depois de `estilo.css`. Onde as duas folhas discordam, vale `referencia.css`; as seções abaixo descrevem a base (`estilo.css`) e o que a camada não troca (componentes, foco, movimento, regras de acessibilidade).
- **Tema:** o `<head>` do `index.html` aplica `data-theme` antes de a página pintar: o tema salvo pelo botão e, sem ele, o do sistema. O botão `#tema` tem `aria-pressed` (ligado = escuro), e a cor da barra do navegador e o manifesto são escuros.
- **Tokens:** `referencia.css` redefine **todos** os tokens de cor nos dois temas (`:root` e `:root[data-theme=light]`); o que ela não redefinir volta a seguir o sistema. `--ln3` é `#5f6d78` (escuro) e `#7f8487` (claro); `--ac` claro é `#7d5a1c`.
- **Fontes:** Georgia (títulos e livros) e Arial (interface); as `woff2` de `estilo.css` não são usadas por essa camada.
- **Ícones:** SVG de traço em linha, com `currentColor` (nada de `<img>` com cor fixa, que não segue o tema nem o alto contraste).
- **Dicas (`.hint`):** só nos ícones sem texto; aparecem com o mouse (`@media(hover:hover)`) ou com o foco do teclado, têm uma ponte invisível até a bolha (alcançável com o ponteiro) e fecham com Esc.
- 🔒 `TestFolhaDeReferencia`: todo token de cor nos dois temas, contraste dos pares de texto e de `--ln3`, sem `px` fora da escala `--fs-*` e dos raios `--r*`, sem `z-index` solto, hover só em `@media(hover:hover)`.

## Direção
**Livraria**: papel creme, marrom de capa de couro e âmbar nos botões. O site é uma ferramenta de consulta de preços, não uma landing page. A tela mostra números, e a decisão fica com quem lê.

Origem: a saída `--design-system` da skill `ui-ux-pro-max` para "book price tracker" (2026-10-13). Ficou de fora o que não serve:
- O padrão "Hero + Testimonials + CTA", que é de landing page.
- O `@import` do Google Fonts, porque as fontes ficam no próprio site.
- O âmbar `#D97706` com texto branco, que dá 3,2:1. Os botões usam `#B45309`, que dá 5,0:1.

## Cores (tokens)
Os nomes são os mesmos nos dois temas. Contraste medido pela fórmula WCAG 🔒 (≥ 4,5:1 para texto, ≥ 3:1 para contorno de campo).

| Token | Papel | Claro | Escuro |
|---|---|---|---|
| `--bg` | fundo da página (papel) | `#faf5ea` | `#17130f` |
| `--sf` | cartões, campos | `#fffdf8` | `#211b16` |
| `--sf2` / `--sf3` | fundo de controle, hover, ativo | `#f3ecdd` / `#eae0cc` | `#2b241d` / `#362d25` |
| `--fg` | texto | `#1c1917` (16,1:1 no bg) | `#f2ebdd` (15,6:1) |
| `--mu` | texto secundário | `#5c5249` (7,0:1) | `#bfb2a0` (8,9:1) |
| `--mu2` | só separadores e ícones, **nunca texto** | `#9a8e80` | `#85796a` |
| `--ln` / `--ln2` | linhas decorativas, réguas | `#e9e0cf` / `#d9cdb6` | `#2e271f` / `#40362c` |
| `--ln3` | contorno de campo 🔒 | `#8c7f6c` (3,9:1 no sf) | `#85796a` (4,0:1) |
| `--ac` / `--acs` | marrom de capa: links, linha do gráfico, chip ligado, contador | `#92400e` (6,5:1) / `#f6e7d4` | `#f0b26b` (9,9:1) / `#3a2715` |
| `--pri` / `--prif` | botão principal (âmbar) e o texto sobre ele | `#b45309` / `#fff` (5,0:1) | `#e8a04a` / `#1c1209` (8,4:1) |
| `--tinta` / `--tintaf` | superfícies escuras: aviso rápido, dica do gráfico, link de pular | `#1c1917` / `#fffdf8` | invertido |
| `--dn` / `--dns` | preço caiu, "abaixo do comum" | `#146c43` / `#e1f0e5` | `#6fd3a0` / `#15291d` |
| `--up` / `--ups` | preço subiu; erro de campo | `#a8321c` / `#f8e3dc` | `#ff9b85` / `#3d1d16` |
| `--wr` / `--wrs` | aviso de dado velho ("sem coleta recente") | `#3f5a86` / `#e4eaf4` | `#9db7e8` / `#1c2638` |
| `--med` | linha do preço mais comum | `#2f6b7a` | `#6fc3d2` |
| `--capa` | linha do preço de capa | `#9a8e80` | `#85796a` |
| `--ev` / `--evl` | faixa e nome das datas de promoção | âmbar translúcido / `#92400e` (7,0:1 no sf) | âmbar translúcido / `#f0b26b` (9,2:1) |
| `--grao` | opacidade do grão de papel | .05 | .07 |
| `--filete` | filete dourado da capa gerada (decorativo) | âmbar translúcido | âmbar translúcido |

- `--wr` e `--med` ficam em tons frios de propósito: em âmbar ou laranja se confundiriam com a marca.
- Verde e vermelho nunca aparecem sozinhos. Vêm sempre com texto ("12% abaixo do comum") ou seta (▼ ▲).

## Tipografia
| Papel | Token | Fonte | Onde |
|---|---|---|---|
| Títulos grandes | `--display` | Cormorant Garamond 600 | `h1`, `h2`, marca. **Só a partir de 20 px**: a fonte é fina e tem olho pequeno |
| Livro e leitura | `--serif` | Crimson Pro 400 / 400 itálico / 600 | título de livro (cartão, linha), autor (itálico), texto da página "Como funciona", gêneros, rodapé |
| Interface e números | `--f` | fonte do sistema | controles, preços, pílulas, estatísticas, eixos do gráfico. Números com `tabular-nums` |

- As fontes ficam em `comparador/web/*.woff2` (subconjunto latino, que cobre ã, ç, é), com `font-display:swap` 🔒 e licença em `OFL.txt`.
- Só a Cormorant tem `preload` (`crossorigin`).
- `h1,h2` têm `font-synthesis:none`, para o navegador não inventar negrito na Cormorant, que só tem 600. A face 600 da Crimson declara `font-weight:600 700`, então o negrito dela também usa o arquivo real.
- O `body` continua com `--f`. Controles (`font:inherit`) não herdam serifa.
- A página avulsa do comando `grafico` embute o CSS sem as fontes e cai na pilha de serifas do sistema.
- Escala 🔒: `--fs-1` 12 … `--fs-12` 40 px (12 degraus, só cresce). Não existe `font-size` em px fora dela, a não ser no título da capa gerada (9 px, proporcional à capa).
  - `h1` da tela: `--fs-12` no início e em "Como funciona", `--fs-11` no livro, `--fs-10` na lista e na busca.
  - No celular o `h1` desce 1 a 3 degraus.
  - `h2` de seção: `--fs-8`. Exceção: o `h2` pequeno do cartão de promoção (`.prox`, 16 px) usa `--f`, porque a Cormorant não serve abaixo de 20 px.
  - Toda tela tem um `h1`, que nomeia a tela e recebe o foco (no livro, a região `.livro` nomeada por ele): na busca por texto ele é só para leitor de tela (`.vh`, "Busca: …"); erro, não encontrado e lista vazia usam `h1` no bloco `.vazio`.

## Forma
- Raios 🔒: `--r0` 4 (capa), `--r1` 8 (controle pequeno), `--r2` 12 (botão, aviso), `--r3` 16 (cartão); `999px` para pílula e chip.
- **Réguas de livraria:**
  - cabeçalho e rodapé com `3px double var(--ln2)`;
  - cabeçalho de seção (`.sec-h`) com régua de 1 px embaixo.
- **Lombada:** filete de 4 px à esquerda. Gêneros em `--ac`, cartão de promoção em `--pri`.
- **Capa gerada** (sem imagem): pano de encadernação, com o matiz escolhido entre couro, vinho, verde, azul, ocre e ameixa (`PANOS` em `app.js`), e filete dourado.
  - Na capa pequena da lista vai só a inicial.
- **Um acento só:** marrom e âmbar. As datas de promoção usam o âmbar translúcido, sem cor nova. Verde e vermelho são semânticos (caiu/subiu), não acento; `--med` e `--wr`, frios, existem para não se confundir com a marca.
- **Grão de papel:** `body::before` fixo (cobre a janela) com ruído SVG (`feTurbulence`) na opacidade `--grao`, atrás do conteúdo (`--zpapel`), sem clique; some no alto contraste e na impressão.
- **Sombras quentes** (`--sh1`, `--sh2`, `--shc`) só no que flutua ou responde: hover de linha e de gênero, dica do gráfico, aviso rápido, capas, segmento ligado. Cartão em repouso (`.card`, `.row`, `.ferr`) tem só borda `--ln`.
- **Camadas:** `--zpapel` −1, `--zacima` 1, `--ztip` 2, `--zhdr` 20, `--ztoast` 50, `--zpular` 60. Não existe `z-index` solto 🔒.
- **Quebra de linha:** `h1,h2,h3` com `text-wrap:balance`; `p,dd,li` com `text-wrap:pretty`; parágrafo de abertura até 60ch.
- **Rolagem:** suave só sem movimento reduzido; restaurar a posição (voltar) e trocar de filtro na busca são instantâneos.
- Espaçamento: passos de 2 px, sem token. Lacunas comuns: 8, 12, 14, 16, 18, 24.

## Componentes e estados
| Peça | Classe | Estados |
|---|---|---|
| Botão | `.btn` (+ `.pri` âmbar, `.sm`, `.gh`, `.ico`) | hover (`@media(hover:hover)` 🔒), `:active` scale .98, `aria-pressed`, foco |
| Chip de filtro | `.chip` | contorno `--ln3` (3:1, como os campos), escurece para `--mu` no hover; ligado = fundo `--ac` com texto `--sf`; `:active` |
| Seletor de período | `.seg button` | ligado = fundo `--sf` com sombra |
| Pílula de preço | `.pill` `.dn` `.up` `.wr` | só leitura |
| Campo e select | `.busca input`, `.sel select`, `.faixa-preco input`, `.alvo-f input` | contorno `--ln3` 🔒, 16 px (o iPhone não amplia), hover escurece a borda 🔒, erro com `aria-invalid` (borda `--up`) e `.erro-campo` embaixo |
| Livro em lista | `.row` (busca, lista) e `.cartao` (estantes) | hover; foco cerca a linha inteira 🔒 |
| Motivo no cartão | `.cartao .por` ("como <cite>Título</cite>") | só nos Parecidos do início, e só com 2 livros de partida ou mais; aí em todos os cartões da estante, para as alturas ficarem iguais. Uma linha, `--fs-2`, `--mu`, o título em `cite` (Crimson itálico). Não reaproveita o selo verde da capa, que é "preço caiu" |
| Nota no cabeçalho da seção | `.sec-h .nota` | só nos Parecidos da página do livro, e só se o livro tem subgêneros: até 3 nomes separados por " · ", à direita da régua. Uma linha, `--fs-3`, `--mu`, `text-overflow: ellipsis` (não é link: não pega o estilo de `.sec-h a`) |
| Carregando | `esqueleto(n)` / `.sk` | sem brilho com movimento reduzido |
| Vazio e erro | `.vazio` (medalhão `--acs`/`--ac`), `erro(msg)` | sempre com ação |
| Página 404 | `404.html` (GitHub Pages) | bloco `.vazio` com `h1` e "Ir para o início"; `<base>` calculada para funcionar em qualquer profundidade de endereço |
| Prévia dos links | meta `og:*` no `index.html` | título e descrição sempre; `og:image` (o ícone de 512 px) só com endereço completo, que a publicação passa em `python -m comparador site --url`; sem `og:url`, porque as telas são o mesmo `index.html` com `?livro=`/`?lista=` e um canônico único mandaria o link compartilhado para o início |
| Aviso rápido | `#toast` | 5 s; 10 s com ação; pausa com ponteiro ou foco; Esc fecha |

## Acessibilidade (obrigatório)
- **Foco e navegação**
  - Foco visível: `:focus-visible` com 2 px de `--ac`.
  - O título (`h1`/`h2` com `tabindex=-1`) ou a região que recebe foco por programa não mostra anel: não é um controle.
  - Link "Pular para o conteúdo" no começo.
  - Toda troca de tela leva o foco ao título dela (o `h1`, ou um alvo marcado com `data-foco`), menos enquanto se digita na busca.
  - O controle recriado por `innerHTML` (chip, select, botão do preço-alvo) recebe o foco de volta. O que some recebe um substituto: ao remover um livro da lista, o foco vai ao remover da linha vizinha; em "Ver todos", ao primeiro livro que apareceu; em "Mostrar mais" (último), ao primeiro livro novo.
  - O aviso rápido fechado tira o botão da ordem do Tab.
  - O aviso com "Desfazer" fica no fim da página: Ctrl+Z (⌘Z no Mac) desfaz enquanto ele está aberto (fora de campos de texto). O atalho aparece no aviso onde há teclado, e o leitor de tela ouve a dica. Fechado, o botão fica `inert`.
  - No livro, o foco da troca de tela vai à região `.livro` (nomeada pelo `h1`), que vem antes das ações no DOM; o Tab seguinte chega em "Ver na Amazon".
  - O erro de campo é `role="alert"`, ligado ao campo por `aria-describedby`, com ids únicos por livro.
- **Leitor de tela:** a contagem da busca é anunciada numa região viva escondida (`#cont-res`), com espera de 0,8 s.
- **Alvos de toque:** ≥ 40 px em tela de toque (`pointer:coarse`); campos e botões ao lado deles, 44 px 🔒.
- **Alto contraste:** `forced-colors` dá contorno aos estados ligados e ao botão principal.
- **Movimento:** `prefers-reduced-motion` tira transições e o brilho do esqueleto; o anel de "buscando" gira devagar.
- **Teclado no gráfico:** ver `pages/livro.md`.

## Antipadrões
- Texto em `--mu2`; borda de campo em `--ln2`.
- Cormorant em texto pequeno; serifa em controle ou em preço.
- Cor como único sinal (preço caiu/subiu, série do gráfico).
- `style="..."` nos modelos em JS, a não ser o tamanho e a posição das peças do esqueleto (`width`, `height`, `margin-top`) e o `--h` da capa gerada 🔒; hover fora de `@media(hover:hover)` 🔒.
- Emoji como ícone: os ícones são SVG de traço (`IC` em `app.js`).
- Fontes externas (Google), carrossel, depoimentos, CTA de landing page.
