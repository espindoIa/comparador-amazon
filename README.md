# Preços de livros

Guarda o histórico de preço dos livros mais vendidos da Amazon.com.br. Serve para conferir ofertas
como as da Black Friday: um desconto só quer dizer alguma coisa comparado com o que o livro custou
nos meses anteriores, e a Amazon não mostra isso.

São duas partes:

- um coletor, que lê as páginas de mais vendidos de cada gênero de livros várias vezes por dia (a meta é a
  cada 3 horas) e anota o preço de cada formato (capa comum, capa dura, Kindle, audiolivro);
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
- **Ciclo**: o tempo entre duas passadas completas do catálogo. A meta é 3 horas (8 passadas por dia, cerca de 105
  mil páginas por dia). O maior volume que se mediu sem bloqueio foi de 12,6 mil por dia (13/10), então o ciclo é um degrau
  guardado no banco: começa em 12 horas, desce um degrau (12, 6, 3) por dia limpo e chega a 3 horas no terceiro
  dia. Sobe um degrau a cada bloqueio, ou quando passa de 2 por mil o número de páginas curtas e erros (a limitação
  costuma aparecer assim antes do bloqueio), ou quando uma janela acaba com fatias sem ler (a sequência não dá conta de
  uma passada no tempo do ciclo), e vai direto ao ciclo diário depois de 3 bloqueios seguidos. Só desce quando o dia no
  degrau passou sem nenhum sinal de alerta (mais de 0,5 falha leve por mil páginas, somando as execuções do dia),
  depois de 3 dias de espera, se o degrau subiu, e se a passada, no teto atual, ocupa até 85% do degrau de baixo (sem
  isso o ciclo desceria mais rápido que o teto sobe e a passada estouraria a janela). Bloqueio, aperto e janela
  estourada olham só a execução. Dentro da janela, as fatias são lidas das mais velhas para as mais novas, para uma sequência lenta
  não repetir só as faixas baratas. Para fixar o ciclo, `--ciclo-horas`.
  A janela de 3 horas é apertada: no ritmo de 45 programadas (uns 40 reais por minuto) cada sequência leva uns 110
  minutos para ler as ~4,4 mil páginas dela, e sobram uns 70 de folga. Se a Amazon desacelerar a resposta ou o ritmo recuar,
  a passada não cabe e o ciclo sobe sozinho para 6 horas: o piso real pode acabar sendo 6 horas.
- **Depois de um bloqueio a coleta espera horas, não minutos**: 3 horas, dobrando a cada bloqueio seguido, até 24.
  Cada execução do GitHub roda num servidor novo, com outro IP, então tentar de novo meia hora depois seria, na
  prática, trocar de IP por causa do bloqueio. Não há rodízio de IP, disfarce de navegador nem resolução de captcha.
  Durante a pausa nenhuma execução pede nada à Amazon, nem a que o vigia reinicia (`--ignorar-pausa` existe, para
  quem roda à mão). As três sequências não trocam sinais: um bloqueio pausa só a sequência que o recebeu.
- Uma página com resultado ralo, mesmo com HTTP 200, conta como falha e é lida de novo.
- O histórico guarda intervalos ("R$ 39,90 de 2 a 15 de outubro"). Ele só cresce quando o preço muda, e com leituras
  de 3 em 3 horas muda mais vezes (estimativa a partir de 13% de preços mudando por dia e de até 30% com as oscilações: de 1,5 a 4 MB por dia no banco, antes de compactar). O site mostra um preço
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
- senão, o início da janela seguinte, com 10 minutos de defasagem por sequência e um sorteio de até 10 minutos, para
  as três não baterem juntas;
- nunca antes do fim da pausa que segue um bloqueio, nem menos de 10 minutos depois do começo da execução;
- se a publicação do banco falhou (por exemplo, a trava de preços recusou), pelo menos 3 horas depois: o que foi lido se
  perdeu, e ler de novo logo só repetiria o pedido à Amazon.

As janelas partem da meia-noite de Brasília (com ciclo de 3 horas: 00:00, 03:00, 06:00...). Uma fatia só conta como lida
na janela se a passada dela começou e terminou nela; uma que atravessa o fim da janela recomeça, porque o preço de um
ciclo precisa ser lido no ciclo. O dia fecha quando cada fatia teve uma passada completa dentro dele.

Como o anel depende do disparo de workflows pelo próprio workflow (`gh workflow run` com o token do GitHub, que a
documentação diz que funciona para `workflow_dispatch`), `varredura.yml` mantém um cron diário (00:41 de Brasília) como
rede de segurança: se o anel não funcionar, é a coleta diária de antes.

`vigia.yml` roda a cada 30 minutos e reinicia uma sequência que ficou sem execução em andamento nem criada há pouco (um
job cancelado, um disparo que não saiu). Para começar a coleta pela primeira vez, ou depois de pará-la, basta rodá-lo à
mão. A variável de repositório `COLETA_PAUSADA=true` desliga o anel e o vigia.

Depois de cada publicação confirmada, `varredura.yml` pede o site a `site.yml`. Em horas de servidor do GitHub, a
coleta passa de umas 4 por dia para umas 45 lendo quando o ciclo chega a 3 horas (3 sequências × 8 passadas × ~110
minutos), mais os jobs de espera, que ficam dormindo entre uma leitura e outra: com o anel inteiro, há quase sempre um
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

## Limites

- Só livros que aparecem nas listas de mais vendidos dos gêneros. Um livro que sai da lista para de receber
  preço novo, e some da busca depois de 14 dias. Os que só aparecem no ranking geral de Livros, sem estar em
  nenhum gênero, deixaram de ser atualizados e saem do site nesse prazo.
- O preço de capa só aparece quando há desconto (sem riscado no card, não há o que ler).
- Ler as páginas da Amazon por programa vai contra os termos de uso dela. A coleta espaça as
  requisições, desacelera ou para quando é bloqueada, e não tenta contornar bloqueios. Ler em três servidores
  ao mesmo tempo triplica a carga em cada instante, e uma passada a cada 3 horas multiplica por oito o volume
  por dia que se mediu. Foram escolhas de quem mantém este repositório. Não há garantia de que não haverá
  bloqueios: o que há é uma rampa de 3 dias, pausa de horas e ciclo mais longo quando eles aparecem. Para ler uma
  sequência de cada vez, dispare `varredura.yml` à mão com a opção `alvo`; para parar, `COLETA_PAUSADA=true`.
- O GitHub Actions é feito para o software do próprio repositório, e umas 45 horas diárias de servidor lendo (fora as de espera)
  podem ser vistas como uso indevido. O mesmo comando roda em qualquer máquina
  com `cron`.
- A frescura dos preços é a do ciclo, não a de cada segundo: com ciclo de 3 horas, um preço pode ter até umas 3 horas
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
