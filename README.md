# Comparador de preços de livros (Amazon Brasil)

Lê, todo dia, os preços de milhares de livros da Amazon Brasil (os ~20 mil mais vendidos e a
categoria inteira de HQs e mangás) e guarda o histórico. O objetivo é saber se uma oferta de
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

## Os ~20 mil livros mais vendidos, todo dia

```bash
python -m comparador --db data/vendidos.db varrer --vendidos
python -m comparador --db data/vendidos.db catalogo --vendidos
```

Lê, todo dia, os mais vendidos de cada um dos 29 gêneros de Livros (Literatura, Romance,
Autoajuda, HQs e mangás, Infantil...) e do ranking geral de Livros, com o preço de cada
formato (capa comum, capa dura, Kindle, audiolivro) e o preço de capa quando há desconto.
No workflow `varredura.yml` é a linha `vendidos` da matrix, num servidor próprio; o
banco vai para a release `catalogo` como `catalogo-vendidos-<data>.db.gz`.

Por que por gênero (medido em out/2026): na ordem "Mais vendidos", a Amazon só mostra
**75 páginas (1.200 livros) por consulta**, embora a paginação anuncie 400, e as páginas de
busca não mostram a posição de vendas de cada livro. Não existe, então, como ler um
ranking geral de 20 mil. Somando os 1.200 primeiros de cada gênero chega-se a até ~35 mil
posições (30 consultas x 75 páginas = ~2.250 páginas, ~1h50 por dia); como um livro pode
estar em mais de um gênero, o número de livros distintos fica abaixo disso. Os gêneros
estão em `GENEROS`, em `comparador/varredura.py`.

## Varredura diária de categorias inteiras (HQs, mangás e graphic novels)

Para acompanhar uma categoria inteira, e não só a sua lista, o comando `varrer` lê
**todos os dias** todas as páginas de busca da categoria. Cada página traz ~16 livros com
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

O workflow `.github/workflows/varredura.yml` roda 4 vezes por dia. A primeira normalmente
completa o dia; as outras só continuam o que faltou (o progresso é salvo a cada página) ou
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
| Bloqueio | Repete a mesma página depois de uma pausa maior, fica 3x mais lento até o fim da execução e para depois de 3 falhas seguidas; a próxima execução do dia continua |
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

- Ler as páginas da Amazon por script vai contra os termos de uso dela. A varredura usa pausas
  entre as requisições e fica mais lenta ou para quando é bloqueada.
- `data/` (banco e HTML) não vai para o git.

## O app: busca por título e lista de desejos

Um site estático (sem servidor, grátis no GitHub Pages) com:

- **Busca por título, autor ou ASIN/ISBN-10,** ignorando acentos e a ordem das palavras. Cada formato
  (capa comum, capa dura, Kindle...) aparece como um resultado, com o preço mais recente.
- **Página de cada livro** com o histórico de preço, os números e os botões de zoom e de dados extras
  (veja "Histórico de preço por livro").
- **Minha lista:** o botão "Adicionar" em qualquer livro o põe na lista. Ela mostra o preço de hoje, a
  diferença para o preço mais comum dos últimos 90 dias e o mais barato do período, e pode ser
  ordenada por título, preço ou diferença. **A lista fica só no navegador de quem a cria** (não há
  conta nem servidor). Para levá-la a outro aparelho, use "Levar a lista para outro aparelho": copie
  num e cole no outro. Só entram livros que o catálogo acompanha (os mais vendidos e HQs/mangás).

```bash
python -m comparador site data/catalogo-vendidos.db data/catalogo-7842710011.db --saida site
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
