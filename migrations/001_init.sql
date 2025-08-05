-- =========================================
-- 01_create_schema.sql
-- =========================================

-- 1. ENUM‑типы для полей со статическими значениями
--
CREATE TYPE order_status AS ENUM (
    'waiting',
    'transferring',
    'ready'
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

--
-- 2. Таблица user_info
--
CREATE TABLE user_info (
    id            BIGINT PRIMARY KEY,
    tg_user_id    BIGINT NOT NULL UNIQUE
);

--
-- 3. Таблица buyer_info (1:1 по tg_user_id → user_info.tg_user_id)
--
CREATE TABLE buyer_info (
    tg_user_id    BIGINT PRIMARY KEY,
    name_surname  VARCHAR(50) NOT NULL,
    tel_num       BIGINT        NOT NULL,
    tg_username   VARCHAR(20),
    address       TEXT,
    bonus_num     INT           DEFAULT 0,
    CONSTRAINT fk_buyerinfo_user FOREIGN KEY (tg_user_id)
        REFERENCES user_info (tg_user_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

--
-- 4. Таблица product_position
--
CREATE TABLE product_position (
    id       INT PRIMARY KEY,
    title    VARCHAR(20) NOT NULL,
    price    INT          NOT NULL CHECK (price >= 0),
    quantity INT          NOT NULL CHECK (quantity >= 0)
);

--
-- 5. Таблица buyer_orders
--    Каждому заказу привязан пользователь и позиция товара
--
CREATE TABLE buyer_orders (
    id                BIGINT            PRIMARY KEY,
    position_id       INT               NOT NULL,
    status            order_status      NOT NULL DEFAULT 'waiting',
    delivery_way      delivery_way      NOT NULL DEFAULT 'pickup',
    registration_date DATE              NOT NULL DEFAULT CURRENT_DATE,
    delivery_date     DATE,
    is_finish         finish_status     NOT NULL DEFAULT 'in_process',
    receipt_date      DATE,
    CONSTRAINT fk_orders_user FOREIGN KEY (id)
        REFERENCES user_info (id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    CONSTRAINT fk_orders_position FOREIGN KEY (position_id)
        REFERENCES product_position (id)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT
);

