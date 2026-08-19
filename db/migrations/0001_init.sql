-- Fase 1 — datamodel.
--
-- Eén op één overgenomen uit het SQLAlchemy-model van de Python-applicatie,
-- zodat de bestaande SQLite-data zonder vertaalslag geïmporteerd kan worden.
-- Tabel- en kolomnamen blijven daarom exact gelijk aan de oude applicatie.
--
-- Datums die in de oude applicatie als tekst werden opgeslagen (ISO
-- YYYY-MM-DD) blijven TEXT; kolommen die al een echte datum waren worden DATE.

BEGIN;

-- ── Toegang ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS users (
  id              SERIAL PRIMARY KEY,
  username        TEXT    NOT NULL UNIQUE,
  hashed_password TEXT    NOT NULL,
  email           TEXT    UNIQUE,
  is_admin        BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
  id         SERIAL      PRIMARY KEY,
  user_id    INTEGER     NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  token      TEXT        NOT NULL UNIQUE,
  expires_at TIMESTAMPTZ NOT NULL,
  used       BOOLEAN     NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_reset_tokens_user ON password_reset_tokens (user_id);

-- ── Stamdata ───────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS eenheden (
  id              SERIAL  PRIMARY KEY,
  naam            TEXT    NOT NULL,
  etiket_per_stuk BOOLEAN NOT NULL DEFAULT FALSE,
  actief          BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS products (
  id         SERIAL  PRIMARY KEY,
  name       TEXT    NOT NULL,
  unit       TEXT,
  eenheid_id INTEGER REFERENCES eenheden (id),
  active     BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_products_active ON products (active);

CREATE TABLE IF NOT EXISTS locations (
  id     SERIAL  PRIMARY KEY,
  name   TEXT    NOT NULL,
  active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS conserveringsmethoden (
  id     SERIAL  PRIMARY KEY,
  naam   TEXT    NOT NULL,
  actief BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS ontvangers (
  id     SERIAL  PRIMARY KEY,
  naam   TEXT    NOT NULL,
  actief BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS product_houdbaarheid (
  id                      SERIAL  PRIMARY KEY,
  product_id              INTEGER NOT NULL REFERENCES products (id) ON DELETE CASCADE,
  conserveringsmethode_id INTEGER REFERENCES conserveringsmethoden (id),
  houdbaarheid_maanden    INTEGER NOT NULL,
  actief                  BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_houdbaarheid_product
  ON product_houdbaarheid (product_id, conserveringsmethode_id);

-- ── Oogst en uitgifte ──────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS harvest_entries (
  id                      SERIAL           PRIMARY KEY,
  product_id              INTEGER          NOT NULL REFERENCES products (id),
  location_id             INTEGER          NOT NULL REFERENCES locations (id),
  conserveringsmethode_id INTEGER          REFERENCES conserveringsmethoden (id),
  quantity                DOUBLE PRECISION NOT NULL,
  date                    TEXT             NOT NULL,
  entered_by              TEXT             NOT NULL,
  note                    TEXT,
  created_at              TIMESTAMPTZ      NOT NULL DEFAULT now(),
  houdbaar_tot            DATE,
  volgnummer              INTEGER,
  gewijzigd_door          TEXT,
  gewijzigd_op            TIMESTAMPTZ,
  uitgegeven              BOOLEAN          NOT NULL DEFAULT FALSE,
  uitgegeven_op           TIMESTAMPTZ,
  uitgegeven_aan          TEXT
);

CREATE INDEX IF NOT EXISTS idx_harvest_product   ON harvest_entries (product_id);
CREATE INDEX IF NOT EXISTS idx_harvest_location  ON harvest_entries (location_id);
CREATE INDEX IF NOT EXISTS idx_harvest_open      ON harvest_entries (uitgegeven);
CREATE INDEX IF NOT EXISTS idx_harvest_houdbaar  ON harvest_entries (houdbaar_tot);

CREATE TABLE IF NOT EXISTS uitgiftes (
  id               SERIAL           PRIMARY KEY,
  harvest_entry_id INTEGER          REFERENCES harvest_entries (id) ON DELETE SET NULL,
  product_id       INTEGER          NOT NULL REFERENCES products (id),
  location_id      INTEGER          NOT NULL REFERENCES locations (id),
  quantity         DOUBLE PRECISION NOT NULL,
  ontvanger        TEXT             NOT NULL,
  date             TEXT             NOT NULL,
  entered_by       TEXT             NOT NULL,
  note             TEXT,
  created_at       TIMESTAMPTZ      NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_uitgiftes_product ON uitgiftes (product_id);
CREATE INDEX IF NOT EXISTS idx_uitgiftes_date    ON uitgiftes (date);

-- ── Winkelvoorraad en containers ───────────────────────────────────────────

CREATE TABLE IF NOT EXISTS shop_items (
  id                  SERIAL           PRIMARY KEY,
  barcode             TEXT,
  name                TEXT             NOT NULL,
  brand               TEXT,
  quantity_per_unit   DOUBLE PRECISION DEFAULT 1,
  unit                TEXT             DEFAULT 'stuks',
  image_url           TEXT,
  owner               TEXT             NOT NULL,
  stock               INTEGER          DEFAULT 0,
  minimum_stock       INTEGER,
  houdbaar_tot        DATE,
  date_added          DATE             DEFAULT CURRENT_DATE,
  entered_by          TEXT             NOT NULL,
  categorie           TEXT,
  is_deelbaar         BOOLEAN          NOT NULL DEFAULT FALSE,
  opslag_in_container BOOLEAN          NOT NULL DEFAULT FALSE,
  niveau_stap         TEXT             DEFAULT 'vol',
  niveau_hoeveelheid  DOUBLE PRECISION,
  container_id        INTEGER,
  status              TEXT             DEFAULT 'voorraad'
);

CREATE INDEX IF NOT EXISTS idx_shop_items_owner   ON shop_items (owner);
CREATE INDEX IF NOT EXISTS idx_shop_items_barcode ON shop_items (barcode);
CREATE INDEX IF NOT EXISTS idx_shop_items_status  ON shop_items (status);

CREATE TABLE IF NOT EXISTS containers (
  id                  SERIAL  PRIMARY KEY,
  qr_code             TEXT    NOT NULL UNIQUE,
  label               TEXT    NOT NULL,
  product_name        TEXT    NOT NULL,
  current_expiry_date DATE,
  source_item_id      INTEGER REFERENCES shop_items (id) ON DELETE SET NULL,
  fill_level          INTEGER,
  notes               TEXT,
  owner               TEXT    NOT NULL
);

-- container_id op shop_items verwijst naar containers.id. In de oude
-- applicatie stond hier bewust geen constraint vanwege de kringverwijzing;
-- als NOT VALID constraint kan hij hier wel mee zonder de import te blokkeren.
ALTER TABLE shop_items
  DROP CONSTRAINT IF EXISTS shop_items_container_fk;
ALTER TABLE shop_items
  ADD CONSTRAINT shop_items_container_fk
  FOREIGN KEY (container_id) REFERENCES containers (id) ON DELETE SET NULL
  NOT VALID;

CREATE TABLE IF NOT EXISTS niveau_logs (
  id                 SERIAL           PRIMARY KEY,
  shop_item_id       INTEGER          NOT NULL REFERENCES shop_items (id) ON DELETE CASCADE,
  timestamp          TIMESTAMPTZ      DEFAULT now(),
  niveau_stap        TEXT             NOT NULL,
  niveau_hoeveelheid DOUBLE PRECISION,
  gewijzigd_door     TEXT             NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_niveau_logs_item ON niveau_logs (shop_item_id);

CREATE TABLE IF NOT EXISTS shop_uitgiftes (
  id           SERIAL  PRIMARY KEY,
  shop_item_id INTEGER NOT NULL REFERENCES shop_items (id) ON DELETE CASCADE,
  quantity     INTEGER NOT NULL,
  date         DATE    DEFAULT CURRENT_DATE,
  entered_by   TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_shop_uitgiftes_item ON shop_uitgiftes (shop_item_id);

-- ── Overig ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS shared_lists (
  id         SERIAL      PRIMARY KEY,
  token      TEXT        NOT NULL UNIQUE,
  owner      TEXT        NOT NULL,
  list_data  TEXT        NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS product_cache (
  id        SERIAL           PRIMARY KEY,
  barcode   TEXT             NOT NULL UNIQUE,
  name      TEXT,
  brand     TEXT,
  quantity  DOUBLE PRECISION,
  unit      TEXT,
  image_url TEXT,
  cached_at TIMESTAMPTZ      DEFAULT now()
);

COMMIT;
