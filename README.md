# Preços de livros

Guarda o histórico de preço dos livros mais vendidos da Amazon.com.br. Serve para conferir ofertas
como as da Black Friday: um desconto só quer dizer alguma coisa comparado com o que o livro custou
nos meses anteriores, e a Amazon não mostra isso.

São duas partes:

- um coletor, que lê as páginas de mais vendidos de cada gênero de livros duas vezes por dia (de manhã, para a
  base poder ficar pronta antes das 8h, e depois das 18h, horário de Brasília) e anota o preço de cada formato
  (capa comum, capa dura, Kindle, audiolivro);
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
python -m comparador varrer --dry-run    # confere as opções e mostra o plano, sem pedir nada à Amazon
python -m comparador varrer --minutos 20 # os mais vendidos de cada gênero, em data/vendidos.db
python -m comparador catalogo            # progresso de hoje e frescor
python -m comparador site data/vendidos.db --saida site
cd site && python -m http.server 8000    # http://localhost:8000
```

O banco padrão é `data/vendidos.db`, e `--db` vale antes ou depois do comando. Sem opções, `varrer` e `catalogo` tratam os
mais vendidos dos gêneros (`--vendidos`, que continua aceito, é o padrão); `--no NÓ` lê uma categoria só, por exemplo
`--no 7842710011 --db data/catalogo.db` para as HQs e o banco antigo. `catalogo --json` escreve o resultado em JSON.
`catalogo`, `grafico` e `site` só leem: com um banco que não existe, param dizendo qual. O HTML bruto das páginas com
problema vai para a pasta `html/` ao lado do banco (`--pasta-html` muda).

Sem Chrome nem Edge: `python -m playwright install chromium`, ou aponte `COMPARADOR_NAVEGADOR`
para o executável de outro navegador.

O `varrer` lê só pelo navegador (`--cliente auto`): se ele não abrir, para e diz por quê, em vez de cair em outro
cliente. `--cliente curl` e `--cliente requests` existem, mas a Amazon costuma bloqueá-los, e um bloqueio grava no
banco uma pausa de horas.

`varrer --dry-run` confere as opções e mostra o plano (ritmo, ciclo, pausa, fatias, cliente) sem abrir o
navegador, sem pedir nada à Amazon e sem gravar no banco.

Testes:

```bash
python -m unittest discover -s tests     # inclui os testes de JavaScript e os do navegador
node tests/busca.test.js                 # só a busca
```

## Como a coleta funciona

A Amazon só mostra 75 páginas (1.200 livros) de cada lista de mais vendidos, mas cada faixa de
preço tem a própria lista. Por isso cada um dos 29 gêneros de Livros é lido em 9 faixas de preço,
até juntar 1.000 livros com preço em cada faixa. Isso cobre com folga os ~2.000 mais vendidos de
cada gênero. São cerca de 13 mil páginas por passada completa (medido em 13/10: 13.795), e cada passada é um ciclo (ver abaixo). O
ranking geral de Livros não é lido: custava 675 páginas por passada (4,9%) para uns 565 livros que não estão em nenhum
gênero (0,29% do catálogo).

Algumas decisões que vieram de medir as páginas reais:

- Um navegador de verdade, sem janela, abre a primeira página e busca as outras de dentro dela.
  Com `requests`, a Amazon respondia com captcha ou erro 503.
- Cada card pode ter vários formatos. O preço é lido de dentro do link de cada formato, e assim
  parcelas e "outras ofertas" não se misturam com ele. Kindle Unlimited (R$ 0,00) é descartado.
- O preço de capa é o preço riscado do link de cada formato, com ou sem o rótulo "De:" (os dois aparecem). No
  Kindle, vale o "Preço digital sugerido"; o "Preço de capa sugerido" que o link do Kindle às vezes mostra é o do
  livro impresso e fica de fora, para não virar preço do Kindle. Um riscado que não é maior que o preço de venda não
  é gravado: a execução conta esses casos na observação e guarda o HTML da primeira página com um deles.
- Só entram ofertas vendidas pela própria Amazon (filtro "Vendido por" da busca). O filtro vale
  para o card, então um formato secundário pode vir de outro vendedor. Medimos isso em cerca de
  1,5% dos itens.
- O ritmo começa em 21 páginas por minuto e sobe aos poucos até o teto. O teto fica guardado no banco: começa em
  60 e sobe 25% por dia de coleta limpa (sem bloqueio e quase sem página curta). O dia limpo soma as execuções dele:
  a 8 páginas por minuto (o recuo depois de bloqueio) uma execução lê ~1.300 páginas, menos que as 2.000 de evidência,
  e com a conta por execução o teto não voltava a subir (as três sequências ficaram presas em 8 de 13 a 15/10). No GitHub cada sequência fica
  limitada a 45 programadas (uns 40 reais por minuto), abaixo dos 60 medidos sem bloqueio, porque o volume por dia é
  bem maior. Depois de um bloqueio o teto cai e fica parado por 3 dias. Quando a Amazon bloqueia ou devolve uma página
  com poucos resultados, o ritmo cai na hora. Para fixar o teto, `--ritmo-max`; para mudar o limite da subida,
  `--teto-auto-max`.
- A coleta roda em três sequências ao mesmo tempo, cada uma num servidor do GitHub e, portanto, com IP próprio.
  Os 29 gêneros estão divididos em três grupos de ~4,4 mil páginas (`PARTICOES_VENDIDOS`), e cada grupo tem o
  seu banco, o seu teto e o seu ciclo. Isso triplica as requisições por minuto que a Amazon recebe, em
  comparação com uma sequência só.
- **Ciclo**: o tempo entre duas passadas completas do catálogo. São duas por dia, em ciclo de 12 horas
  (00:00–12:00 e 12:00–24:00 de Brasília). A meta antiga de 3 horas (8 passadas por dia, cerca de 105 mil páginas)
  nunca se mediu sem bloqueio — o maior volume limpo foi 12,6 mil páginas por dia (13/10) — e a partir de 22/10 a
  Amazon passou a recusar as páginas fundas. O ciclo guardado no banco não desce de 12 horas; um 24 horas antigo
  volta a 12. Os degraus de 3 e 6 horas continuam existindo para `--ciclo-horas` (que fixa o ciclo e não aprende
  nada, nem respeita a pausa), mas a coleta recorrente não desce até eles. Sobe um degrau, no máximo até 12 horas,
  a cada bloqueio, ou quando passa de 2 por mil o número de páginas curtas e erros, ou quando uma janela acaba com
  fatias sem ler; 3 bloqueios seguidos vão direto às 12 horas. Dentro da janela, as fatias são lidas das mais velhas
  para as mais novas, para uma sequência lenta não repetir só as faixas baratas. No teto de 15 páginas por minuto
  cada sequência leva umas 5 horas para ler as ~4,4 mil páginas dela: a passada das 03:10 cabe antes das 8h. Com o
  teto mais baixo que fica guardado depois de um bloqueio (8 páginas por minuto), a manhã não fecha antes das 8h e
  a leitura continua na janela, em execuções de 165 minutos, até as 12h.
- **Depois de um bloqueio a coleta espera horas, não minutos**: 3 horas, dobrando a cada bloqueio seguido, até 24.
  Cada execução do GitHub roda num servidor novo, com outro IP, então tentar de novo meia hora depois seria, na
  prática, trocar de IP por causa do bloqueio. Não há rodízio de IP, disfarce de navegador nem resolução de captcha.
  HTTP 202 e 429 contam como bloqueio (a Amazon recusou a página), do mesmo modo que captcha, 500 e 503.
  Durante a pausa nenhuma execução pede nada à Amazon, nem a que o vigia reinicia (`--ignorar-pausa` existe, para
  quem roda à mão). Acabada a pausa, se ainda há fatias por ler, a próxima leitura começa na hora — não espera o
  ciclo de 24 horas nem a janela seguinte. Três falhas seguidas na mesma página continuam encerrando a execução;
  a retomada é no fim da pausa. As três sequências não trocam sinais: um bloqueio pausa só a sequência que o recebeu.
- Uma página com resultado ralo, mesmo com HTTP 200, conta como falha e é lida de novo.
- O histórico guarda intervalos ("R$ 39,90 de 2 a 15 de outubro"). Ele só cresce quando o preço muda. Com duas
  leituras por dia, a estimativa (a partir de 13% de preços mudando por dia e de até 30% com as oscilações) é de 1,5 a 4 MB por dia no banco, antes de compactar. O site mostra um preço
  por dia, o último lido nele: uma oscilação de poucas horas não vira "queda" nem "menor preço registrado".

Cada card também traz nota, número de avaliações, autor, capa, data e idioma. As avaliações
ordenam a busca e decidem quais livros vêm primeiro no índice do site.

## Agendamento e cópias

O cron do GitHub atrasa em horas, então a coleta não depende dele. Ao fim de cada execução, `varredura.yml` marca o
instante da próxima leitura (`scripts/proximo_ciclo.py`) e dispara `espera.yml`, que dorme até lá em saltos de ~5 horas
(um job vive no máximo 6) e dispara `varredura.yml` de novo: é um anel por sequência, e o grupo de concorrência
cancela uma espera quando outra chega, então não há dois anéis. A próxima leitura é:

- agora, se a janela do ciclo não fechou e a execução terminou limpa depois de ler pelo menos 500 páginas (o orçamento
  de 165 minutos acabou);
- agora, ou no fim da pausa se ela ainda não acabou, se a execução teve bloqueio ou parou por falhas seguidas e ainda
  há fatias por ler;
- senão, o próximo horário da agenda: 03:10 e 18:10 de Brasília, mais 10 minutos por sequência e um sorteio de até
  10 minutos, para a passada da manhã poder terminar antes das 8h e a da tarde começar depois das 18h. Se a janela
  atual já fechou, um horário que ainda cairia dentro dela é pulado. Com ciclo de 3 ou 6 horas (só `--ciclo-horas`),
  continua valendo o início da janela seguinte;
- nunca antes do fim da pausa que segue um bloqueio, nem menos de 10 minutos depois do começo da execução;
- se a publicação do banco falhou (por exemplo, a trava de preços recusou), pelo menos 3 horas depois: o que foi lido se
  perdeu, e ler de novo logo só repetiria o pedido à Amazon.

As janelas partem da meia-noite de Brasília (00:00–12:00 e 12:00–24:00). Uma fatia só conta como lida
na janela se a passada dela começou e terminou nela; uma que atravessa o fim da janela recomeça, porque o preço de um
ciclo precisa ser lido no ciclo. O dia fecha quando cada fatia teve uma passada completa dentro dele.

Como o anel depende do disparo de workflows pelo próprio workflow (`gh workflow run` com o token do GitHub, que a
documentação diz que funciona para `workflow_dispatch`), `varredura.yml` mantém dois crons (03:10 e 18:10 de Brasília,
06:10 e 21:10 UTC) como rede de segurança: se o anel não funcionar, ainda há uma leitura de manhã e outra de tarde.
O cron do GitHub atrasa em horas; quem cumpre o horário é o anel.

`vigia.yml` roda a cada 30 minutos e reinicia uma sequência que ficou sem execução em andamento nem criada há pouco (um
job cancelado, um disparo que não saiu). Para começar a coleta pela primeira vez, ou depois de pará-la, basta rodá-lo à
mão. A variável de repositório `COLETA_PAUSADA=true` desliga o anel e o vigia.

Depois de cada publicação confirmada, `varredura.yml` pede o site a `site.yml`. Em horas de servidor do GitHub, a
coleta faz duas passadas por dia em três sequências (cada uma pode levar várias horas; no teto de 15 páginas por
minuto, cerca de 5 horas), mais os jobs de espera, que ficam dormindo entre uma leitura e outra: com o anel inteiro, há quase sempre um
job vivo por sequência.

Cada sequência tem o seu banco na release `catalogo`: `catalogo-vendidos-<data>.db.gz`,
`catalogo-vendidos-b-<data>.db.gz` e `catalogo-vendidos-c-<data>.db.gz`. O site junta os três pelo ASIN. O
primeiro é o banco que já existia e continua com os livros e o histórico de todos os gêneros; os outros dois
começaram vazios, e é o site que une o histórico antigo ao novo. Antes de publicar uma
cópia nova, `scripts/verificar_banco.py` confere duas coisas: que o banco está íntegro e que nenhuma
tabela encolheu, e `scripts/verificar_precos.py` compara os preços dos livros físicos com os da cópia
anterior: se quase todos mudarem de uma vez (um erro de leitura, como reais lidos como centavos), a
publicação é recusada e a release fica com a última cópia boa. `scripts/catalogo_release.py` faz o download (com tentativas e, se a cópia mais nova
estiver quebrada, usando a anterior) e confere no GitHub o tamanho do que foi enviado. De cada banco ficam as 14
cópias mais recentes e a última de cada um dos 30 dias anteriores.

Se o navegador ou a página cair no meio da coleta, o cliente abre outro e a execução continua. Bloqueio
continua parando a execução (depois de 3 lotes seguidos com falha).

Avisos por e-mail (falha do workflow):

- o dia anterior ficou incompleto (verificado na primeira execução do dia);
- alguma fatia está sem passada completa há mais de 2 ciclos e 2 horas (`catalogo --exigir-frescor`): a coleta parou ou
  não dá conta do ciclo;
- os cards pararam de trazer capa e autor, o que costuma indicar que a Amazon mudou o layout.

`catalogo` mostra o frescor: o ciclo atual, a idade da passada completa mais velha e se há pausa em vigor.

`site.yml` gera o site com os bancos mais recentes. Ele se recusa a publicar se o site novo tiver menos de
70% dos livros do site no ar. Para publicar mesmo assim, rode-o à mão com a opção `forcar`.

Para ativar o site, uma vez só: *Settings → Pages → Source: GitHub Actions*.

## Arquivos do site

`python -m comparador site` gera:

- `dados/indice-N.json`: o índice da busca, em partes, das obras mais avaliadas para as menos. A
  primeira parte (~15 mil obras, ~0,7 MB compactado) chega rápido. As outras chegam enquanto a
  pessoa já está buscando.
- `dados/destaques.json`: o que a página inicial mostra, para ela não esperar o índice.
- `dados/h/XX.json`: o histórico de cada livro, em 256 arquivos.
- `dados/p/XXX.json`: os livros parecidos com cada livro, em 1024 arquivos (~90 KB compactado cada).
  A página do livro pede o seu junto com o histórico; o início junta os dos livros salvos e vistos.
  A conta fica em `comparador/parecidos.py`.
- `meta.json` e `eventos.json`: o resumo da coleta e as datas de promoção, que vêm de `eventos.csv`.

`python -m comparador site … --subgeneros subgeneros.json` põe os subgêneros (o snapshot do comando
`subgeneros`, só da ficção) na conta dos parecidos. Sem o arquivo, ou com um arquivo ilegível, o site sai como sem eles.

O formato de cada arquivo está descrito no começo de `comparador/site.py`.

A busca fica em `comparador/web/busca.js`, os cálculos e o gráfico em `comparador/web/livro.js`, a
lista em `comparador/web/lista.js` e a junção dos parecidos do início em `comparador/web/recomenda.js`.
Os quatro têm testes que rodam no Node. `python scripts/medir_parecidos.py <pasta ou URL de dados/>`
mede o tempo, o tamanho e as listas de livros-sonda dos parecidos.

## Outros comandos

```bash
python -m comparador grafico "título ou ASIN"                       # página avulsa com o histórico
python scripts/simular_precos.py data/vendidos.db data/simulado.db    # preços inventados até a Black Friday
python -m comparador subgeneros custo                                 # experimento dos subgêneros (abaixo)
```

O banco simulado parte de livros reais e inventa preços diários com três cenários de Black Friday:
desconto real, desconto falso (o preço sobe antes) e nenhum desconto. Ele serve para testar o site
antes da data e leva um aviso em todas as páginas.

**Subgêneros (experimento, sem coleta recorrente).** Os 29 gêneros são amplos: na ficção, os parecidos
de um livro são "os mais avaliados do gênero". A Amazon divide cada gênero em subcategorias ("Fantasia" →
"Épica"), e `python -m comparador subgeneros` mede o que custaria usá-las, sem mexer no site nem na coleta:
`descobrir` lê uma página por subcategoria e guarda a árvore, `rotular` lê as primeiras páginas de cada
folha para saber quais livros são de cada uma, e `custo` resume o que foi lido e quanto custaria repetir
isso toda semana, comparado com uma passada do coletor. O HTML lido fica em `data/subgeneros/paginas/` e
tudo se refaz dele, sem pedir nada de novo (`--pasta` muda o lugar). Cortesia com a Amazon: uma página
por vez, pausa de pelo menos 4 s, para na primeira página bloqueada sem tentar de novo e tem um teto de
400 páginas (`--max-paginas`), que conta as que já estão em disco. O comando não abre banco.

## Manter a base em dia

A base não entra no git (`data/` fica de fora). O que está no ar são os SQLite da release `catalogo` (um por sequência: `vendidos`, `vendidos-b`, `vendidos-c`) e o site no Pages, gerado a partir deles.

Não há chave de API nem segredo de loja. O Actions usa o `GITHUB_TOKEN` que o próprio GitHub fornece. O que liga e desliga a coleta são variáveis de repositório (Settings → Secrets and variables → Actions → Variables):

- `COLETA_PAUSADA=true` para o anel, o vigia e os subgêneros;
- `SUBGENEROS_ATIVO=true` para a coleta dos subgêneros da ficção (desligada até lá);
- `SUBGENEROS_NO_SITE=true` para esses rótulos entrarem no site.

Para ver se está fresco, sem baixar o banco: `dados/meta.json` do site (`lido_ate`) ou o resumo da última execução de `varredura.yml`. Para atualizar à mão, com Chrome ou Edge:

```bash
python -m comparador varrer --dry-run    # plano, sem pedir nada à Amazon e sem gravar
python -m comparador varrer --minutos 20
python -m comparador catalogo
```

Publicar na release e no Pages é o workflow, não um commit. Uma passada completa são cerca de 13 mil páginas; a Amazon bloqueia cliente apressado, e um bloqueio grava pausa de horas no banco daquela sequência.

## Limites

- Só livros que aparecem nas listas de mais vendidos dos gêneros. Um livro que sai da lista para de receber
  preço novo, e some da busca depois de 14 dias. Os que só aparecem no ranking geral de Livros, sem estar em
  nenhum gênero, deixaram de ser atualizados e saem do site nesse prazo.
- O preço de capa só aparece quando há desconto (sem riscado no card, não há o que ler).
- Ler as páginas da Amazon por programa vai contra os termos de uso dela. A coleta espaça as
  requisições, desacelera ou para quando é bloqueada, e não tenta contornar bloqueios. Ler em três servidores
  ao mesmo tempo triplica a carga em cada instante. A meta antiga de uma passada a cada 3 horas multiplicava por oito
  o volume por dia que se mediu e foi o que a Amazon passou a bloquear; a coleta ficou em duas passadas por dia.
  Foram escolhas de quem mantém este repositório. Não há garantia de que não haverá
  bloqueios: o que há é pausa de horas (dobrando até 24), teto mais baixo e retomada quando a pausa acaba. Para ler uma
  sequência de cada vez, dispare `varredura.yml` à mão com a opção `alvo`; para parar, `COLETA_PAUSADA=true`.
- O GitHub Actions é feito para o software do próprio repositório, e duas passadas por dia em três sequências
  (cada uma pode levar várias horas, fora os jobs de espera) podem ser vistas como uso indevido. O mesmo comando roda em qualquer máquina
  com `cron`.
- A frescura dos preços é a do ciclo, não a de cada segundo: com duas passadas por dia, um preço pode ter até umas 12 horas
  (mais a duração da passada) quando o site o mostra. Livros que a Amazon deixa de listar nos mais vendidos deixam de ser
  lidos.
- **Subgêneros (opcional, só ficção).** `subgeneros.yml` lê, a cada ciclo, a página 1 de cada subcategoria dos gêneros de
  ficção e as 10 primeiras páginas de mais vendidos de cada folha: ~2.700 páginas por ciclo (384 folhas e 76 nós internos, medidos
  em 14/10/2026; 21% de uma passada do coletor, ou ~1,5% do que ele lê por semana num ciclo a cada 14 dias), uma de cada vez,
  com pausa de 4 s e num servidor só. Mudar os gêneros (`SUBGENEROS_GENEROS`) ou o K vale a partir do ciclo seguinte; um ciclo com
  menos da metade das folhas do anterior é recusado. Não roda
  enquanto a variável `SUBGENEROS_ATIVO` não for `true`; um ciclo continua de uma execução para a seguinte (o estado fica na
  release) e o intervalo entre ciclos é de 14 dias, provisório até a troca entre os dois primeiros ciclos mostrar quanto os
  rótulos mudam. Depois de um bloqueio, pausa de 24 h (dobra a cada um seguido, até 7 dias) e nenhuma tentativa de novo na
  mesma execução. O snapshot só entra no site com `SUBGENEROS_NO_SITE=true`. Para parar: apagar `SUBGENEROS_ATIVO` (ou
  `COLETA_PAUSADA=true`, que para tudo).
- `data/` não vai para o git.
