from app.database.connection import create_connection


def get_all_products():
    connection = create_connection()

    try:
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                id,
                product_name,
                store_name,
                product_url,
                image_url,
                current_price,
                old_price,
                discount_percent,
                rating,
                review_count,
                availability,
                last_checked
            FROM products
            ORDER BY last_checked DESC
        """)

        return cursor.fetchall()

    finally:
        cursor.close()
        connection.close()


def get_product_by_id(product_id):
    connection = create_connection()

    try:
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                id,
                product_name,
                store_name,
                product_url,
                image_url,
                current_price,
                old_price,
                discount_percent,
                rating,
                review_count,
                availability,
                last_checked
            FROM products
            WHERE id = %s
        """, (product_id,))

        return cursor.fetchone()

    finally:
        cursor.close()
        connection.close()


def search_products(keyword):
    connection = create_connection()

    try:
        cursor = connection.cursor(dictionary=True)

        search_term = f"%{keyword}%"

        cursor.execute("""
            SELECT
                id,
                product_name,
                store_name,
                product_url,
                image_url,
                current_price,
                old_price,
                discount_percent,
                rating,
                review_count,
                availability,
                last_checked
            FROM products
            WHERE product_name LIKE %s
               OR store_name LIKE %s
            ORDER BY last_checked DESC
        """, (search_term, search_term))

        return cursor.fetchall()

    finally:
        cursor.close()
        connection.close()


def get_price_history(product_id):
    connection = create_connection()

    try:
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                price,
                checked_at
            FROM price_history
            WHERE product_id = %s
            ORDER BY checked_at ASC
        """, (product_id,))

        return cursor.fetchall()

    finally:
        cursor.close()
        connection.close()


def get_products_by_store(store_name):
    connection = create_connection()

    try:
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                id,
                product_name,
                store_name,
                product_url,
                image_url,
                current_price,
                old_price,
                discount_percent,
                rating,
                review_count,
                availability,
                last_checked
            FROM products
            WHERE LOWER(store_name) = LOWER(%s)
            ORDER BY last_checked DESC
        """, (store_name,))

        return cursor.fetchall()

    finally:
        cursor.close()
        connection.close()


def get_top_discounted_products(limit=5):
    connection = create_connection()

    try:
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                id,
                product_name,
                store_name,
                current_price,
                old_price,
                discount_percent,
                rating,
                image_url,
                product_url
            FROM products
            WHERE discount_percent IS NOT NULL
            ORDER BY discount_percent DESC
            LIMIT %s
        """, (limit,))

        return cursor.fetchall()

    finally:
        cursor.close()
        connection.close()


def get_product_ratings():
    connection = create_connection()

    try:
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                id,
                product_name,
                rating
            FROM products
            ORDER BY rating DESC
        """)

        return cursor.fetchall()

    finally:
        cursor.close()
        connection.close()


def save_product(product):
    connection = create_connection()

    try:
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            "SELECT id, current_price FROM products WHERE product_url = %s",
            (product["product_url"],)
        )

        existing = cursor.fetchone()

        if existing:
            product_id = existing["id"]

            cursor.execute("""
                UPDATE products
                SET
                    product_name = %s,
                    store_name = %s,
                    image_url = %s,
                    current_price = %s,
                    old_price = %s,
                    discount_percent = %s,
                    rating = %s,
                    review_count = %s,
                    availability = %s,
                    last_checked = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (
                product["product_name"],
                product["store_name"],
                product.get("image_url"),
                product["current_price"],
                product.get("old_price"),
                product.get("discount_percent"),
                product.get("rating"),
                product.get("review_count", 0),
                product.get("availability"),
                product_id,
            ))

            if (
                existing["current_price"] is None
                or float(existing["current_price"]) != float(product["current_price"])
            ):
                cursor.execute("""
                    INSERT INTO price_history (product_id, price)
                    VALUES (%s, %s)
                """, (
                    product_id,
                    product["current_price"],
                ))

        else:
            cursor.execute("""
                INSERT INTO products (
                    product_name,
                    store_name,
                    product_url,
                    image_url,
                    current_price,
                    old_price,
                    discount_percent,
                    rating,
                    review_count,
                    availability
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                product["product_name"],
                product["store_name"],
                product["product_url"],
                product.get("image_url"),
                product["current_price"],
                product.get("old_price"),
                product.get("discount_percent"),
                product.get("rating"),
                product.get("review_count", 0),
                product.get("availability"),
            ))

            product_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO price_history (product_id, price)
                VALUES (%s, %s)
            """, (
                product_id,
                product["current_price"],
            ))

        connection.commit()

        return product_id

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()

def get_price_drops(limit=20):
    connection = create_connection()

    try:
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                p.id AS product_id,
                p.product_name,
                p.store_name,
                p.image_url,
                ph.prev_price AS old_price,
                ph.price AS new_price,
                ROUND((ph.prev_price - ph.price) / ph.prev_price * 100, 2)
                    AS drop_percent,
                ph.checked_at
            FROM (
                SELECT
                    product_id,
                    price,
                    checked_at,
                    LAG(price) OVER (
                        PARTITION BY product_id
                        ORDER BY checked_at
                    ) AS prev_price,
                    ROW_NUMBER() OVER (
                        PARTITION BY product_id
                        ORDER BY checked_at DESC
                    ) AS rn
                FROM price_history
            ) ph
            JOIN products p ON p.id = ph.product_id
            WHERE ph.rn = 1
              AND ph.prev_price IS NOT NULL
              AND ph.prev_price > 0
              AND ph.price < ph.prev_price
            ORDER BY ph.checked_at DESC
            LIMIT %s
        """, (limit,))

        return cursor.fetchall()

    finally:
        cursor.close()
        connection.close()


def get_store_summaries():
    connection = create_connection()

    try:
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                store_name,
                COUNT(*) AS product_count,
                ROUND(AVG(discount_percent), 2) AS average_discount,
                ROUND(AVG(rating), 2) AS average_rating,
                ROUND(AVG(current_price), 2) AS average_price,
                MAX(last_checked) AS last_checked
            FROM products
            GROUP BY store_name
            ORDER BY product_count DESC
        """)

        return cursor.fetchall()

    finally:
        cursor.close()
        connection.close()


def get_last_update():
    connection = create_connection()

    try:
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                MAX(last_checked) AS last_checked,
                COUNT(*) AS total_products
            FROM products
        """)

        return cursor.fetchone()

    finally:
        cursor.close()
        connection.close()


def get_price_trends(days=7):
    connection = create_connection()

    try:
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                DATE_FORMAT(checked_at, '%Y-%m-%d') AS day,
                ROUND(AVG((price - prev_price) / prev_price * 100), 2)
                    AS avg_change_percent,
                COUNT(*) AS changes
            FROM (
                SELECT
                    product_id,
                    price,
                    checked_at,
                    LAG(price) OVER (
                        PARTITION BY product_id
                        ORDER BY checked_at
                    ) AS prev_price
                FROM price_history
            ) t
            WHERE prev_price IS NOT NULL
              AND prev_price > 0
              AND checked_at >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
            GROUP BY DATE_FORMAT(checked_at, '%Y-%m-%d')
            ORDER BY day ASC
        """, (days,))

        return cursor.fetchall()

    finally:
        cursor.close()
        connection.close()

SORT_COLUMNS = {
    "name": "product_name",
    "price": "current_price",
    "discount": "discount_percent",
    "rating": "rating",
    "updated": "last_checked",
}


def get_products_page(
    page=1,
    per_page=10,
    search=None,
    store=None,
    sort="updated",
    order="desc",
    category=None,
    brand=None,
):
    column = SORT_COLUMNS.get(sort, "last_checked")
    direction = "ASC" if str(order).lower() == "asc" else "DESC"

    conditions = []
    params = []

    if search:
        conditions.append("(product_name LIKE %s OR store_name LIKE %s)")
        term = f"%{search}%"
        params.extend([term, term])

    if store:
        conditions.append("LOWER(store_name) = LOWER(%s)")
        params.append(store)

    if category:
        # A parent category also includes everything in its sub-categories
        conditions.append("""
            category_id IN (
                SELECT id FROM categories
                WHERE slug = %s
                   OR parent_id = (SELECT id FROM categories WHERE slug = %s)
            )
        """)
        params.extend([category, category])

    if brand:
        conditions.append("LOWER(brand) = LOWER(%s)")
        params.append(brand)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    offset = (page - 1) * per_page

    connection = create_connection()

    try:
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            f"SELECT COUNT(*) AS total FROM products {where}",
            params
        )

        total = cursor.fetchone()["total"]

        cursor.execute(f"""
            SELECT
                id,
                product_name,
                store_name,
                product_url,
                image_url,
                current_price,
                old_price,
                discount_percent,
                rating,
                review_count,
                availability,
                last_checked,
                brand,
                category_id
            FROM products
            {where}
            ORDER BY {column} IS NULL, {column} {direction}, id ASC
            LIMIT %s OFFSET %s
        """, params + [per_page, offset])

        return cursor.fetchall(), total

    finally:
        cursor.close()
        connection.close()