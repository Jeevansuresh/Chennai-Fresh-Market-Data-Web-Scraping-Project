import requests
import mysql.connector
from datetime import datetime, timedelta
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# --- DB Config ---
DB_CONFIG = {
    "host": "localhost",
    "user": "jagi",
    "password": "Padjagi75$",
    "database": "vegetables"
}

# Thread-local storage for DB connections to avoid conflicts between threads
thread_local = threading.local()

def get_db_connection():
    if not hasattr(thread_local, "db"):
        thread_local.db = mysql.connector.connect(**DB_CONFIG)
        thread_local.cursor = thread_local.db.cursor()
    return thread_local.db, thread_local.cursor

def clean_price(value):
    if isinstance(value, str):
        return value.replace('₹', '').replace(',', '').strip()
    return value

def generate_date_range(start_date, end_date):
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)

def scrape_date_data(date_obj):
    date_str = date_obj.strftime('%Y-%m-%d')
    url = "https://vegetablemarketprice.com/api/dataapi/market/chennai/daywisedata"
    params = {"date": date_str}

    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200:
            print(f"❌ {date_str}: Failed to fetch data with status {response.status_code}")
            return

        data = response.json()
        rows = []
        for item in data.get('data', []):
            vegetable = item.get("vegetablename", "").split(' (')[0].strip()
            wholesale = clean_price(item.get("price", "0"))
            retail_min, retail_max = (item.get("retailprice", "0 - 0") + " - 0").split(" - ")[:2]
            mall_min, mall_max = (item.get("shopingmallprice", "0 - 0") + " - 0").split(" - ")[:2]
            units = item.get("units", "")

            rows.append((date_str, vegetable, wholesale, retail_min, retail_max, mall_min, mall_max, units))

        db, cursor = get_db_connection()
        insert_query = """
            INSERT INTO VEG_DATA (date, vegetable, wholesale_price, retail_min, retail_max, mall_min, mall_max, units)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.executemany(insert_query, rows)
        db.commit()
        print(f"✅ {date_str}: Inserted {len(rows)} rows")
    except Exception as e:
        print(f"⚠️ {date_str}: Exception occurred - {e}")

def create_table_if_not_exists():
    db, cursor = get_db_connection()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS VEG_DATA (
        id INT AUTO_INCREMENT PRIMARY KEY,
        date DATE,
        vegetable VARCHAR(255),
        wholesale_price DECIMAL(10, 2),
        retail_min DECIMAL(10, 2),
        retail_max DECIMAL(10, 2),
        mall_min DECIMAL(10, 2),
        mall_max DECIMAL(10, 2),
        units VARCHAR(50),
        dma_30 DECIMAL(10, 2),
        dma_90 DECIMAL(10, 2),
        high_90 DECIMAL(10, 2),
        low_90 DECIMAL(10, 2),
        median_90 DECIMAL(10, 2),
        dma_90_prev DECIMAL(10, 2)
    )
    """)
    db.commit()

def calc_stats(df, vegetable, today):
    current = today - timedelta(days=1)
    filtered = df[(df["Vegetable"] == vegetable) & (df["Date"] <= current)].sort_values("Date")

    dma_30 = filtered.tail(30)["Wholesale Price"].mean() if len(filtered) >= 30 else None
    dma_90_block = filtered.tail(90)
    dma_90 = dma_90_block["Wholesale Price"].mean() if len(dma_90_block) >= 90 else None
    high_90 = dma_90_block["Wholesale Price"].max() if len(dma_90_block) >= 90 else None
    low_90 = dma_90_block["Wholesale Price"].min() if len(dma_90_block) >= 90 else None
    median_90 = dma_90_block["Wholesale Price"].median() if len(dma_90_block) >= 90 else None

    prev_cutoff = current - timedelta(days=365)
    prev_block = filtered[filtered["Date"] <= prev_cutoff].sort_values("Date").tail(90)
    dma_90_prev = prev_block["Wholesale Price"].mean() if len(prev_block) >= 90 else None

    return dma_30, dma_90, high_90, low_90, median_90, dma_90_prev

def backfill_statistics():
    print("\n📊 Starting backfill of statistics...")

    db, cursor = get_db_connection()
    cursor.execute("SELECT date, vegetable, wholesale_price FROM VEG_DATA")
    data = cursor.fetchall()

    df = pd.DataFrame(data, columns=["Date", "Vegetable", "Wholesale Price"])
    df["Date"] = pd.to_datetime(df["Date"])
    df["Wholesale Price"] = pd.to_numeric(df["Wholesale Price"], errors='coerce')

    unique_dates = sorted(df["Date"].unique())
    unique_vegetables = df["Vegetable"].unique()

    updates = 0
    for veg in unique_vegetables:
        for dt in unique_dates:
            stats = calc_stats(df, veg, dt)
            cursor.execute("""
                UPDATE VEG_DATA
                SET dma_30 = %s, dma_90 = %s, high_90 = %s, low_90 = %s, median_90 = %s, dma_90_prev = %s
                WHERE vegetable = %s AND date = %s
            """, (*stats, veg, dt))
            updates += 1
            print(f"{veg} {dt.date()} Backfilled")
            if updates % 500 == 0:
                db.commit()
    db.commit()
    print(f"\n✅ Backfill complete. Total records updated: {updates}")

def main():
    create_table_if_not_exists()

    start_date = datetime(2022, 1, 1)
    end_date = datetime.today() - timedelta(days=1)

    print(f"🔄 Starting historical data scrape from {start_date.date()} to {end_date.date()} with multithreading...")

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(scrape_date_data, date) for date in generate_date_range(start_date, end_date)]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                print(f"Thread exception: {e}")

    backfill_statistics()

    # Close DB connection for main thread
    db, cursor = get_db_connection()
    cursor.close()
    db.close()
    print("🔚 All operations completed successfully.")

if __name__ == "__main__":
    main()
