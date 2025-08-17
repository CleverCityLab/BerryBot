INSERT INTO user_info (tg_user_id)
VALUES (100001),
       (100002);

INSERT INTO buyer_info (user_id, name_surname, tel_num, tg_username, address, bonus_num)
VALUES (1, 'Ivan Petrov', '+79990000001', 'ivan_petrov',
        'Москва, Арбат 1', 50),
       (2, 'Maria Sidorova', '+79990000002', 'masha_sid',
        'С-Пб, Невский 10', 30);

INSERT INTO product_position (title, price, quantity)
VALUES ('Клубника 1 кг', 350, 100),
       ('Черника 0.5 кг', 500, 50),
       ('Малина 0.5 кг', 420, 40);

INSERT INTO buyer_orders
(buyer_id, status, delivery_way, registration_date, finished_at, delivery_date)
VALUES (1, 'waiting', 'pickup',
        CURRENT_DATE, NULL, NULL),
       (1, 'ready', 'delivery',
        CURRENT_DATE, NULL, CURRENT_DATE + INTERVAL '1 day'),
       (1, 'transferring', 'delivery',
        CURRENT_DATE - INTERVAL '1 day', NULL, CURRENT_DATE + INTERVAL '2 days'),
       (2, 'finished', 'pickup',
        CURRENT_DATE - INTERVAL '7 day', CURRENT_DATE - INTERVAL '5 day', NULL),
       (2, 'cancelled', 'delivery',
        CURRENT_DATE - INTERVAL '3 day', CURRENT_DATE - INTERVAL '1 day', NULL);

INSERT INTO order_items (order_id, position_id, qty)
VALUES
    -- заказ 1 (waiting)
    (1, 1, 1),
    (1, 2, 2),
    -- заказ 2 (ready)
    (2, 2, 1),
    (2, 3, 1),
    -- заказ 3 (transferring)
    (3, 1, 2),
    (3, 3, 1),
    -- заказ 4 (finished)
    (4, 1, 1),
    (4, 2, 1),
    -- заказ 5 (cancelled)
    (5, 3, 2),
    (5, 2, 1);