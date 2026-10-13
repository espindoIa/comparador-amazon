# Página do livro: regras que valem por cima do MASTER

## Estrutura
- **No computador** (≥ 900 px), à esquerda e fixa ao rolar:
  - a capa;
  - "Ver na Amazon" (`.btn.pri`, âmbar);
  - "Salvar" (`aria-pressed`);
  - "Compartilhar".
- À direita ficam:
  - título (`h1`, Cormorant);
  - autor (Crimson itálico, link para a busca);
  - detalhes (nota com estrela âmbar, data, idioma, ASIN) e gêneros;
  - formatos (`.fmt`, `aria-current`);
  - preço grande (`--fs-12`, fonte do sistema), com as comparações em pílulas;
  - o cartão do gráfico e as estatísticas;
  - datas de promoção e estantes ("Outras edições", "Mais de …").
- **No celular**: a capa (108 px) fica ao lado do título e o resto vem embaixo, com a mesma marcação.

## Gráfico (`livro.js`, `grafico`)
- Série por estilo de linha, não só por cor:
  - preço: linha cheia `--ac` com área;
  - preço mais comum: tracejada `--med`, que é fria e não se confunde com o marrom;
  - preço de capa: pontilhada `--capa`.
  - A legenda repete o traço de cada uma.
- Datas de promoção: faixa `--ev` (âmbar translúcido) com o nome escrito em `--evl`, e o ponto do menor preço na promoção com contorno `--evl`. Mesmo tom da marca: o que distingue a promoção é a faixa e o nome, não uma cor nova.
- **Teclado:**
  - a área do gráfico entra no Tab (`tabindex=0`, `role=group`, rótulo com instruções);
  - ← → (e ↑ ↓) andam de um dia observado para o outro, Home e End vão às pontas, Esc esconde;
  - a dica aparece no ponto, e o valor é anunciado numa região `aria-live` ("R$ 34,99 em 12 out 2026").
- **Resumo em texto:** o `aria-label` do SVG diz o período, o menor, o maior e o último preço, e muda com o período escolhido.
- O seletor de período (`.seg`) e a legenda (`.leg`) são botões com `aria-pressed`. "Preço" é fixo, um `span`, não um botão.
- Estatísticas abaixo do gráfico: grade de 4, que vira 2 em telas de até 599 px. Rótulo em `--mu` e número em `tabular-nums`.
