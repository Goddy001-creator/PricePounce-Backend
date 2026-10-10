import csv
import sys
from decimal import Decimal, InvalidOperation

from app.database.repositories import create_connection
from app.services.product_service import save_products

BRANDS = [
    "Apple", "Samsung", "Tecno", "Infinix", "Itel", "Xiaomi", "Oppo", "Realme",
    "Nokia", "Huawei", "Google", "OnePlus", "HP", "Dell", "Lenovo", "Asus",
    "Acer", "Microsoft", "Sony", "LG", "Hisense", "TCL", "JBL", "Anker",
    "Oraimo", "Binatone", "Scanfrost", "Midea", "Philips", "Bosch", "Nexus",
    "Canon", "Epson", "Logitech", "Redmi", "Poco", "Nintendo", "Mi",
]
BRAND_LOOKUP = {b.lower(): b for b in BRANDS}

DRY_RUN = "--dry-run" in sys.argv


def parse_price(value, required=False):
    text = str(value or "").replace(",", "").replace("₦", "").strip()

    if not text:
        if required:
            raise ValueError("missing price")
        return None

    try:
        price = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"bad price '{value}'")

    if price <= 0 or price >= Decimal("99999999.99"):
        raise ValueError(f"price out of range '{value}'")

    return float(price)


def parse_rating(value):
    text = str(value or "").strip()

    if not text:
        return None

    try:
        rating = float(text)
    except ValueError:
        raise ValueError(f"bad rating '{value}'")

    if not 0 <= rating <= 5:
        raise ValueError(f"rating out of range '{value}'")

    return rating


def guess_brand(name):
    for word in name.replace("-", " ").split()[:4]:
        brand = BRAND_LOOKUP.get(word.lower())
        if brand:
            return brand
    return None


def load_category_map(cursor):
    cursor.execute("SELECT id, name, slug FROM categories")
    lookup = {}
    for row in cursor.fetchall():
        lookup[row["slug"].lower()] = row["id"]
        lookup[row["name"].lower()] = row["id"]
    return lookup


def build_product(row):
    name = (row.get("product_name") or "").strip()
    store = (row.get("store_name") or "").strip()
    url = (row.get("product_url") or "").strip()
    image = (row.get("image_url") or "").strip()

    if not name or len(name) > 255:
        raise ValueError("missing or too long product_name")
    if not store or len(store) > 100:
        raise ValueError("missing or too long store_name")
    if not url.startswith(("http://", "https://")) or len(url) > 500:
        raise ValueError("product_url must start with http(s):// and be under 500 chars")
    if image and not image.startswith(("http://", "https://")):
        raise ValueError("image_url must start with http(s)://")

    review_count = str(row.get("review_count") or "0").strip()

    return {
        "product_name": name,
        "store_name": store,
        "product_url": url,
        "image_url": image,
        "current_price": parse_price(row.get("current_price"), required=True),
        "old_price": parse_price(row.get("old_price")),
        "rating": parse_rating(row.get("rating")),
        "review_count": int(review_count) if review_count.isdigit() else 0,
        "availability": (row.get("availability") or "").strip() or "Unknown",
    }


def main():
    files = [arg for arg in sys.argv[1:] if not arg.startswith("--")]

    if len(files) != 1:
        sys.exit("Usage: python import_products.py products.csv [--dry-run]")

    connection = create_connection()
    cursor = connection.cursor(dictionary=True)
    categories = load_category_map(cursor)
    other_id = categories.get("other")

    imported = 0
    problems = []

    with open(files[0], newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)

        for line_number, row in enumerate(reader, start=2):
            try:
                product = build_product(row)

                category_text = (row.get("category") or "").split(">")[-1].strip().lower()
                category_id = categories.get(category_text, other_id)
                brand = (row.get("brand") or "").strip()[:100] or guess_brand(product["product_name"])

                if DRY_RUN:
                    imported += 1
                    continue

                saved = save_products([product])[0]

                cursor.execute(
                    "UPDATE products SET category_id = %s, brand = %s WHERE id = %s",
                    (category_id, brand, saved["id"]),
                )
                connection.commit()
                imported += 1

            except Exception as error:
                problems.append(f"line {line_number}: {error}")

    cursor.close()
    connection.close()

    label = "would import" if DRY_RUN else "imported"
    print(f"{label}: {imported} | skipped: {len(problems)}")

    for problem in problems[:50]:
        print("  ", problem)

    if len(problems) > 50:
        print(f"   ...and {len(problems) - 50} more")


if __name__ == "__main__":
    main()