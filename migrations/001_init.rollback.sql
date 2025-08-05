-- =========================================
-- 02_rollback_schema.sql
-- =========================================
-- 1. Снятие зависимостей и удаление таблиц
DROP TABLE IF EXISTS buyer_orders CASCADE;
DROP TABLE IF EXISTS product_position CASCADE;
DROP TABLE IF EXISTS buyer_info CASCADE;
DROP TABLE IF EXISTS user_info CASCADE;

-- 2. Удаление ENUM‑типов
DROP TYPE IF EXISTS finish_status;
DROP TYPE IF EXISTS delivery_way;
DROP TYPE IF EXISTS order_status;

