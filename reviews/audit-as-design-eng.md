# Design Engineering Audit: front-end do site (`comparador/web`), sem plano

**Perspective**: Design Engineer
**Date**: 2026-10-13
**Plan**: nenhum plano foi indicado. Auditei o estado atual de `main` (f151df8): `estilo.css`, `index.html`, `livro.html`, `manifest.json`, `icone.svg` e a marcação gerada por `app.js`, `livro.js` e `lista.js`.

## Plan Summary
Não há mudança visual proposta; esta é uma auditoria do que existe. O site é um app de página única, com fontes do sistema, tokens em variáveis CSS, tema claro e escuro pelo sistema, e estantes de capas. O desenho é coeso e bem acabado. Os problemas são poucos e concentrados em contraste, campos no iPhone e consistência da escala.

## Como foi feito (e o que não foi)
- O skill descreve oklch, `globals.css`, `html.dark` e Tailwind; este projeto usa **variáveis CSS em hexadecimal, um bloco `:root` e `@media (prefers-color-scheme: dark)`**, sem Tailwind. Julguei o código pelo sistema de tokens dele, não pelo do skill.
- **Medido**: contraste WCAG calculado a partir dos valores dos tokens, nos dois temas; contagem de tamanhos de fonte, raios e tokens sem uso no `estilo.css`.
- **Renderizado** (Chromium sem janela, com o `estilo.css` real e a marcação de uma linha da lista): foco de teclado na linha da lista e campos numéricos, em claro e em escuro. O escuro foi obtido forçando o bloco escuro como `:root`, porque o Chromium deste ambiente não aceitou forçar `prefers-color-scheme`.
- **Não feito**: não renderizei o app inteiro com dados, nem as páginas do livro e do início, nem os pontos de quebra de 520, 720 e 900 px. Não testei em iPhone: o zoom do iOS e as áreas seguras são comportamento conhecido do Safari, não reproduzido aqui. `app.js` (703 linhas) foi lido por busca de padrões, não linha a linha.

## Files Reviewed
| File | Visual Role | Risk |
|------|-------------|------|
| `comparador/web/estilo.css` | Tokens, componentes, temas claro e escuro, movimento | Médio |
| `comparador/web/index.html` | Estrutura do cabeçalho, busca, rodapé, `meta theme-color` | Baixo |
| `comparador/web/app.js` | Marcação das telas (início, busca, livro, lista), esqueletos, estados vazios e de erro | Médio |
| `comparador/web/livro.js` | Gráfico SVG, legenda, estatísticas | Baixo |
| `comparador/web/manifest.json`, `icone.svg` | Instalação e ícone | Médio |

## Verdict: APPROVE WITH CHANGES
Os tokens têm paridade completa entre os temas (os 29 tokens de cor e sombra são redefinidos no escuro), há esqueleto, estado vazio e estado de erro nas quatro telas de dados, o movimento usa só `transform` e `opacity` em 100–200 ms e existe regra para `prefers-reduced-motion`. O que impede de aprovar sem ressalvas é o texto em `--mu2`, que não atinge contraste em nenhum dos temas, e os campos de 14 px que o iPhone amplia.

## Critical Issues (Must Fix)
| # | Issue | File(s) | Impact | Fix |
|---|-------|---------|--------|-----|
| V1 | **Campos a 14 px no iPhone.** `.faixa-preco input` (preço de/até), `.alvo-f input` (preço-alvo) e `.sel select` (gênero, ordenar) têm `font-size:14px`. Só o campo de busca do cabeçalho tem 16 px. O cálculo de 14 px foi confirmado na renderização; o zoom em si é comportamento conhecido do Safari, não reproduzido. | `estilo.css:102,171,298` | O Safari do iPhone amplia a página ao focar um campo com menos de 16 px, e ela não volta sozinha. O público principal é de celular (manifesto "adicionar à tela inicial"). | `@media(max-width:719px){.faixa-preco input,.alvo-f input,.sel select{font-size:16px}}`. Não precisa mudar a altura. |
| V2 | **`--mu2` usado como cor de texto não atinge 4,5:1 em nenhum tema.** Claro: 2,70 sobre `--bg` e 2,94 sobre `--sf`. Escuro: 4,08 sobre `--bg` e 3,75 sobre `--sf`. É texto em: rótulos dos eixos do gráfico (`.graf text`, 11,5 px), linha pequena das estatísticas (`.stats small`, 12 px), contagem dos gêneros (`.gens span`, 12 px) e o placeholder da busca. | `estilo.css:49,196,249,275` | O número que dá sentido ao gráfico (as datas e os valores dos eixos) é o de menor contraste da página. | Nesses quatro seletores, usar `--mu` (5,48 a 5,98 no claro; 6,11 a 7,36 no escuro). Deixar `--mu2` só para pontos separadores, linhas e ícones. |

## Recommendations
| # | Issue | File(s) | Why | Fix |
|---|-------|---------|-----|-----|
| R1 | **O foco de teclado na lista não cerca o cartão.** Em `div.row`, o link esticado (`.esticar::after{inset:0}`) cobre o cartão para o clique e o hover tem tratamento (`div.row:has(.esticar:hover)`), mas o anel de foco aparece só ao redor do título. Confirmado na renderização, em claro e em escuro. | `estilo.css:146,157`; `app.js:544` | Quem navega por teclado vê um alvo menor do que o que o mouse enxerga. A "Minha lista" é uma das telas centrais. | `div.row:has(.esticar:focus-visible){outline:2px solid var(--ac);outline-offset:2px}` e `.row .esticar:focus-visible{outline:none}`, espelhando a regra do hover. |
| R2 | **Escala sem tokens.** São 27 tamanhos de fonte distintos (7, 9, 11, 11,5, 12, 12,5, 13, 13,5, 14, 15, 15,5, 16, 17, 18, 19, 20, 21, 22, 23, 25, 26, 27, 28, 30, 32, 34 e 40 px, com meios pixels) e 9 tamanhos de `h1` (22 a 34). Raios: `10px` aparece 5 vezes fora da escala `--r1` 8 / `--r2` 12, e `8px` aparece 5 vezes escrito à mão. | `estilo.css` | Cada tela nova escolhe um número novo, e a hierarquia do início, da busca, do livro e da lista não se compara. | Definir de 6 a 8 degraus (`--fs-*`) e 2 tamanhos de `h1` (computador e celular); trocar `10px` e `8px` por tokens de raio. |
| R3 | **Três tokens sem uso**: `--r1`, `--ac2` e `--acf` só aparecem na definição (e `--ac2`/`--acf` nos dois temas). | `estilo.css:4,5,12,19` | Dá a falsa impressão de que existe um tom de realce em hover e uma cor de texto sobre o realce. | Usar (`--r1` resolve parte de R2) ou apagar. |
| R4 | **Estados que faltam.** Sem hover: `.seg button` (seletor de período do gráfico), `.leg button` (legenda), `.sel select` e `.busca input`. Sem `:active`: `.chip`, `.ib`, enquanto `.btn` tem `scale(.98)`. Os hovers não estão atrás de `@media(hover:hover)`, então ficam "presos" depois de um toque no celular. | `estilo.css:81-103,144-146` | A mesma família de controles reage de jeitos diferentes. | Uma regra comum de hover para controles segmentados e legenda; envolver os hovers em `@media(hover:hover)`. |
| R5 | **Alvos de toque abaixo de 44 px**: `.ib` 40; `.chip`, `.btn.sm`, campos e selects 36; `.busca .limpa` 32; `.seg button` e `.leg button` 30. Todos passam o mínimo de 24 px do WCAG 2.2 AA, mas ficam abaixo dos 44 pt do iOS. | `estilo.css:52,84,87,91,98,102,264` | Os mais apertados são justamente os do gráfico (período e legenda), que se usa com o dedo. | Aumentar a área de toque com `::before` ou padding sem mexer no desenho (começar por `.seg button` e `.leg button`). |
| R6 | **Borda dos campos fraca.** `--ln2` sobre o fundo dá 1,36:1 no claro e 1,62:1 no escuro (limite do WCAG 1.4.11 para o contorno de um controle: 3:1). Na renderização escura, os campos vazios quase somem. | `estilo.css:48,102,171,298` | O contorno é o que mostra onde se digita. | Um token mais escuro só para controles (por exemplo `--ln3`, cerca de 3:1) e manter `--ln2` nas linhas decorativas. |
| R7 | **`viewport-fit=cover` sem `env(safe-area-inset-*)`.** Em iPhone com entalhe, na horizontal ou instalado, o cabeçalho e o aviso rápido (`.toast`, `bottom:24px`) podem ficar sob o entalhe ou o indicador inicial. Não testado em aparelho. | `index.html:4`; `estilo.css:42,313` | Corte de conteúdo justamente na instalação. | Tirar `viewport-fit=cover` ou somar os insets em `.hdr-in`, `.pg` e `.toast`. |
| R8 | **Ícone de instalação só em SVG.** `apple-touch-icon` aponta para `icone.svg` (o iOS usa PNG para esse fim; conhecimento geral, não testado) e o manifesto só lista o SVG. O `theme_color` do manifesto (`#1a1916`) difere do `theme-color` do HTML (`#f6f5f1`/`#131210`). | `index.html:9-10`; `manifest.json` | A tela inicial do aparelho pode ficar com uma miniatura em vez do ícone. | PNGs de 180, 192 e 512 px (mais um maskable) e alinhar a cor do tema. |

## Nice-to-Haves
| # | Suggestion | Rationale |
|---|------------|-----------|
| N1 | `@media (forced-colors: active)` com contorno nos estados `aria-pressed` e `aria-current` | `.chip`, `.seg`, `.btn.pri` e `.badge` dependem só da cor de fundo, que o modo de alto contraste do Windows remove. |
| N2 | Manter um indicador mínimo em `prefers-reduced-motion` | `*{animation:none!important}` congela o `.giro`, que vira um anel parado; o texto "Buscando…" continua, mas o brilho do esqueleto também some. |
| N3 | Remover as regras sem uso: `.btn.salvar svg{transition:transform .2s}` e `.seg button:disabled` | Nenhuma regra muda o `transform` desse ícone (só o preenchimento muda), e nenhum arquivo `.js` define `disabled` em nenhum elemento. |
| N4 | Capas de substituição: texto de 9 px (7 px em `.cv.p`) | É ilegível nessa largura; basta a inicial ou nada, já que está `aria-hidden`. O branco sobre o gradiente chega a 3,65:1 no pior matiz. |
| N5 | Trocar os `style=` estáticos dos modelos em JS por classes | Margens e tamanhos fixos em 8 pontos de `app.js` e `livro.js` (por exemplo `style="margin:4px 0 0"`, `style="font-size:17px"`; o `h2` com `font-size:19px` em `livro.js:161` repete `.graf-h h2`). Os `style=` de largura do esqueleto estão certos. |

## Design System Compliance
- **Cores**: tudo vem de variáveis, com duas exceções pequenas e justificáveis: `#fff` e `rgba(255,255,255,.55)` do texto das capas de substituição, e `rgba(0,0,0,.18)` da sombra do selo. `icone.svg` e o `manifest.json` têm hexadecimal, o que não tem como evitar.
- **Tema**: o escuro segue o sistema (`color-scheme: light dark`), sem alternador manual. É uma escolha coerente com um site sem conta; vale só registrá-la.
- **Paridade claro/escuro**: completa. O que enfraquece no escuro é a borda dos campos (R6) e o `--mu2` (V2).
- **Fragmentação**: a escala tipográfica e os raios (R2) e os tokens sem uso (R3) são o que mais se afasta de um sistema.
- **Espaçamento**: não há tokens de espaçamento, e os valores variam de 2 em 2 px (4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24…). Não contei, e não é a primeira prioridade.

## Visual State Coverage
"n/a" = o estado não existe para o elemento. "✗" = existe e não tem tratamento.

| Component/Element | Hover | Focus | Active | Disabled | Loading | Empty | Error | Dark Mode |
|-------------------|-------|-------|--------|----------|---------|-------|-------|-----------|
| `.btn` | ✓ | ✓ (global) | ✓ | n/a (nenhum botão é desabilitado) | n/a | n/a | n/a | ✓ |
| `.chip` (filtros) | ✓ | ✓ | ✗ | n/a | n/a | n/a | n/a | ✓ |
| `.seg button` (período) | ✗ | ✓ | ✗ | n/a (estilo existe, nada o usa) | n/a | n/a | n/a | ✓ |
| `.leg button` (legenda) | ✗ | ✓ | ✗ | n/a | n/a | n/a | n/a | ✓ |
| Campos (busca, preço, `select`) | ✗ | ✓ | n/a | n/a | n/a | n/a | ✗ (sem `:invalid`) | ✓ (borda fraca, R6) |
| `.ib` (botão de ícone) | ✓ | ✓ | ✗ | n/a | n/a | n/a | n/a | ✓ |
| Linha da lista (`div.row`) | ✓ | ✗ (só no título, R1) | n/a | n/a | ✓ | ✓ | ✓ | ✓ |
| Linha da busca (`a.row`) | ✓ | ✓ | n/a | n/a | ✓ | ✓ | ✓ | ✓ |
| Cartão da estante (`.cartao`) | ✓ (só o título sublinha) | ✓ | n/a | n/a | ✓ (linhas de esqueleto) | n/a | n/a | ✓ |
| Telas de dados (início, busca, livro, lista) | n/a | n/a | n/a | n/a | ✓ esqueleto | ✓ `.vazio` | ✓ `erro()` | ✓ |

## Verdict Details
- Design Token Fidelity: CONCERNS (escala de fonte e raios sem tokens; 3 tokens sem uso; `--mu2` usado onde o texto precisa de mais contraste)
- Visual State Coverage: CONCERNS (foco da lista; hover e `:active` desiguais entre controles)
- Dark Mode Parity: PASS (todos os tokens redefinidos e renderizado sem quebras; ressalvas em V2 e R6)
- Animation Quality: PASS (só `transform` e `opacity`, 100–200 ms, regra de `prefers-reduced-motion`; ver N2 e N3)
- Visual Consistency: CONCERNS (27 tamanhos de fonte, 9 de `h1`, `10px` fora da escala de raios)

## Atualização: o que foi corrigido (PRs #31 e seguintes)

- **V1 e V2** foram corrigidos no PR #31.
- **Sobre o V1:** a correção usou `font-size: 16px` **sem** a media query de 719 px sugerida na tabela, como o campo de busca já fazia. Uma media query por largura deixaria de fora o iPhone na horizontal e o iPad.
- **Efeito colateral não previsto no relatório:** com 16 px, os rótulos padrão dos seletores (`Todos os gêneros`, `Adicionados por último`) deixaram de caber lado a lado em celular. O PR #31 faz a linha quebrar quando não cabe.
