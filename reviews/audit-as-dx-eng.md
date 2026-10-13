# DX Audit: CLI `comparador` e scripts de apoio (auditoria do repositório, sem plano)

**Perspective**: Developer Experience Engineer
**Date**: 2026-10-13
**Plan**: nenhum plano foi indicado. Auditei o estado atual de `main` (f151df8): `python -m comparador {varrer,catalogo,grafico,site}`, os 8 scripts em `scripts/`, o README e as mensagens dos workflows.

## Plan Summary
Quem usa isto é uma pessoa que mantém o repositório e roda a coleta à mão ou lê os logs do GitHub Actions quando algo falha. O que mais pesa no dia a dia é o `varrer` (muitas opções, estado escondido no banco) e os scripts de conferência que decidem se uma publicação sai ou não.

## Como foi feito
- Li `__main__.py`, os 8 scripts, `rede.py`, `db.py`, `relatorio.py`, `cliente_http.py` (trechos), o README, o `roadmap.md` e os cabeçalhos dos workflows.
- **Executei** os comandos com entradas erradas, usando bancos descartáveis na pasta temporária. O repositório não foi alterado (`git status` limpo; só este relatório é novo).
- **Não executei**: a suíte de testes, o `site` com banco real e nenhum workflow. Tudo marcado "(lido no código)" abaixo não foi reproduzido.
- **Efeito colateral dos meus testes**: uma das minhas chamadas de `varrer` (`--ritmo -3 --max-paginas 1 --cliente requests`) pediu uma página à Amazon a partir deste sandbox e voltou bloqueada (captcha). A chamada seguinte (`--ritmo-max 1 --ritmo 50`, mesma forma) não terminou em ~2 min e a encerrei sem saber o motivo; é provável que também tenha tentado a rede. Só bancos descartáveis foram tocados. Isto é também um achado (C2).

## Files Reviewed
| File | DX Role | Risk |
|------|---------|------|
| `comparador/__main__.py` | Porta de entrada de todo o uso manual | Médio |
| `comparador/cliente_http.py` | Escolha do cliente HTTP e mensagem de "sem navegador" | Médio |
| `comparador/db.py` | Cria o banco no primeiro acesso | Médio |
| `comparador/relatorio.py` | `grafico`, leitura de `eventos.csv` | Baixo |
| `scripts/verificar_banco.py`, `verificar_precos.py`, `conferir_site.py` | Travas de publicação; o log delas é o que o mantenedor lê quando a publicação é recusada | Alto |
| `scripts/espera.py`, `proximo_ciclo.py`, `vigia.py` | Cola do anel de execuções | Médio |
| `scripts/comparar_bancos.py`, `podar_copias.py`, `simular_precos.py` | Ferramentas avulsas | Baixo |
| `README.md` | Documentação de uso | Médio |

## Verdict: APPROVE WITH CHANGES
As mensagens de domínio são, em geral, boas: dizem o que houve e o que fazer (`em pausa até …; Para ler assim mesmo: --ignorar-pausa`, `repita com o ASIN exato`, `para publicar assim mesmo, rode o workflow com 'forcar'`). Os problemas estão nas bordas: entradas que nunca passaram por validação, scripts de CI que despejam traceback sem dizer qual arquivo, e a falta de qualquer modo que não toque a Amazon.

## Critical Issues (Must Fix)
| # | Issue | Impact on Developer | Fix |
|---|-------|-------------------|-----|
| C1 | **Scripts de trava não dizem qual arquivo falhou.** `verificar_banco.py`, `verificar_precos.py` e `proximo_ciclo.py` com banco ausente terminam em `sqlite3.OperationalError: unable to open database file`, sem o caminho. `verificar_banco.py` trata `DatabaseError`, mas o erro de abertura ocorre antes, fora do `try`. Em `verificar_precos.py` há dois bancos e nada indica qual. (Reproduzido.) | No log de um workflow, quem investiga uma publicação recusada vê um traceback e tem de adivinhar se faltou o banco novo ou o anterior. | Abrir os bancos por uma função comum que faz `sys.exit(f"{caminho}: não consegui abrir o banco ({e})")`. `verificar_banco.py` já tem o padrão. |
| C2 | **Não há como validar as opções de `varrer` sem uma chamada de rede.** Não existe `--dry-run` nem cliente falso pela linha de comando, e a validação de valores é tardia: `--ritmo -3` só foi notado depois de a Amazon responder (reproduzido, resposta bloqueada). `--max-paginas`, descrito como "para testes", ainda faz requisições reais, grava uma linha em `execucoes` (vi três no banco de teste) e dispara o recuo do ritmo. Em compensação, ele **não** guarda pausa nem ritmo aprendidos: o `executar` volta antes de `aprender_*` quando `--max-paginas` ou `--parar-na-falha` estão presentes (confirmado no código e no banco de teste, que ficou sem `ritmo_pausa_ate` depois do bloqueio). | Testar uma combinação de flags, ou um erro de digitação em um valor, custa uma requisição ao serviço que o README diz não permitir leitura automática, e quem esquece `--max-paginas` num teste grava a pausa de verdade. | `--dry-run` que valida as opções, imprime o plano (ritmo, ciclo, fatias) e sai antes de abrir a sessão, e validação de faixa dos valores no `argparse` (ver R4). |
| C3 | **`--cliente auto` rebaixa em silêncio para um cliente que o README diz ser bloqueado.** Sem o módulo `playwright`, `nova_sessao` cai em `curl`/`requests` sem nenhuma linha de aviso (neste sandbox, `playwright` não está instalado). Com o módulo mas sem navegador, imprime `aviso: navegador indisponível (...)` na saída normal. O README diz que `requests` "respondia com captcha ou erro 503". Numa execução comum (sem `--max-paginas`, `--parar-na-falha` ou `--ciclo-horas`), um bloqueio grava a pausa de 3 h, dobrando até 24 h (`aprender_ciclo`). (Lido no código; o bloqueio com `requests` foi visto, mas a pausa gravada por ele não, porque meus testes usaram `--max-paginas`.) | Quem segue o README em máquina sem Chrome pode perder horas de pausa por uma causa que a saída nunca mencionou. | Em `auto`, avisar em stderr, em destaque, qual cliente foi escolhido e por quê, e recusar por padrão o rebaixamento para `requests` sem `--cliente requests` explícito. |

## Recommendations
| # | Issue | Why | Fix |
|---|-------|-----|-----|
| R1 | **Erro de digitação no `--db` cria um banco vazio e responde "0 itens" com exit 0.** `db.conectar` faz `mkdir` e cria o arquivo. `catalogo --db tipo.db` criou `tipo.db` (reproduzido). | Um caminho errado parece um catálogo vazio, e o alerta `--exigir-ontem` sairia com resultado enganoso. | Em `catalogo`, `grafico` e `site`, exigir que o arquivo exista: `banco não encontrado: <caminho>`. Criar só no `varrer`. |
| R2 | **`--db` só vale antes do subcomando.** `catalogo --db y.db` dá `unrecognized arguments: --db y.db` (reproduzido), sem dica. | Todo mundo erra isso uma vez, e o `--db` é a opção mais usada. | Aceitar `--db` também depois do subcomando (um `parents=[...]` compartilhado), ou incluir a dica na mensagem. |
| R3 | **O padrão não bate com o README.** `--db` padrão é `data/catalogo.db` e `--no` padrão é HQs/Mangás; todo exemplo do README usa `data/vendidos.db` e `--vendidos`. (Lido no código.) | Rodar `catalogo` sem `--vendidos` num banco de vendidos mostra a categoria errada, sem aviso. | Tornar `--vendidos` o padrão (ou único) e mover HQs/Mangás para uma opção explícita; alinhar o `--db` padrão. |
| R4 | **Valores sem validação.** `--ritmo -3` é aceito e impresso como `começa em -3 páginas/min`; `--minutos -5` roda zero páginas e sai 0 (ambos reproduzidos). | Um valor absurdo vira comportamento estranho, não erro. | `type=` com checagem de faixa (positivo; `--ritmo` ≤ `--ritmo-max`). |
| R5 | **Flags condicionais ignoradas sem aviso.** `--faixas`, `--generos` e `--particao` dizem "com --vendidos" na ajuda, mas sem ele não fazem efeito, e nada avisa: `--generos`/`--particao` só são lidos dentro de `if args.vendidos`, e `--faixas` chega a `executar`, mas só é usado em `semear_vendidos`, que roda apenas no caminho `vendidos`. (Lido no código; não executei esse caso.) | Quem esquece `--vendidos` lê a categoria errada achando que filtrou. | `p.error("--generos exige --vendidos")`. |
| R6 | **`espera.py` não usa `argparse`.** Sem argumento: `IndexError`; com `amanha`: `ValueError: Invalid isoformat string` (reproduzido). Um instante sem fuso também não é tratado (lido no código). | É o script que dorme horas no GitHub; entrada ruim só aparece depois do disparo. | `argparse` com `type=` que exija ISO com fuso e mensagem de exemplo. |
| R7 | **`site` com banco inexistente despeja traceback** (reproduzido). | O mesmo comando dá mensagem curta em outros erros (`grafico` diz `nenhum livro encontrado…`), então o traceback destoa. | Mesma checagem de R1. |
| R8 | **Caminhos relativos ao diretório atual.** `eventos.csv` ausente vira lista vazia em silêncio (`ler_eventos`), e o HTML bruto sempre vai para `./data/html`, mesmo com `--db` em outro lugar (apareceu `data/` ao lado de `z.db`). | Rodar de outra pasta tira as datas de promoção do `site`/`grafico` sem avisar, e espalha lixo. | Avisar quando `--eventos` foi dado e não existe; derivar a pasta de HTML do `--db` ou oferecer `--pasta-html`. |
| R9 | **`varrer --help` é um muro.** Cerca de 15 opções, várias de calibragem interna (`--subir-a-cada`, `--teto-auto-max`), misturadas com as de uso comum, sem exemplos. A ajuda cita uma constante do código ("ver PARTICOES_VENDIDOS"). A descrição do comando principal é o docstring `python -m comparador {varrer,catalogo,grafico,site}.` | Quem vem do `--help` não distingue "o que eu uso" de "o que o mantenedor calibrou". | `add_argument_group("uso comum")` / `("calibragem")`, um `epilog` com 3 exemplos, e tirar a referência a `PARTICOES_VENDIDOS`. |
| R10 | **Sem controle de verbosidade nem saída para máquina.** `varrer` e `catalogo` misturam texto humano e números; os workflows leem `proximo_ciclo.py` por linhas posicionais (instante na 1ª, motivo na 2ª). | Frágil para quem encadeia; qualquer linha extra quebra o consumidor. | `--json` em `catalogo`; em `proximo_ciclo`, `--formato json` ou chaves nomeadas. |

## Nice-to-Haves
| # | Suggestion | Rationale |
|---|------------|-----------|
| N1 | `--version` e um ponto de entrada `comparador` (via `pyproject.toml`) | `python -m comparador` funciona, mas é longo para uso diário. |
| N2 | Ao terminar o `varrer`, uma linha com o próximo passo ("`catalogo --vendidos` mostra o progresso") | Fecha o ciclo do "primeiro uso". |
| N3 | `argparse` em `comparar_bancos.py` (hoje `sys.exit(__doc__)` com exit 1 e sem `--help`) | Consistência com os outros scripts. |
| N4 | Completar `catalogo` com `--exigir-*` em um único `--alertas` que liste todos os problemas, em vez de parar no primeiro | Hoje o primeiro `SystemExit` esconde os seguintes. |
| N5 | README: seção "Quando algo dá errado" com as 4 mensagens mais comuns (pausa, bloqueio, trava de preços, trava do site) e o comando de cada saída | O texto atual explica o *porquê* do desenho em detalhe, mas a ação fica espalhada. |

## Error Message Audit
| Error Scenario | Current Message | What Developer Needs | Suggested Message |
|---------------|----------------|---------------------|-------------------|
| `--db` com erro de digitação em `catalogo` | `0 itens no catálogo; …` e exit 0 (reproduzido) | Saber que o banco não existe | `banco não encontrado: tipo.db (o varrer cria o arquivo; catalogo não)` |
| `--db` depois do subcomando | `unrecognized arguments: --db y.db` | Saber que a opção vai antes | `--db vale antes do subcomando: comparador --db y.db catalogo` |
| `site` com banco ausente | Traceback `sqlite3.OperationalError: unable to open database file` | Qual arquivo | `banco não encontrado: naoexiste.db` |
| `verificar_banco`/`verificar_precos`/`proximo_ciclo` com banco ausente | Mesmo traceback, sem caminho | Qual arquivo, qual papel (novo/anterior) | `anterior: banco não encontrado: <caminho>` |
| `espera.py` sem argumento | `IndexError: list index out of range` | Uso e formato | `uso: espera.py INSTANTE_UTC (ex.: 2026-10-13T18:00:00+00:00)` |
| `espera.py amanha` | `ValueError: Invalid isoformat string: 'amanha'` | Formato esperado | `instante inválido: 'amanha'; use ISO 8601 com fuso` |
| `--ritmo -3` | Aceito; imprime `começa em -3 páginas/min` | Recusa | `--ritmo deve ser maior que 0` |
| `--minutos -5` | Aceito; zero páginas, exit 0 | Recusa | `--minutos deve ser maior que 0` |
| `--generos 999` | `opção inválida: gênero desconhecido: 999` (bom) | Quais valem | acrescentar `(use --help ou os nós de PARTICOES_VENDIDOS)` com a lista |
| `--faixas 0,abc` | `opção inválida: could not convert string to float: 'abc'` | Qual valor, em português | `--faixas: 'abc' não é um número; exemplo: 0,20,30` |
| `varrer` durante pausa | `em pausa até …; nada a fazer. Para ler assim mesmo: --ignorar-pausa` (bom) | — | manter |
| Sem navegador (`--cliente navegador`) | `não consegui abrir o navegador: nenhum navegador encontrado. Instale o Chrome ou rode python -m playwright install chromium…` (bom) | — | manter; mostrar o mesmo em `auto` |
| `grafico` ambíguo | Lista os 15 primeiros e `N resultados; repita com o ASIN exato` (bom) | — | manter |
| `conferir_site` recusa | `recusado: … para publicar assim mesmo, rode o workflow com 'forcar'` (bom; o `site.yml` tem mesmo a entrada `forcar`) | — | manter |

## Developer Journey
- **Primeiro uso**: o README leva bem do `pip install` ao site local em cinco comandos, e a mensagem de "sem navegador" é boa. O atrito começa se não houver Chrome: o `auto` pode seguir com um cliente que será bloqueado (C3). Digitar o `--db` errado ou na posição errada (R1, R2) é a segunda pedra.
- **Uso diário**: o fluxo `varrer` → `catalogo` → `site` funciona, mas a ajuda do `varrer` é longa demais (R9), `catalogo` sem `--vendidos` olha a categoria errada (R3), e conferir uma combinação de opções exige uma chamada de rede (C2).
- **Uso avançado / CI**: aqui o custo é maior. Quando uma trava recusa uma publicação, o log precisa dizer qual arquivo e qual regra; hoje, em caso de arquivo ausente, só há traceback (C1). A saída por posição de linha em `proximo_ciclo.py` (R10) é uma dependência frágil entre script e workflow.

## Verdict Details
- Error Quality: CONCERNS (domínio bom; bordas e scripts de CI sem tratamento)
- Defaults & Config: CONCERNS (padrões não batem com o README; valores sem validação)
- Keyboard Experience: PASS (CLI sem interação; sem atalhos a avaliar)
- Discoverability: CONCERNS (`--help` do `varrer` sem grupos nem exemplos)
- Workflow Integration: CONCERNS (sem `--dry-run`, sem `--json`, saída posicional)

## Atualização: o que foi corrigido (PRs #30 e seguintes)

- **C1, C2 e C3** foram corrigidos no PR #30.
- **Sobre o C3:** a evidência contra o curl não vem do README, que só cita o `requests` ("captcha ou erro 503"), e sim do docstring de `comparador/cliente_http.py` (503 em todas as tentativas de paginação da lista). Por isso a correção feita foi mais ampla que a sugerida na tabela: o `--cliente auto` não cai nem no curl nem no `requests`; os dois só valem pedidos explicitamente.
