import time
from vpa.app_runner import MarketAnalyzer
import pandas as pd
import time
import json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import os
from datetime import datetime, timedelta

driver = webdriver.Chrome()
driver.get("https://forexsb.com/historical-forex-data")
driver.set_window_size(1920, 1044)
driver.switch_to.frame(0)
driver.find_element(By.ID, "select-symbol").click()
dropdown = driver.find_element(By.ID, "select-symbol")
dropdown.find_element(By.XPATH, "//option[. = 'GBPUSD - British Pound / US Dollar']").click()
driver.switch_to.default_content()
driver.find_element(By.ID, "page-container").click()
driver.switch_to.frame(0)
driver.find_element(By.ID, "btn-load-data").click()
driver.find_element(By.ID, "select-format").click()
# Locate the dropdown element by its ID
dropdown = Select(driver.find_element("id", "select-format"))
# Select the option by visible text
dropdown.select_by_visible_text("Excel (CSV)")
# Wait up to 10 seconds for the link to be clickable
wait = WebDriverWait(driver, 10)
download_link = wait.until(EC.element_to_be_clickable((By.LINK_TEXT, "GBPUSD_D1.csv")))
download_link.click()

# Wait long enough for the file to download
time.sleep(10)
driver.quit()

# Adjust this path if your Downloads folder is in a different location
downloads_folder = os.path.join(os.path.expanduser("~"), "Downloads")

# Define the time threshold (last 5 minutes)
time_threshold = datetime.now() - timedelta(minutes=5)

# Check for files starting with "GBPUSD_D1" modified in the last 5 minutes
recent_files = []
for filename in os.listdir(downloads_folder):
    if filename.startswith("GBPUSD_D1"):
        file_path = os.path.join(downloads_folder, filename)
        modified_time = datetime.fromtimestamp(os.path.getmtime(file_path))
        if modified_time > time_threshold:
            recent_files.append(filename)

# Output the result
if recent_files:
    print("Recent files found:", recent_files)
else:
    print("No recent 'GBPUSD_D1*' files found in the last 5 minutes.")
    raise Exception("No recent 'GBPUSD_D1*' files found in the last 5 minutes.")

recent_files.sort(key=lambda f: os.path.getmtime(os.path.join(downloads_folder, f)), reverse=True)

my_df = pd.read_csv(os.path.join(downloads_folder, recent_files[0]), sep="\t", index_col=False).tail(100)

my_df.columns = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']
print(my_df.head(5))

analyzer = MarketAnalyzer(config_path="config/config.json", log_level="INFO", fixed_df=my_df)
signal_score = analyzer.process_data()