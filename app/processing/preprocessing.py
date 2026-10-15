import pandas as pd


def preprocess_products(products):
    if not products:
        return []

    dataframe = pd.DataFrame(products)

    if "rating" not in dataframe.columns:
        return products

    ratings = pd.to_numeric(dataframe["rating"], errors="coerce")
    average_rating = ratings.mean()

    # No product has a rating at all, so there is nothing to fill in
    if pd.isna(average_rating):
        return products

    dataframe["rating"] = ratings.fillna(average_rating).round(1)

    return dataframe.to_dict(orient="records")