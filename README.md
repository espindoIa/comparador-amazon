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
  respostas reais (em `tests/fixtures/`). A paginação real (página 2 em diante) ainda não
  foi confirmada. Na primeira coleta, confira se `lista de desejos: N itens` bate com a
  sua lista.
- Ler as páginas da Amazon por script vai contra os termos de uso dela. O coletor faz o
  mínimo de requisições, com pausas, e para quando é bloqueado.
- `data/` (banco e HTML) não vai para o git.
