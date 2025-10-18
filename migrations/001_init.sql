-- =========================================
-- 01_create_schema.sql
-- =========================================

-- 1. ENUM‑типы для полей со статическими значениями
--
CREATE TYPE order_status AS ENUM (
    'waiting',
    'pending_payment',
    'processing',
    'ready',
    'transferring',
    'finished',
    'cancelled'

    );

CREATE TYPE delivery_way AS ENUM (
    'pickup',
    'delivery'
    );

CREATE TYPE finish_status AS ENUM (
    'delivered',
    'in_process',
    'canceled'
    );

CREATE TYPE payment_status AS ENUM (
    'pending',
    'succeeded',
    'canceled'
    );


--
-- 2. Таблица user_info
--
CREATE TABLE user_info
(
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tg_user_id BIGINT NOT NULL UNIQUE
);

--
-- 3. Таблица buyer_info (1:1 по tg_user_id → user_info.tg_user_id)
--
CREATE TABLE buyer_info
(
    user_id      BIGINT PRIMARY KEY REFERENCES user_info (id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    name_surname VARCHAR(50) NOT NULL,
    tel_num      VARCHAR(15) NOT NULL,
    tg_username  VARCHAR(32),
    address      TEXT,
    porch        VARCHAR(10),
    floor        VARCHAR(10),
    apartment    VARCHAR(10),
    bonus_num    INT DEFAULT 0
);

--
-- 4. Таблица product_position
--
CREATE TABLE product_position
(
    id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title     VARCHAR(50)   NOT NULL,
    price     INT           NOT NULL CHECK (price >= 0),
    quantity  INT           NOT NULL CHECK (quantity >= 0),
    weight_kg NUMERIC(7, 3) NOT NULL DEFAULT 0.1,
    length_m  NUMERIC(7, 3) NOT NULL DEFAULT 0.1,
    width_m   NUMERIC(7, 3) NOT NULL DEFAULT 0.1,
    height_m  NUMERIC(7, 3) NOT NULL DEFAULT 0.1,
    image_path TEXT
);

--
-- 5. Таблица buyer_orders
--    Каждому заказу привязан пользователь и позиция товара
--
CREATE TABLE buyer_orders
(
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    buyer_id          BIGINT       NOT NULL REFERENCES user_info (id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    status            order_status NOT NULL DEFAULT 'waiting',
    comment           TEXT,
    delivery_way      delivery_way NOT NULL DEFAULT 'pickup',
    delivery_address  TEXT,
    used_bonus        INT          NOT NULL DEFAULT 0,
    registration_date DATE         NOT NULL DEFAULT CURRENT_DATE,
    finished_at       DATE,         -- итоговая дата (доставки/отмены)
    delivery_date     DATE,         -- плановая дата доставки (optional)
    delivery_cost     NUMERIC(10, 2)        DEFAULT 0.00,
    yandex_claim_id   VARCHAR(100), -- ID заявки
    payment_info      JSONB,
    payment_date      TIMESTAMP WITH TIME ZONE,
    created_at        TIMESTAMP WITH TIME ZONE DEFAULT now()
);

-- Корзина - несколько позиций в одном заказе
CREATE TABLE order_items
(
    order_id    BIGINT NOT NULL REFERENCES buyer_orders (id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    position_id BIGINT NOT NULL REFERENCES product_position (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    qty         INT    NOT NULL CHECK (qty > 0),

    PRIMARY KEY (order_id, position_id)
);

CREATE INDEX idx_buyer_orders_buyer ON buyer_orders (buyer_id);
CREATE INDEX idx_buyer_orders_status ON buyer_orders (status);
CREATE INDEX idx_product_position_title ON product_position (title);
--
-- 6. Таблица payments
--    Связь оплаты с пользователем и заказом
--
CREATE TABLE payments
(
    id          SERIAL PRIMARY KEY,
    tg_user_id  BIGINT              NOT NULL,
    amount      NUMERIC(10, 2)      NOT NULL CHECK (amount >= 0),
    yookassa_id VARCHAR(255) UNIQUE NOT NULL,
    status      payment_status      NOT NULL DEFAULT 'pending',
    order_id    BIGINT,
    CONSTRAINT fk_payments_user FOREIGN KEY (tg_user_id)
        REFERENCES user_info (tg_user_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    CONSTRAINT fk_payments_order FOREIGN KEY (order_id)
        REFERENCES buyer_orders (id)
        ON UPDATE CASCADE
        ON DELETE SET NULL
);

--
-- 7. Таблица warehouses
--    Информация о поставщике для ЯДоставки
--

CREATE TABLE warehouses
(
    id            SERIAL PRIMARY KEY,
    name          VARCHAR(255)   NOT NULL,
    address       TEXT           NOT NULL,
    latitude      NUMERIC(10, 7) NOT NULL,
    longitude     NUMERIC(10, 7) NOT NULL,
    contact_name  VARCHAR(255)   NOT NULL,
    contact_phone VARCHAR(20)    NOT NULL,
    porch         VARCHAR(10), -- Подъезд
    floor         VARCHAR(10), -- Этаж
    apartment     VARCHAR(10), -- Квартира/офис
    is_active     BOOLEAN        NOT NULL DEFAULT TRUE,
    is_default    BOOLEAN        NOT NULL DEFAULT FALSE
);

-- Добавим уникальный индекс, чтобы только один склад мог быть по умолчанию
CREATE UNIQUE INDEX one_default_warehouse_idx ON warehouses (is_default) WHERE is_default = TRUE;

