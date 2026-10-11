-- Esquema do banco de preços. Valores monetários ficam em CENTAVOS (inteiro)
-- para evitar erros de arredondamento de ponto flutuante. Datas em UTC, ISO 8601.

-- Dados fixos de cada item. Capa dura, brochura e Kindle têm ASINs diferentes
-- e são tratados como itens separados.
CREATE TABLE IF NOT EXISTS livros (
    asin       TEXT PRIMARY KEY,
    titulo     TEXT,
    autor      TEXT,
    url        TEXT NOT NULL,
    ativo      INTEGER NOT NULL DEFAULT 1,
    criado_em  TEXT NOT NULL
);

-- Uma linha por execução do coletor. Serve para separar "o livro estava
-- indisponível" de "o script falhou ou foi bloqueado".
CREATE TABLE IF NOT EXISTS coletas (
    id            INTEGER PRIMARY KEY,
    iniciada_em   TEXT NOT NULL,
    finalizada_em TEXT,
    tentados      INTEGER NOT NULL DEFAULT 0,
    sucesso       INTEGER NOT NULL DEFAULT 0,
    falhas        INTEGER NOT NULL DEFAULT 0,
    observacao    TEXT,
    -- 1 quando a lista de desejos foi lida inteira. Só coletas completas
    -- contam como "dia coberto" (ver `python -m comparador lacunas`).
    completa      INTEGER NOT NULL DEFAULT 0
);

-- Uma linha por tentativa de coleta de um livro (inclusive as que falharam,
-- com o motivo em `status`). Para gráficos, filtre status = 'ok'.
-- `fonte`: 'lista_desejos' (preço da lista, todo dia, barato) ou 'ofertas'
-- (lista de ofertas do produto: também preço de capa, vendedor e condição).
CREATE TABLE IF NOT EXISTS precos (
    id                  INTEGER PRIMARY KEY,
    asin                TEXT NOT NULL REFERENCES livros(asin),
    coleta_id           INTEGER NOT NULL REFERENCES coletas(id),
    coletado_em         TEXT NOT NULL,
    fonte               TEXT NOT NULL DEFAULT 'ofertas'
                        CHECK (fonte IN ('ofertas', 'lista_desejos')),
    status             TEXT NOT NULL CHECK (status IN (
                            'ok',           -- preço lido
                            'indisponivel', -- página lida, sem oferta/estoque
                            'sem_preco',    -- página lida, mas sem preço nem aviso de estoque (suspeito)
                            'bloqueado',    -- captcha / página de robô
                            'erro_http',    -- erro de rede ou status HTTP != 200
                            'erro_parse'    -- layout inesperado
                        )),
    preco_centavos      INTEGER,
    preco_capa_centavos INTEGER,   -- preço de capa / "de:" mostrado na página
    vendido_por         TEXT,      -- 'Amazon' ou o nome do vendedor
    em_estoque          INTEGER,   -- 1, 0 ou NULL se desconhecido
    condicao            TEXT,      -- 'novo' ou 'usado'
    html_arquivo        TEXT,      -- caminho do HTML bruto guardado, se houver
    detalhe             TEXT       -- mensagem de erro ou observação
);
CREATE INDEX IF NOT EXISTS idx_precos_asin_data ON precos (asin, coletado_em);

-- Datas das promoções, para marcar nos gráficos. Preenchida à mão (eventos.csv).
CREATE TABLE IF NOT EXISTS eventos (
    id     INTEGER PRIMARY KEY,
    nome   TEXT NOT NULL,
    inicio TEXT NOT NULL,  -- AAAA-MM-DD
    fim    TEXT NOT NULL,  -- AAAA-MM-DD
    UNIQUE (nome, inicio)
);
