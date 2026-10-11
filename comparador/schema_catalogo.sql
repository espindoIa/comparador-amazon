-- Banco da varredura de categorias inteiras (separado do banco da lista de desejos).
-- Preços em CENTAVOS, datas em UTC ISO 8601.

-- Fatias: categoria + faixa de preço (centavos, inclusive). Cada fatia cabe em poucas
-- páginas de busca; fatias grandes demais são divididas automaticamente.
CREATE TABLE IF NOT EXISTS fatias (
    id                  INTEGER PRIMARY KEY,
    no                  TEXT NOT NULL,              -- nó da categoria na Amazon
    preco_min           INTEGER NOT NULL,
    preco_max           INTEGER NOT NULL,
    ativa               INTEGER NOT NULL DEFAULT 1, -- 0 = foi dividida
    paginas             INTEGER,                    -- última contagem de páginas
    total               INTEGER,                    -- "N resultados" da última visita
    proxima_pagina      INTEGER NOT NULL DEFAULT 1, -- progresso da passada atual
    passada_iniciada_em TEXT,
    ultima_passada      TEXT,                       -- fim da última passada completa
    criada_em           TEXT NOT NULL,
    UNIQUE (no, preco_min, preco_max)
);

-- Itens vistos (cada formato é um ASIN).
CREATE TABLE IF NOT EXISTS catalogo (
    asin           TEXT PRIMARY KEY,
    titulo         TEXT,
    formato        TEXT,
    no             TEXT,
    primeiro_visto TEXT NOT NULL,
    ultimo_visto   TEXT NOT NULL
);

-- Histórico por intervalos: uma linha por "período com o mesmo preço". Só cresce
-- quando o preço muda (ou depois de um buraco de observação), não a cada visita.
-- `ate` é a última vez em que esse preço foi visto.
CREATE TABLE IF NOT EXISTS historico (
    id                  INTEGER PRIMARY KEY,
    asin                TEXT NOT NULL REFERENCES catalogo(asin),
    preco_centavos      INTEGER NOT NULL,
    preco_capa_centavos INTEGER,
    desde               TEXT NOT NULL,
    ate                 TEXT NOT NULL,
    vezes               INTEGER NOT NULL DEFAULT 1   -- quantas observações confirmam
);
CREATE INDEX IF NOT EXISTS idx_historico_asin ON historico (asin, id);

-- Uma linha por execução, para auditoria e alertas.
CREATE TABLE IF NOT EXISTS execucoes (
    id            INTEGER PRIMARY KEY,
    iniciada_em   TEXT NOT NULL,
    finalizada_em TEXT,
    paginas       INTEGER NOT NULL DEFAULT 0,
    itens         INTEGER NOT NULL DEFAULT 0,
    bloqueios     INTEGER NOT NULL DEFAULT 0,
    erros         INTEGER NOT NULL DEFAULT 0,
    observacao    TEXT
);
