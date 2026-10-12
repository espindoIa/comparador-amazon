# Roadmap do app

O objetivo é um app com cara e comportamento de produto profissional, que continue simples: site
estático, JavaScript sem build, dados gerados pelo Python. Cada item abaixo existe porque resolve
uma tarefa que a pessoa faz de verdade:

1. **Achar um livro** e saber, de relance, se é o livro certo (capa, autor, ano, formato).
2. **Entender o preço**: quanto custa agora, quanto costuma custar, como variou.
3. **Acompanhar uma lista** até a hora de comprar (Black Friday, por exemplo).
4. **Ir para a Amazon** comprar.

O app dá números, não conselhos: quem decide se o preço é bom é a pessoa.

## Fase 0: fundação

- **Testes automáticos em todo PR** (Python, JavaScript e navegador). Hoje os testes só rodam na
  máquina de quem desenvolve.
- **Índice agrupado por obra.** Capa comum, capa dura e Kindle do mesmo livro viram um item só,
  com o preço de cada formato. O título, o autor e a capa não se repetem, o que deixa o arquivo menor.
- **Números calculados na geração do site.** O "preço mais comum" (mediana de 90 dias) só aparece
  com pelo menos 14 dias de coleta, e o mesmo vale para o "Baixaram de preço" do início. Assim o
  app não mostra estatística com 2 dias de dados.
- **Itens que não são livro ficam de fora da busca:** brinquedo, agenda, material de escritório,
  CD, mapa, baralho.
- **Cache-busting.** Depois de cada publicação, o navegador baixa o JavaScript e o CSS novos.

## Fase 1: sistema visual e estrutura do app

- **Tokens de cor, tipo e espaçamento**, com modo escuro automático e números tabulares nos preços.
- **Ícones SVG próprios**, no lugar de ☆★↗◀▶.
- **Logo e favicon**, e manifesto para "Adicionar à tela inicial".
- **Uma página só**, com endereços de verdade, para que voltar seja instantâneo e a busca continue
  onde estava:
  - `?q=` para a busca
  - `?livro=ASIN` para o livro
  - `?lista` para a lista
  - `?sobre` para a página Como funciona

  Os links antigos `livro.html?asin=` continuam funcionando.
- **Cabeçalho fixo** com a busca sempre à mão e o atalho para Minha lista com contador.
- **Estados de carregando (esqueleto), vazio e erro**, este com o botão "Tentar de novo".

## Fase 2: livros fáceis de identificar

- Cada resultado mostra:
  - a capa (ou uma capa gerada, quando a Amazon não tem)
  - o título limpo
  - o autor e o ano
  - etiquetas de idioma e de volume
  - os formatos com o preço de cada um
- **Filtros sempre visíveis:** Livro físico, Kindle e Audiolivro, mais o idioma. Ordenação e faixa
  de preço ficam num painel.

## Fase 3: página do livro

- **Topo:**
  - a capa, o título, o autor e o ano
  - a escolha de formato
  - o preço em destaque e o preço de capa
  - os botões "Ver na Amazon" (principal) e "Salvar"
- **Gráfico desenhado no tamanho real da tela**, com área preenchida, dica flutuante no toque e
  períodos de 30 dias, 90 dias e Tudo. Saem os controles pouco usados: zoom, setas, "cada coleta"
  e "dias sem coleta".
- **Números em grade:**
  - preço mais comum
  - mais barato
  - mais caro
  - acompanhado desde
- **Datas de promoção:** só as que têm dados, mais um aviso da próxima.
- **Outras edições** do mesmo título e autor.

## Fase 4: Minha lista como painel

- Cada livro mostra a capa, o preço, a diferença para o preço mais comum e um minigráfico.
- **"Desde sua última visita":** o que ficou mais barato ou mais caro.
- **Ordenação:** adicionados, menor preço, maior queda.
- **Compartilhar por link,** que também serve para levar a lista a outro aparelho. Substitui a
  caixa de texto.

## Fase 5: início útil

- Prévia da lista.
- **Baixaram de preço:** o que ficou mais barato na última coleta.
- **Próxima data de promoção,** com contagem de dias.
- **Página "Como funciona",** com a origem dos dados, a frequência da coleta e o que significa cada número.

## O que fica de fora, de propósito

- Conta, login ou servidor (a lista fica no aparelho, e o link leva para outro).
- Alerta de preço por e-mail ou push (exigiria servidor).
- Avaliações, recomendações e recursos sociais.
- Comparação com outras lojas, editora e link de afiliado.
- Modo offline (service worker): dá trabalho e quase ninguém usaria.

## Quando os dados chegam

O histórico começou em 11/10/2026. Os metadados (capa, autor, ano, idioma e obra) chegam na coleta
das 03:41 UTC de 13/10. Até lá o app usa a capa gerada e mostra um item por formato. Os números que
dependem de histórico aparecem sozinhos quando há dias suficientes: com 14 dias, o preço mais comum;
na Black Friday (27/11), cerca de 46 dias de dados.
