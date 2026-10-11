# Comparador de preços de livros (Amazon Brasil)

Coleta o preço dos livros que você escolher, uma vez por dia, e guarda o histórico
num banco SQLite local. O objetivo é saber se uma oferta de Black Friday ou Dia do
Consumidor é boa de verdade, comparando com o preço praticado no resto do ano (e
não só com o preço de capa).

## Uso

```bash
pip install -r requirements.txt
python -m comparador init            # cria data/precos.db e importa eventos.csv
# edite livros.txt: um ASIN (ISBN-10) ou link por linha
python -m comparador coletar         # uma coleta (6 a 14 s de pausa entre livros)
python -m comparador status          # últimas coletas e último preço de cada livro
python -m unittest discover -s tests # testes
```

Para rodar todo dia, agende o comando `coletar` no `cron` (Linux/Mac) ou no
Agendador de Tarefas (Windows), a partir da pasta do projeto, com o computador ligado.
Exemplo de cron, todo dia às 9h: `0 9 * * * cd /caminho/comparador-amazon && python3 -m comparador coletar`

## Banco (`data/precos.db`)

| Tabela | Conteúdo |
|---|---|
| `livros` | Dados fixos: ASIN, título, autor, URL |
| `precos` | Uma linha por tentativa: data, `status`, preço, preço de capa, vendedor, estoque, condição |
| `coletas` | Uma linha por execução: quantos livros tentados, quantos deram certo, por que parou |
| `eventos` | Datas das promoções (edite `eventos.csv` e rode `init` de novo) |

Valores em **centavos**. Datas em UTC. Para gráficos, use só `status = 'ok'`; as demais
linhas explicam os buracos (bloqueio, indisponível, erro). Exemplo, menor preço e mediana
aproximada por livro:

```sql
SELECT asin, MIN(preco_centavos)/100.0 AS menor, COUNT(*) AS coletas
FROM precos WHERE status = 'ok' GROUP BY asin;
```

## Avisos importantes

- **Os seletores do parser (`comparador/parser.py`) não foram testados contra páginas
  reais.** Os testes usam HTML sintético. Na primeira coleta, confira o `status`; se vier
  `sem_preco` ou `erro_parse`, o HTML bruto fica em `data/html/AAAA-MM-DD/` (gzip) para
  ajustar os seletores.
- Ler as páginas da Amazon por script vai contra os termos de uso dela. O coletor reduz o
  risco: lista pequena, uma visita por livro por dia, pausas aleatórias, sem retentativas,
  e **para sozinho depois de 3 bloqueios seguidos**. Não tenta burlar captcha nem trocar
  de IP. Se for bloqueado, espere e reduza a lista.
- `data/` (banco e HTML) não vai para o git.
