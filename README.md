# Comparador de preços de livros (Amazon Brasil)

Coleta, uma vez por dia, o preço dos livros da sua **lista de desejos** (e de ASINs
avulsos) e guarda o histórico num banco SQLite local. O objetivo é saber se uma oferta
de Black Friday ou Dia do Consumidor é boa de verdade, comparando com o preço praticado
no resto do ano, e não só com o preço de capa.

## Uso

```bash
pip install -r requirements.txt     # inclui o Playwright, que controla o Chrome/Edge já instalado
# só se você não tiver Chrome nem Edge: python -m playwright install chromium
python -m comparador init            # cria data/precos.db e importa eventos.csv
# cole o link da sua lista de desejos em desejos.txt (a lista precisa ser Pública ou Compartilhada)
python -m comparador coletar
python -m comparador status          # últimas coletas e último preço de cada livro
python -m unittest discover -s tests # testes
```

Opções de `coletar`:

- `--desejos LINK` passa o link direto, sem usar `desejos.txt` (pode repetir).
- `--lista livros.txt` define o arquivo de ASINs avulsos, fora de qualquer lista.
- `--detalhar auto|todos|nenhum` define quando consultar a lista de ofertas de cada livro (veja abaixo).
- `--cliente auto|navegador|curl|requests` define o cliente HTTP (veja "Por que um navegador").
  O padrão usa o navegador se o Playwright estiver instalado, senão o `curl`, senão o `requests`.

Para rodar todo dia, agende o comando no `cron` (Linux/Mac) ou no Agendador de Tarefas
(Windows), com o computador ligado. Exemplo de cron, às 9h:
`0 9 * * * cd /caminho/comparador-amazon && python3 -m comparador coletar`

## Por que um navegador

A Amazon responde com erro 503 ou captcha a clientes que não parecem um navegador.
Nos testes, a partir do mesmo IP e nos mesmos minutos:

| Cliente | Lista de desejos (página 1) | Páginas seguintes | Lista de ofertas |
|---|---|---|---|
| `requests` | 0 de 4 | – | captcha |
| `curl` | 2 de 3 | 0 de 6 | intermitente |
| **navegador (Playwright)** | **sempre 200** | **9 de 9 (82 itens)** | **3 de 3** |

O cliente navegador abre a primeira página de verdade, como você faria, e busca as
seguintes com `fetch` dentro dela, na mesma sessão. Ele roda sem janela (headless) e usa
o Chrome ou o Edge que você já tem. Para indicar outro navegador, defina a variável
`COMPARADOR_NAVEGADOR` com o caminho do executável.

## De onde vêm os preços

| Fonte (`precos.fonte`) | O que traz | Custo |
|---|---|---|
| `lista_desejos` | Preço atual de cada item | 1 requisição a cada ~10 itens, todo dia |
| `ofertas` | Preço da oferta principal, **preço de capa**, vendedor e condição (novo/usado) | 1 requisição por livro |

Com `--detalhar auto` (o padrão), a lista de ofertas só é consultada quando o livro é
novo no banco, quando o preço mudou na lista de desejos, ou quando o último detalhe tem
mais de 7 dias. Numa lista de 50 livros, o normal é fazer 5 requisições num dia comum
em vez de 50, o que reduz muito a chance de bloqueio.

A página do produto (`/dp/ASIN`) **não** é usada: em acessos automatizados a Amazon
costuma esconder o preço nela ("adicione ao carrinho para ver o preço").

## Coleta automática (sem deixar o computador ligado)

O workflow `.github/workflows/coleta.yml` roda no GitHub Actions (grátis em repositório
público) e guarda o banco na branch `dados`, arquivo `precos.db`.

**Configuração, uma vez só:**

1. Em *Settings → Branches*, deixe `main` como branch padrão (o GitHub só dispara
   agendamentos a partir da branch padrão).
2. Em *Settings → Secrets and variables → Actions → New repository secret*, crie
   `LISTA_DESEJOS` com o link da sua lista. Como o repositório é público, o link vai no
   segredo e não em `desejos.txt`.
3. Opcional, mas recomendado: crie uma conta grátis em [healthchecks.io](https://healthchecks.io),
   crie um check com período de 1 dia e tolerância de 1 dia e guarde a URL de ping no
   segredo `HEALTHCHECK_URL`. Se o GitHub parar de rodar o agendamento, ele avisa por
   e-mail.
4. Teste em *Actions → coleta → Run workflow*.

**Como evita buracos nos dados:**

| Risco | Defesa |
|---|---|
| O cron do GitHub atrasa ou pula uma execução | 5 agendamentos por dia (05h, 09h, 14h, 19h e 23h, horário de Brasília). Cada um só coleta se o dia ainda não tem coleta completa; os outros terminam em segundos |
| A Amazon bloqueia ou a lista vem incompleta | A coleta é marcada como incompleta e não cobre o dia. O workflow falha (o GitHub avisa por e-mail) e o próximo agendamento tenta de novo |
| Duas execuções ao mesmo tempo corromperiam o banco | `concurrency` serializa as execuções |
| Falha no meio da coleta | O banco é salvo mesmo assim (`if: always()`), para não perder o que já foi lido |
| O GitHub desativa agendamentos de repositório parado (60 dias) | Cada coleta gera um commit na branch `dados`, o que conta como atividade |
| O GitHub inteiro deixa de executar | healthchecks.io avisa quando nenhum aviso chega em 1 dia |

Não existe como recuperar depois o preço de um dia perdido, porque a Amazon não publica o
histórico. O que o sistema garante é tentar até 5 vezes por dia e avisar quando o dia
fechar sem dado. Para ver os buracos:

```bash
git fetch origin dados && git show origin/dados:precos.db > data/precos.db
python -m comparador lacunas        # dias sem coleta completa
python -m comparador status
```

O dia é contado no horário de Brasília. Para forçar uma coleta extra no mesmo dia, use
*Run workflow* com "forcar" marcado.

## Varredura de uma categoria inteira (HQs, mangás e graphic novels)

Para acompanhar uma categoria inteira (mais de 30 mil itens), e não só a sua lista, o
comando `varrer` lê as páginas de busca da Amazon, que trazem ~16 livros com preço por
requisição. Isso é ~16x mais barato que consultar livro por livro.

```bash
python -m comparador varrer --minutos 60     # banco em data/catalogo.db
python -m comparador catalogo                # cobertura: itens, fatias atrasadas, execuções
```

O workflow `.github/workflows/varredura.yml` roda isso todo dia por 90 minutos e guarda o
banco como arquivo na release `catalogo` do repositório. Medido: ~10 s por página, ~6
páginas e ~95 preços por minuto, sem bloqueios. A categoria inteira leva alguns dias e
depois é revisitada em rodízio. Para baixar o banco: *Releases → catalogo*, arquivo mais
recente, e `gunzip`.

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
| Bloqueio | Repete a mesma página depois de uma pausa maior; para depois de 3 falhas seguidas |
| Histórico gigante (milhões de linhas por mês) | O histórico guarda intervalos ("R$ X de tal dia a tal dia"): só cresce quando o preço muda. Mais de 10 dias sem ver o item abre um intervalo novo, para o buraco ficar visível |
| Banco publicado vazio ou corrompido por um erro | `scripts/verificar_banco.py` recusa banco corrompido ou com menos linhas que o anterior. Cada execução publica uma cópia nova com data e só depois apaga as antigas (mantém 14) |
| Fatia esquecida | `catalogo` sai com erro (e o GitHub avisa por e-mail) se alguma fatia ficar mais de 8 dias sem visita |

**Limites que continuam existindo:**
- Itens sem preço (indisponíveis) não aparecem na busca, então não entram no catálogo.
- Se o preço muda no meio de uma passada, o item pode mudar de fatia e ser visto duas
  vezes ou nenhuma naquela passada; aparece na seguinte.
- O preço de capa só aparece na busca quando há desconto. Sem desconto, fica vazio.
- Os termos de uso do GitHub Actions dizem que ele serve para o software do próprio
  repositório; uma varredura diária longa pode ser considerada uso indevido. Se isso
  preocupar, o mesmo comando roda em qualquer máquina sempre ligada (`cron`).
- Os termos da Amazon proíbem robôs. Quanto mais volume, maior o risco de bloqueio.

## Banco (`data/precos.db`)

| Tabela | Conteúdo |
|---|---|
| `livros` | Dados fixos: ASIN, título, autor, URL |
| `precos` | Uma linha por tentativa: data, fonte, `status`, preço, preço de capa, vendedor, estoque, condição |
| `coletas` | Uma linha por execução: quantos itens tentados, quantos deram certo, avisos |
| `eventos` | Datas das promoções (edite `eventos.csv` e rode `init` de novo) |

Os valores ficam em **centavos** e as datas em UTC. Para gráficos, use só `status = 'ok'`.

## Erros previstos e como são tratados

| Situação | O que acontece |
|---|---|
| Lista privada | Aviso pedindo para torná-la Pública ou Compartilhada. Os ASINs de `livros.txt` continuam sendo coletados |
| Link curto (amzn.to) | O redirecionamento é seguido para descobrir o ID da lista |
| Item sem oferta (`-Infinity`) | Gravado como `indisponivel` |
| "Ideias" e itens sem produto na lista | Ignorados |
| Paginação repetida ou infinita | Para ao repetir uma página ou ao chegar a 100 páginas |
| Captcha, ou erro 500/503 da Amazon | `bloqueado`. Espera 90 s a mais antes da próxima requisição e encerra após 3 bloqueios seguidos. Não tenta resolver captcha |
| Livro sem oferta principal | Usa a primeira oferta **nova** da lista e anota isso em `detalhe` |
| Layout mudou | `erro_parse` ou `sem_preco`, com o HTML bruto salvo em `data/html/AAAA-MM-DD/` para ajustar os seletores |
| Cliente HTTP reconhecido como robô (503) | O padrão é o navegador real (veja acima). Sem Playwright, usa o `curl` e, por último, o `requests` com cabeçalhos mínimos |
| Navegador não encontrado | Tenta Chrome, Edge e o Chromium do Playwright, nessa ordem. Se nenhum abrir, avisa e usa o `curl` |
| 503 intermitente na lista de desejos | Até 3 tentativas por página, com espera de 90 s e depois 180 s |
| Página do meio da lista falha de vez | Os itens já lidos são gravados e a coleta registra o aviso "lista incompleta" |
| Aviso oculto "Algo deu errado" na página da lista | Não conta como bloqueio. A página de erro é reconhecida pelo `<title>` |

## Avisos

- O parser da lista de ofertas e o leitor da lista de desejos foram validados com
  respostas reais (em `tests/fixtures/`) e com uma coleta completa de 82 itens em 9 páginas.
  Na primeira coleta, confira se `lista de desejos: N itens` bate com a sua lista.
- Ler as páginas da Amazon por script vai contra os termos de uso dela. O coletor faz o
  mínimo de requisições, com pausas, e para quando é bloqueado.
- `data/` (banco e HTML) não vai para o git.
