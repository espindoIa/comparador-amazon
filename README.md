# Preços de livros

Guarda o histórico de preço dos livros mais vendidos da Amazon.com.br. Serve para conferir ofertas
como as da Black Friday: um desconto só quer dizer alguma coisa comparado com o que o livro custou
nos meses anteriores, e a Amazon não mostra isso.

São duas partes:

- um coletor, que lê todo dia as páginas de mais vendidos de cada categoria de livros e anota o
  preço de cada formato (capa comum, capa dura, Kindle, audiolivro);
- um site estático, que mostra quanto cada livro custa hoje e quanto já custou.

Tudo roda no GitHub: o coletor no Actions, o banco nos arquivos de uma release e o site no Pages.
Não há servidor.

## O site

- Busca por título, autor, ISBN ou link da Amazon. Acentos, pontuação e a ordem das palavras não
  importam, e erros de digitação são corrigidos quando nada é encontrado.
- Filtros por formato, idioma, gênero e faixa de preço.
- Página de cada livro:
  - gráfico do preço;
  - preço mais comum dos últimos 90 dias, menor e maior preço;
  - comparação nas datas de promoção;
  - outros formatos, outras edições e outros livros do mesmo autor.
- Página inicial: livros que baixaram de preço, livros no menor preço já registrado e lista de gêneros.
- Minha lista, guardada só no navegador (não há conta):
  - mostra o que mudou desde a última visita;
  - aceita um preço-alvo por livro;
  - pode ir para outro aparelho por um link.

O site mostra números, não recomendações: não diz se um preço é bom.

## Rodar na sua máquina

```bash
pip install -r requirements.txt          # o Playwright usa o Chrome ou o Edge que você já tem
python -m comparador --db data/vendidos.db varrer --vendidos --minutos 20
python -m comparador --db data/vendidos.db catalogo --vendidos
python -m comparador site data/vendidos.db --saida site
cd site && python -m http.server 8000    # http://localhost:8000
```

Sem Chrome nem Edge: `python -m playwright install chromium`, ou aponte `COMPARADOR_NAVEGADOR`
para o executável de outro navegador.

Testes:

```bash
python -m unittest discover -s tests     # inclui os testes de JavaScript e os do navegador
node tests/busca.test.js                 # só a busca
```

## Como a coleta funciona

A Amazon só mostra 75 páginas (1.200 livros) de cada lista de mais vendidos, mas cada faixa de
preço tem a própria lista. Por isso cada uma das 30 categorias (o ranking geral e 29 gêneros) é
lida em 9 faixas de preço, até juntar 1.000 livros com preço em cada faixa. Isso cobre com folga os
~2.000 mais vendidos de cada categoria. São cerca de 12 mil páginas por dia.

Algumas decisões que vieram de medir as páginas reais:

- Um navegador de verdade, sem janela, abre a primeira página e busca as outras de dentro dela.
  Com `requests`, a Amazon respondia com captcha ou erro 503.
- Cada card pode ter vários formatos. O preço é lido de dentro do link de cada formato, e assim
  parcelas e "outras ofertas" não se misturam com ele. Kindle Unlimited (R$ 0,00) é descartado.
- Só entram ofertas vendidas pela própria Amazon (filtro "Vendido por" da busca). O filtro vale
  para o card, então um formato secundário pode vir de outro vendedor. Medimos isso em cerca de
  1,5% dos itens.
- O ritmo começa em 21 páginas por minuto e sobe aos poucos até 60. Quando a Amazon bloqueia ou
  devolve uma página com poucos resultados, ele cai. Não há rodízio de IP, disfarce de navegador
  nem resolução de captcha.
- Uma página com resultado ralo, mesmo com HTTP 200, conta como falha e é lida de novo.
- O histórico guarda intervalos ("R$ 39,90 de 2 a 15 de outubro"). Ele só cresce quando o preço muda.

Cada card também traz nota, número de avaliações, autor, capa, data e idioma. As avaliações
ordenam a busca e decidem quais livros vêm primeiro no índice do site.

## Agendamento e cópias

`varredura.yml` roda às 00:41, 06:41, 12:41 e 18:41 (horário de Brasília). Cada execução continua de
onde a anterior parou, e o dia costuma fechar nas três primeiras.

O banco fica na release `catalogo`, como `catalogo-vendidos-<data>.db.gz`. Antes de publicar uma
cópia nova, `scripts/verificar_banco.py` confere duas coisas: que o banco está íntegro e que nenhuma
tabela encolheu. Ficam as 14 cópias mais recentes e a última de cada um dos 30 dias anteriores.

Avisos por e-mail (falha do workflow):

- o dia anterior ficou incompleto;
- os cards pararam de trazer capa e autor, o que costuma indicar que a Amazon mudou o layout.

`site.yml` gera o site depois de cada coleta. Ele se recusa a publicar se o site novo tiver menos de
70% dos livros do site no ar. Para publicar mesmo assim, rode-o à mão com a opção `forcar`.

Para ativar o site, uma vez só: *Settings → Pages → Source: GitHub Actions*.

## Arquivos do site

`python -m comparador site` gera:

- `dados/indice-N.json`: o índice da busca, em partes, das obras mais avaliadas para as menos. A
  primeira parte (~15 mil obras, ~0,7 MB compactado) chega rápido. As outras chegam enquanto a
  pessoa já está buscando.
- `dados/destaques.json`: o que a página inicial mostra, para ela não esperar o índice.
- `dados/h/XX.json`: o histórico de cada livro, em 256 arquivos.
- `meta.json` e `eventos.json`: o resumo da coleta e as datas de promoção, que vêm de `eventos.csv`.

O formato de cada arquivo está descrito no começo de `comparador/site.py`.

A busca fica em `comparador/web/busca.js`, os cálculos e o gráfico em `comparador/web/livro.js` e a
lista em `comparador/web/lista.js`. Os três têm testes que rodam no Node.

## Outros comandos

```bash
python -m comparador --db data/vendidos.db grafico "título ou ASIN"   # página avulsa com o histórico
python scripts/simular_precos.py data/vendidos.db data/simulado.db    # preços inventados até a Black Friday
```

O banco simulado parte de livros reais e inventa preços diários com três cenários de Black Friday:
desconto real, desconto falso (o preço sobe antes) e nenhum desconto. Ele serve para testar o site
antes da data e leva um aviso em todas as páginas.

## Limites

- Só livros que aparecem nas listas de mais vendidos. Um livro que sai da lista para de receber
  preço novo, e some da busca depois de 14 dias.
- O preço de capa só aparece quando há desconto.
- Ler as páginas da Amazon por programa vai contra os termos de uso dela. A coleta espaça as
  requisições, desacelera ou para quando é bloqueada, e não tenta contornar bloqueios.
- O GitHub Actions é feito para o software do próprio repositório, e horas diárias de coleta
  podem ser vistas como uso indevido. O mesmo comando roda em qualquer máquina com `cron`.
- `data/` não vai para o git.
