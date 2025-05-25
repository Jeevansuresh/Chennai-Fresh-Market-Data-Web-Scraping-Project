import requests
import csv
import mysql.connector
from datetime import datetime, timedelta

def generate_date_range(start_date, end_date):
    current_date = start_date
    while current_date <= end_date:
        yield current_date
        current_date += timedelta(days=1)

# Step 1: Scrape and save data to CSV
start_date = datetime(2022, 1, 1)  # Starting from Jan 1, 2022
end_date = datetime.today() - timedelta(days=1)        # Until yesterday's date

csv_file_path = 'vegetable_prev_prices.csv'

# Open the CSV file for writing
with open(csv_file_path, mode="w", newline="", encoding="utf-8") as csvfile:
    csvwriter = csv.writer(csvfile)
    header = ["Date", "Vegetable", "Wholesale Price", "Retail Min", "Retail Max", "Mall Min", "Mall Max", "Units"]
    csvwriter.writerow(header)  # Write header to CSV

    print("Starting...")

    # Initialize counters and list for error tracking
    success_dates = 0
    failed_dates = []

    for current_date in generate_date_range(start_date, end_date):
        formatted_date = current_date.strftime('%Y-%m-%d')

        url = "https://vegetablemarketprice.com/api/dataapi/market/chennai/daywisedata"
        params = {"date": formatted_date}
        response = requests.get(url, params=params)

        if response.status_code == 200:
            try:
                data = response.json()  # Convert response to JSON

                # Process and write data to CSV
                for item in data.get('data', []):
                    vegetable = item.get("vegetablename", "N/A").split(' (')[0]  # Remove the additional info in the name
                    wholesale_price = item.get("price", "N/A")
                    
                    # Split Retail Price into Retail Min and Retail Max
                    retail_prices = item.get("retailprice", "N/A").split(" - ")
                    retail_min = retail_prices[0] if len(retail_prices) > 1 else retail_prices[0]
                    retail_max = retail_prices[1] if len(retail_prices) > 1 else retail_prices[0]
                    
                    # Split Mall Price into Mall Min and Mall Max
                    mall_prices = item.get("shopingmallprice", "N/A").split(" - ")
                    mall_min = mall_prices[0] if len(mall_prices) > 1 else mall_prices[0]
                    mall_max = mall_prices[1] if len(mall_prices) > 1 else mall_prices[0]
                    
                    units = item.get("units", "N/A")

                    # Write each row of data to the CSV file
                    csvwriter.writerow([formatted_date, vegetable, wholesale_price,
                                        retail_min, retail_max, mall_min, mall_max, units])
                
                success_dates += 1

            except Exception as e:
                print(f"Error processing data for {formatted_date}: {e}")
                failed_dates.append(formatted_date)

        else:
            print(f"Failed to retrieve data for {formatted_date}. Status code: {response.status_code}")
            failed_dates.append(formatted_date)

# Step 2: Insert data from CSV into SQL database

# Connect to MySQL
db_connection = mysql.connector.connect(
    host="localhost",
    user="root",
    password="Skyno@1978",  # Change this to your MySQL password
    database="vegetables"  # Change this to your database name
)
cursor = db_connection.cursor()

# Step 2.1: Clear the existing data from the table
#delete_query = "DELETE FROM VEG_DATA"
#cursor.execute(delete_query)
#db_connection.commit()
print("Existing data cleared from VEG_DATA table.")

# Create table if it doesn't exist (adjust column types as needed)
create_table_query = """
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
"""
cursor.execute(create_table_query)

# Insert data from the CSV into the database
with open(csv_file_path, mode="r", newline="", encoding="utf-8") as csvfile:
    csvreader = csv.reader(csvfile)
    next(csvreader)  # Skip the header row

    for row in csvreader:
        formatted_date, vegetable, wholesale_price, retail_min, retail_max, mall_min, mall_max, units = row

        # Prepare the insert query
        insert_query = """
        INSERT INTO VEG_DATA (date, vegetable, wholesale_price, retail_min, retail_max, mall_min, mall_max, units)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        # Insert data into the database
        try:
            cursor.execute(insert_query, (
                formatted_date, vegetable, wholesale_price, retail_min, retail_max, mall_min, mall_max, units
            ))
            db_connection.commit()  # Commit after every insert
            print(f"Inserted data for {vegetable} on {formatted_date}")
        except mysql.connector.Error as err:
            print(f"Error inserting data for {vegetable} on {formatted_date}: {err}")
            db_connection.rollback()  # Rollback in case of error

# Close the database connection
cursor.close()
db_connection.close()

# Final summary
print("\nSummary:")
print(f"Data received for {success_dates} dates.")
if failed_dates:
    print(f"Data unable to receive for the following dates: {', '.join(failed_dates)}")
else:
    print("No dates failed.")
