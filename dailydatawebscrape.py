import requests
from bs4 import BeautifulSoup
import mysql.connector
import csv
from datetime import datetime, timedelta
import pandas as pd

# --- Configuration ---
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "Skyno@1978",
    "database": "vegetables"
}

# --- Utility Functions ---
def clean_price(value):
    return value.replace('₹', '').replace(',', '').strip()

def calculate_statistics(df, vegetable, today_date):
    current_date = today_date - timedelta(days=1)
    veggie_data = df[(df['Vegetable'] == vegetable) & (df['Date'] <= current_date)].dropna(subset=['Wholesale Price']).sort_values('Date')

    dma_30_data = veggie_data.tail(30)
    dma_30 = dma_30_data['Wholesale Price'].mean() if len(dma_30_data) == 30 else None

    dma_90_data = veggie_data.tail(90)
    if len(dma_90_data) == 90:
        dma_90 = dma_90_data['Wholesale Price'].mean()
        highest_90 = dma_90_data['Wholesale Price'].max()
        lowest_90 = dma_90_data['Wholesale Price'].min()
        median_90 = dma_90_data['Wholesale Price'].median()
    else:
        dma_90 = highest_90 = lowest_90 = median_90 = None

    prev_cutoff = current_date - timedelta(days=365)
    prev_year_data = veggie_data[veggie_data['Date'] <= prev_cutoff].sort_values('Date')
    dma_90_prev_data = prev_year_data.tail(90)
    dma_90_prev = dma_90_prev_data['Wholesale Price'].mean() if len(dma_90_prev_data) == 90 else None

    return dma_30, dma_90, highest_90, lowest_90, median_90, dma_90_prev

def update_today_stats(cursor, db, df, today_date):
    vegetables = df['Vegetable'].unique()
    updated_count = 0
    for veg in vegetables:
        stats = calculate_statistics(df, veg, today_date)
        stats = tuple(float(x) if x is not None else None for x in stats)
        update_query = """
        UPDATE VEG_DATA
        SET dma_30 = %s, dma_90 = %s, high_90 = %s, low_90 = %s, median_90 = %s, dma_90_prev = %s
        WHERE vegetable = %s AND date = %s
        """
        cursor.execute(update_query, (*stats, veg, today_date))
        updated_count += 1
    db.commit()
    print(f"\n✅ Statistics updated for {updated_count} vegetables for date {today_date}")

# --- Connect to Database ---
db = mysql.connector.connect(**DB_CONFIG)
cursor = db.cursor()

# --- Scrape Today's Data ---
url = "https://vegetablemarketprice.com/market/chennai/today"
response = requests.get(url)

today_date = datetime.today().date()
print(f"\n🔄 Running web scrape for: {today_date}")

if response.status_code == 200:
    soup = BeautifulSoup(response.text, "html.parser")
    table = soup.find("table")

    if table:
        rows = table.find_all("tr")
        inserted = 0
        with open("vegetable_prices_today.csv", "w", newline="", encoding="utf-8") as today_csv, \
             open("vegetable_prev_prices.csv", "a", newline="", encoding="utf-8") as prev_csv:

            today_writer = csv.writer(today_csv)
            prev_writer = csv.writer(prev_csv)
            header = ["Vegetable", "Wholesale Price", "Retail Min", "Retail Max", "Mall Min", "Mall Max", "Units"]
            today_writer.writerow(header)

            for row in rows[1:]:
                cols = row.find_all("td")
                vegetable = cols[1].text.strip().split('(')[0].strip()
                wholesale_price = clean_price(cols[2].text.strip())

                retail_prices = [clean_price(p) for p in cols[3].text.strip().split(" - ")]
                retail_min = retail_prices[0]
                retail_max = retail_prices[1] if len(retail_prices) > 1 else retail_prices[0]

                mall_prices = [clean_price(p) for p in cols[4].text.strip().split(" - ")]
                mall_min = mall_prices[0]
                mall_max = mall_prices[1] if len(mall_prices) > 1 else mall_prices[0]

                units = cols[5].text.strip() if len(cols) > 5 else ""

                row_data = [vegetable, wholesale_price, retail_min, retail_max, mall_min, mall_max, units]
                today_writer.writerow(row_data)
                prev_writer.writerow([today_date] + row_data)

                insert_query = """
                INSERT INTO VEG_DATA (date, vegetable, wholesale_price, retail_min, retail_max, mall_min, mall_max, units)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """
                try:
                    cursor.execute(insert_query, (
                        today_date, vegetable, wholesale_price, retail_min, retail_max, mall_min, mall_max, units
                    ))
                    db.commit()
                    inserted += 1
                except mysql.connector.Error as err:
                    print(f"⚠️ Insert failed for {vegetable}: {err}")
                    db.rollback()
        print(f"\n✅ Today's data inserted for {inserted} vegetables.")

        # After inserting today's data, read from DB and update today's stats
        cursor.execute("SELECT date, vegetable, wholesale_price FROM VEG_DATA WHERE date <= %s", (today_date,))
        all_data = cursor.fetchall()
        df = pd.DataFrame(all_data, columns=['Date', 'Vegetable', 'Wholesale Price'])
        df['Date'] = pd.to_datetime(df['Date'])
        df['Wholesale Price'] = pd.to_numeric(df['Wholesale Price'], errors='coerce')

        print("\n📊 Calculating and updating statistics for today's data...")
        update_today_stats(cursor, db, df, today_date)

    else:
        print("⚠️ No table found on page.")
else:
    print("❌ Failed to fetch today's data.")

cursor.close()
db.close()
print("🔚 Operation completed.")
