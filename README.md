# Comparador de preços de livros (Amazon Brasil)

Lê, todo dia, os preços dos ~2.000 livros mais vendidos de cada categoria de livros da Amazon
Brasil (algumas dezenas de milhares de livros diferentes) e guarda o histórico. O objetivo é saber se uma oferta de
Black Friday ou Dia do Consumidor é boa de verdade, comparando com o preço praticado no resto
do ano, e não só com o preço de capa.

A coleta roda sozinha no GitHub Actions (grátis, sem deixar o computador ligado). A lista de
desejos da Amazon não é mais lida: os preços vêm só das varreduras de catálogo.

## Uso

```bash
pip install -r requirements.txt     # inclui o Playwright, que controla o Chrome/Edge já instalado
# só se você não tiver Chrome nem Edge: python -m playwright install chromium
python -m comparador varrer --vendidos   # lê os mais vendidos de hoje (banco em data/catalogo.db)
python -m comparador catalogo --vendidos # progresso de hoje e dias sem varredura completa
python -m comparador grafico "título"    # página com o histórico de um livro
python -m unittest discover -s tests     # testes
```

Opções de `varrer`: `--vendidos` (os mais vendidos de cada gênero), `--no` (uma categoria),
`--minutos`, `--max-paginas` e `--cliente auto|navegador|curl|requests` (veja abaixo). `--db`
(antes do subcomando) escolhe o arquivo do banco.

## Por que um navegador

A Amazon responde com erro 503 ou captcha a clientes que não parecem um navegador.
Nos testes, a partir do mesmo IP e nos mesmos minutos:

| Cliente | Resultado |
|---|---|
| `requests` | captcha ou erro 503 |
| `curl` | intermitente |
| **navegador (Playwright)** | **sempre 200** |

O cliente navegador abre a primeira página de verdade, como você faria, e busca as
seguintes com `fetch` dentro dela, na mesma sessão. Ele roda sem janela (headless) e usa
o Chrome ou o Edge que você já tem. Para indicar outro navegador, defina a variável
`COMPARADOR_NAVEGADOR` com o caminho do executável.

## Os mais vendidos de cada categoria, todo dia

```bash
python -m comparador --db data/vendidos.db varrer --vendidos
python -m comparador --db data/vendidos.db catalogo --vendidos
```

Lê, todo dia, os mais vendidos de cada um dos 29 gêneros de Livros (Literatura, Romance,
Autoajuda, HQs e mangás, Infantil...) e do ranking geral de Livros, com o preço de cada
formato (capa comum, capa dura, Kindle, audiolivro) e o preço de capa quando há desconto.
No workflow `varredura.yml` é a linha `vendidos` da matrix, num servidor próprio; o
banco vai para a release `catalogo` como `catalogo-vendidos-<data>.db.gz`.

**Os ~2.000 mais vendidos de cada categoria, só com preço de compra.** Na ordem "Mais vendidos", a
Amazon só mostra **75 páginas (1.200 livros) por consulta**, embora a paginação anuncie 400, e as
páginas de busca não mostram a posição de vendas de cada livro. Mas cada **faixa de preço** (filtro
`p_36`) tem o seu próprio ranking de 75 páginas, na mesma ordem. Por isso cada gênero é lido em
3 faixas (até R$ 39,99; R$ 40 a R$ 79,99; R$ 80 ou mais, em `FAIXAS_VENDIDOS`), e cada faixa para ao
completar **1.000 livros com preço de compra** (ou ao chegar à página 75). Juntas, as faixas contêm
os ~2.000 mais vendidos do gênero, a não ser que uma faixa sozinha tenha mais de 1.000 deles (em
média são ~670 por faixa); na prática a leitura passa de 2.000 (até ~3.000 por gênero). A faixa vale
para o card: um livro entra se algum formato dele estiver nela. Livros "fora de
catálogo", isto é, sem preço de compra na busca (indisponíveis, ou e-books só do Kindle Unlimited,
que aparecem como "R$ 0,00"), não entram na base e não contam nos 1.000 de cada faixa; a leitura segue um pouco
mais fundo para compensar. Se um deles voltar a aparecer com preço em outro dia, entra na base nesse
dia; o que já estava na base nunca é apagado. **Só livros vendidos pela Amazon:** toda consulta usa o filtro "Vendido por Amazon.com.br" da própria
busca (`p_6`, em `VENDEDOR_AMAZON`, `comparador/busca.py`). Limite medido: o filtro vale para o livro
(o card), não para cada formato. Um card passa se alguma oferta dele é da Amazon, então um formato do
mesmo card pode estar à venda só por terceiros. Testes com a busca real: o filtro tira ~15% dos
cards de um gênero e funciona junto com o filtro de preço. O vendedor "Amazon Servicos de Varejo do
Brasil Ltda" (um 2º filtro, quase só e-books) não entra, porque a busca não aceita os dois juntos.
O site esconde da busca o que não foi visto desde que o filtro começou (livros de outros vendedores
que entraram antes), assim que a primeira varredura completa com o filtro termina; o histórico deles
continua guardado, e quem estiver na sua lista aparece com "sem coleta recente".
São 90 consultas (29 gêneros mais o ranking geral, 3 faixas cada),
até ~5.700 páginas, cerca de 2 h por dia no ritmo atual (dividido entre as execuções do dia; eram ~4h40 a
21 páginas/min); como um livro pode
estar em mais de um gênero, o número de livros distintos fica bem abaixo de 90 mil. Os gêneros (inclusive HQs e mangás, que não são mais varridos
à parte) estão em `GENEROS`, em `comparador/varredura.py`.

### Ritmo da coleta

O ritmo é programado (`comparador/ritmo.py`), com espaçamento uniforme entre as requisições (cada
intervalo varia ±30%), e não uma pausa fixa depois de cada página:

- começa em 21 páginas/min (o ritmo de antes: 0 bloqueios em ~11 mil páginas) e sobe 25% a cada 100
  páginas boas, até o teto de 60 programadas (`--ritmo-max`);
- acima de ~45 programadas são lidas 2 ou 3 fatias diferentes ao mesmo tempo (uma página por fatia de
  cada vez), numa única sessão do navegador. O ritmo **real** fica ~20% abaixo do programado, porque cada
  lote espera a requisição mais lenta: 60 programadas dão ~50 reais;
- **bloqueio** (captcha, HTTP 500/503) ou **falha leve repetida** (outra em menos de 500 páginas boas):
  o ritmo cai para o mínimo (8 programadas) e o teto passa a ser 70% do ritmo em que a falha aconteceu;
- **falha leve isolada** (página curta, erro de rede, layout desconhecido): o ritmo cai pela metade e volta
  a subir; o teto não muda. Falhas isoladas acontecem, e não devem corroer o ritmo do dia inteiro;
- depois de qualquer falha, a mesma página é lida de novo depois de uma pausa de 90 s; 3 lotes seguidos com
  falha encerram a execução (a próxima do dia continua de onde parou).

"Sem erro" inclui o que não chega como erro. Uma página do meio da fatia com menos de 8 resultados
(as normais têm ~16), ou a página 1 vazia numa fatia que tinha 5 páginas ou mais na passada anterior,
conta como **falha ("página curta") mesmo com HTTP 200**, e só é aceita se vier igual numa segunda
leitura. Ao fim de cada fatia, a execução avisa se leu menos de 80% dos livros da passada anterior.
`execucoes` guarda as páginas curtas e as páginas por minuto reais de cada execução.

Opções do `varrer`: `--ritmo` (início), `--ritmo-max` (teto), `--subir-a-cada`, `--parar-na-falha` (para
medir, sem insistir), `--generos` (só estes nós) e `--faixas` (bordas das faixas de preço em reais, ex.:
`0,20,30,40,50,60,80,120,200`).

Medido em out/2026 em servidores do GitHub (cada teste num IP; ritmos **reais**, em páginas/min):

| Teste | Ritmo real | Páginas | Bloqueios / erros / curtas |
|---|---|---|---|
| Controle, 21 programadas | 21 | 600 | 0 / 0 / 0 |
| Rampa de 20 a 120 programadas | de 25 a ~80, estável por ~9 min | 1.500 | 0 / 0 / 0 |
| 1 hora no teto (60 programadas), 7 gêneros | 54 no trecho do teto, 48 na média | 2.905 | 0 / 0 / 0 |
| 1ª rampa, que parava na 1ª falha | 21 | 122 | 0 / 0 / 1 |

A única falha foi a página 60 de uma fatia que veio com 0 resultados (HTTP 200); no controle e na rampa,
a mesma fatia leu a página 60 normalmente. São **1 página curta em ~5.100 medidas**. O que foi medido
vai até ~80 páginas/min reais por ~9 min e ~54 por ~40 min; o teto padrão fica abaixo disso. É uma
amostra de um dia, com IPs de servidores do GitHub, e a Amazon pode mudar o comportamento: se aparecerem
bloqueios, a resposta é baixar `--ritmo-max`, não contornar.

## Varredura de uma categoria inteira (disponível, mas não agendada)

A categoria inteira de HQs e mangás já foi varrida todo dia, e o comando continua disponível, mas
o workflow não a agenda mais: os HQs mais vendidos entram pelo ranking acima. Para acompanhar uma
categoria inteira, o comando `varrer --no` lê todas as páginas de busca da categoria. Cada página traz ~16 livros com
preço, o que é ~16x mais barato que consultar livro por livro.

```bash
python -m comparador varrer --no 7842710011     # banco em data/catalogo.db
python -m comparador catalogo --no 7842710011   # progresso de hoje e dias sem varredura completa
```

Medido em out/2026 para HQs, Mangás e Graphic Novels (nó `7842710011`):

| | |
|---|---|
| Tamanho | 33 fatias, ~2.050 páginas, ~32 mil itens (cada formato é um item) |
| Ritmo | pausa de 1–3 s, ~20 páginas/min, sem bloqueios (testado também com 0,3–1 s: 36 páginas/min, sem bloqueio) |
| Tempo por dia | ~1h40 num único servidor |

O workflow `.github/workflows/varredura.yml` (hoje só com a linha `vendidos`) roda 4 vezes por dia. Com as
3 faixas de preço, as duas primeiras completam o dia; as outras só continuam o que faltou (o progresso é salvo a cada página) ou
terminam em segundos. Uma passada que ficou pela metade ontem recomeça da página 1, para
que todos os preços de um dia sejam daquele dia. A primeira execução de cada dia falha (e
o GitHub avisa por e-mail) se o dia anterior ficou incompleto.

Os bancos ficam na release `catalogo` do repositório, um arquivo por categoria
(`catalogo-<nó>-<data>.db.gz`). Para baixar: *Releases → catalogo*, o arquivo mais
recente, e `gunzip`.

**Outras categorias:** acrescente o nó na lista `matrix.no` do workflow; cada categoria
roda em paralelo, num servidor próprio. Os nós aparecem no link da categoria na Amazon
(`rh=n:NÚMERO`). Exemplos: Fantasia, Horror e Ficção Científica `7841775011`, Literatura e
Ficção `7872687011`, Infantil `7844001011`. O catálogo **inteiro** de livros (mais de 1
milhão de itens, só o preço R$ 49,90 tem mais de 40 mil) não cabe num dia com esta
abordagem; categorias do tamanho de HQs e mangás, sim.

**Problemas encontrados e como foram resolvidos (todos medidos em páginas reais):**

| Problema | Solução |
|---|---|
| A busca mostra no máximo 400 páginas, e as mais fundas vêm incompletas | A categoria é dividida em fatias por faixa de preço. Uma fatia com mais de 100 páginas é dividida ao meio automaticamente. Um preço exato comum (R$ 29,90) tem ~45 páginas, então sempre cabe |
| Card com vários formatos (capa comum, Kindle, capa dura), cada um com ASIN e preço próprios. O card pode até ser do Kindle | O preço é lido de dentro do link `/dp/ASIN` que o contém: cada formato fica com o próprio ASIN e o próprio "De:" |
| Parcelas ("em até 2x de R$ 21,73") e "outras ofertas" perto do preço | Ficam fora do link do formato, então são ignoradas |
| Kindle Unlimited aparece como R$ 0,00 | Descartado (não é preço de venda) |
| Formatos inesperados ("Canoa, Grampeado ou Costurado") | Rótulo desconhecido é guardado como veio, em vez de perdido |
| Sem o parâmetro de ordenação, a Amazon devolve uma vitrine sem resultados | Toda URL tem `s=price-asc-rank`. Página sem resultados e sem a marca "Nenhum resultado" é tratada como mudança de layout (erro), não como fim |
| O filtro de preço vale para qualquer formato do card: as fatias se sobrepõem | Observações repetidas não duplicam o histórico |
| Execução interrompida (tempo, bloqueio, queda) | O progresso é salvo a cada página; a próxima execução continua da página seguinte |
| Bloqueio | Repete a mesma página depois de uma pausa de 90 s, recua para o ritmo mínimo e baixa o teto de ritmo, e para depois de 3 lotes seguidos com falha; a próxima execução do dia continua |
| Página que vem com poucos resultados e HTTP 200 (a fatia pareceria acabar antes da hora) | Conta como falha ("página curta"), é lida de novo depois de uma pausa e só é aceita se vier igual; `execucoes` guarda quantas houve |
| Histórico gigante (milhões de linhas por mês) | O histórico guarda intervalos ("R$ X de tal dia a tal dia"): só cresce quando o preço muda. Mais de 10 dias sem ver o item abre um intervalo novo, para o buraco ficar visível |
| Banco publicado vazio ou corrompido por um erro | `scripts/verificar_banco.py` recusa banco corrompido ou com menos linhas que o anterior. Cada execução publica uma cópia nova com data e só depois apaga as antigas (mantém 14) |
| Dia incompleto | 4 execuções por dia continuam de onde a anterior parou; se mesmo assim o dia ficar incompleto, a primeira execução do dia seguinte falha e o GitHub avisa por e-mail. `catalogo` lista os dias sem varredura completa |

**Limites que continuam existindo:**
- Itens sem preço (indisponíveis) não aparecem na busca, então não entram no catálogo.
- Se o preço muda no meio da leitura, o item pode mudar de fatia e ser visto duas vezes
  ou nenhuma naquele dia. Medido: a fatia de R$ 29,90 (710 resultados) devolveu 709 itens
  distintos, sem repetição, em 45 páginas.
- O preço de capa só aparece na busca quando há desconto. Sem desconto, fica vazio.
- E-books do Kindle Unlimited aparecem na busca só como "R$ 0,00, grátis com
  assinatura", sem o preço de compra; por isso ficam de fora. Livros físicos não são
  afetados.
- Os termos de uso do GitHub Actions dizem que ele serve para o software do próprio
  repositório; ~2 horas diárias de varredura podem ser consideradas uso indevido. Se
  isso preocupar, o mesmo comando roda em qualquer máquina sempre ligada (`cron`).
- Os termos da Amazon proíbem robôs. Quanto mais volume, maior o risco de bloqueio.

## Banco (`data/catalogo.db`)

| Tabela | Conteúdo |
|---|---|
| `catalogo` | Cada item visto (cada formato é um ASIN): título, formato, primeira e última vez visto |
| `historico` | Preço em intervalos ("R$ X de tal dia a tal dia"), com o preço de capa quando há |
| `fatias` | Progresso da varredura: faixas de preço e a próxima página de cada uma |
| `execucoes`, `dias` | Auditoria de cada execução e dos dias com varredura completa |

Os valores ficam em **centavos** e as datas em UTC.

## Avisos

- Ler as páginas da Amazon por script vai contra os termos de uso dela. A varredura espaça as
  requisições, fica mais lenta ou para quando há bloqueio ou resultado ralo, e não tenta contornar
  bloqueios (sem rodízio de IP ou proxy, disfarce de navegador ou captcha).
- `data/` (banco e HTML) não vai para o git.

## O app: busca por título e lista de desejos

Um site estático (sem servidor, grátis no GitHub Pages) com:

- **Busca por título, autor ou ASIN/ISBN-10,** ignorando acentos e a ordem das palavras. Cada formato
  (capa comum, capa dura, Kindle...) aparece como um resultado, com o preço mais recente.
- **Filtrar e ordenar** (na busca, mesmo sem digitar nada): ordenar por mais relevantes, menor preço,
  maior preço, maior desconto sobre o preço de capa ou título; filtrar por formato, faixa de preço,
  "só com desconto sobre a capa" e "só na minha lista". Os filtros se combinam entre si e com o texto.
- **Página de cada livro** com o histórico de preço, os números e os botões de zoom e de dados extras
  (veja "Histórico de preço por livro").
- **Minha lista:** o botão "Adicionar" em qualquer livro o põe na lista. Ela mostra o preço de hoje, a
  diferença para o preço mais comum dos últimos 90 dias e o mais barato do período, e pode ser
  ordenada por título, preço ou diferença. **A lista fica só no navegador de quem a cria** (não há
  conta nem servidor). Para levá-la a outro aparelho, use "Levar a lista para outro aparelho": copie
  num e cole no outro. Só entram livros que o catálogo acompanha (os ~2.000 mais vendidos de cada categoria).

```bash
python -m comparador site data/catalogo-vendidos.db --saida site
cd site && python -m http.server 8000      # abra http://localhost:8000
```

**Publicação automática:** o workflow `site.yml` baixa os bancos mais recentes da release `catalogo`,
gera o site e publica no GitHub Pages depois de cada varredura e uma vez por dia. Configuração, uma
vez só: *Settings → Pages → Build and deployment → Source: GitHub Actions*. O endereço aparece em
*Actions → site → publicar*. O site é público (como o repositório), e os dados também.

Tamanho medido com os ~31 mil livros: índice de busca de 3 MB (1 MB compactado) e 4 MB de históricos,
carregados em pedaços só quando um livro é aberto.

O cálculo dos números e o gráfico ficam em um único arquivo, `comparador/web/livro.js`, usado pelo
site e pelo comando `grafico`, e testado com `node tests/livro.test.js` (os testes de Python o rodam
quando o `node` está instalado).

## Histórico de preço por livro (gráfico e números)

```bash
python -m comparador --db data/catalogo-vendidos.db grafico "título ou ASIN"
```

Gera `data/grafico-<ASIN>.html`, uma página única (abra no navegador, não precisa de servidor). A página **não tira conclusões**: mostra os
dados para quem compra decidir. Usa `data/catalogo.db`, ou o banco passado em `--db`. Se o termo casar com vários livros, lista os ASINs para repetir com o exato.

**Gráfico (ajustável):** abre só com o preço (degraus), o preço mais comum dos últimos 90 dias
(pontilhada) e as promoções. Abaixo dele há botões:

- **Período:** 30 dias, 90 dias, Tudo, e um atalho por promoção (mostra os 45 dias antes e 7 depois).
- **Zoom:** aproximar, afastar e andar para trás/frente no tempo. A escala de preço se ajusta ao trecho visível.
- **Mostrar** (liga e desliga; a escolha fica guardada no navegador): preço mais comum, faixa usual
  (onde ficou a metade central dos dias), preço de capa, promoções, dias sem coleta (hachurado) e
  um ponto para cada dia coletado.

Passando o mouse (ou o dedo) aparece o preço de cada dia. Períodos sem coleta nunca são preenchidos
como se tivessem sido observados. Funciona no celular. O gráfico é desenhado no navegador (precisa de
JavaScript); os números da página funcionam sem ele.

**Números, em linguagem comum:** no topo, quatro cartões: preço de hoje, preço mais comum (mediana
de 90 dias), o mais barato e o mais caro, com as datas. Para cada evento: o preço no evento e quanto
está acima ou abaixo do preço mais comum dos 90 dias *anteriores*, o intervalo em que andou, o pico
das 3 semanas antes e a última vez em que esteve igual ou menor. Em "Mais detalhes" (recolhido):
faixa onde ficou a metade central dos dias, preço de capa e quantos dias de coleta sustentam a conta.
Com pouco histórico, a página avisa.

Os bancos do catálogo estão em *Releases → catalogo* (descompacte o `.db.gz`).

### Simulação para testar antes da Black Friday

```bash
python scripts/simular_precos.py ORIGEM.db data/simulado.db --livros 2000
python -m comparador --db data/simulado.db grafico "título ou ASIN"
```

Parte dos livros e preços **reais** de um banco do catálogo e inventa, num banco novo (o original
não é tocado), preços diários de 28/09 a 30/11/2026 com oscilação de até ±12%. Cada livro recebe
um cenário sorteado (`real`: queda de 15 a 40% na Black Friday; `falso`: preço sobe 15 a 35% nas 3
semanas antes e volta; `nenhum`: sem promoção), gravado em `simulacao.cenario`. O banco simulado
leva um aviso nos gráficos e **não deve ser misturado ao real**.
