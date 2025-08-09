DELETE
FROM order_items
WHERE order_id IN (1, 2, 3, 4, 5);
DELETE
FROM buyer_orders
WHERE id IN (1, 2, 3, 4, 5);
DELETE
FROM product_position
WHERE id IN (1, 2, 3);
DELETE
FROM buyer_info
WHERE user_id IN (1, 2);
DELETE
FROM user_info
WHERE id IN (1, 2);