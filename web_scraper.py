import os
import time
import re
import pandas as pd
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from typing import List, Dict, Optional, Tuple

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


# --- 1. LOGGING SETUP ---
logger = logging.getLogger("FlightScraper")
logger.setLevel(logging.INFO)

# Rotate logs at 5MB, keep 3 backup files
file_handler = RotatingFileHandler("scraper.log", maxBytes=2*1024*1024, backupCount=3)
stream_handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

file_handler.setFormatter(formatter)
stream_handler.setFormatter(formatter)
logger.addHandler(file_handler)
logger.addHandler(stream_handler)


def generate_google_flights_url(
        origin: str, 
        dest: str, 
        depature_date: str, 
        return_date: str | None = None, 
        one_way: bool = True
        ) -> tuple[str, str]:
    """
    Docstring for generate_google_flights_url
    
    :param origin: Airport code of origin or city name (e.g. VIE for Vienna, or Vienna)
    :type origin: str
    :param dest: Airport code of destination or city name (e.g. LHR for London Heathrow, or London)
    :type dest: str
    :param depature_date: Departure date
    :type depature_date: date
    :param return_date: Return date, default None
    :type return_date: date | None
    :param one_way: one way trip if True, defaults to True
    :return: url string for Google Flights search
    :rtype: str
    """

    if one_way or return_date is None:
        query = f"Flights to {dest} from {origin} on {depature_date} oneway non-stop"
    else:
        query = f"Flights to {dest} from {origin} on {depature_date} return {return_date} non-stop"
    
    # URL encode the spaces to %20
    encoded_query = query.replace(" ", "%20")
    return f"https://www.google.com/travel/flights?q={encoded_query}", encoded_query


def scrape_google_flights(url: str) -> pd.DataFrame:
    chrome_options = Options()
    chrome_options.page_load_strategy = 'eager'
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    # --- CROSS-PLATFORM PATH DETECTION ---
    pi_browser_path = "/usr/bin/chromium"
    pi_driver_path = "/usr/bin/chromedriver"

    # If we are on the Raspberry Pi (Linux + specific path exists)
    if os.path.exists(pi_browser_path):
        chrome_options.binary_location = pi_browser_path
        driver_service = Service(executable_path=pi_driver_path)
        driver = webdriver.Chrome(service=driver_service, options=chrome_options)
    else:
        driver = webdriver.Chrome(options=chrome_options)
        
    driver.set_page_load_timeout(60)
    
    try:
        logger.info(f"Scraping URL: {url}")
        driver.get(url)
        wait = WebDriverWait(driver, 15)

        # A. CONSENT SCREEN
        try:
            reject_xpath = "//button[contains(., 'Reject all') or contains(., 'Alle ablehnen')]"
            reject_btn = wait.until(EC.element_to_be_clickable((By.XPATH, reject_xpath)))
            reject_btn.click()
            logger.info("Consent screen cleared.")
        except Exception:
            pass # Already cleared or didn't appear

        # B. POP-UP KILLER (Recommended Flights / Tips)
        try:
            time.sleep(2) # Small pause for animations
            driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
            
            pop_up_xpath = "//button[contains(., 'Got it') or contains(., 'Verstanden') or contains(., 'Done')]"
            pop_ups = driver.find_elements(By.XPATH, pop_up_xpath)
            for btn in pop_ups:
                btn.click()
                logger.info("Recommendation pop-up cleared.")
        except Exception:
            pass

        # C. CLICK DEPARTURE INPUT
        try:
            departure_input = wait.until(EC.element_to_be_clickable((By.XPATH, "//input[@placeholder='Departure']")))
            departure_input.click()
            logger.info("'Departure' input clicked.")
        except Exception:
            logger.warning("Could not click 'Departure' input.")

        # D. EXTRACT PRICES FROM CALENDER
        logger.info("Executing 10 clicks for all months to load...")
        for i in range(10):
            try:
                # Use a short wait to ensure the button is ready for the next click
                next_btn = wait.until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "button[jsname='KpyLEe']"))
                )
                driver.execute_script("arguments[0].click();", next_btn)
                # Small buffer to prevent the browser from freezing
                time.sleep(3) 
            except Exception as e:
                logger.warning(f"Stopped at click {i+1}: {e}")
                break

        # Give the final view a moment to load prices for the current months
        logger.info("Clicks finished. Waiting for final render...")
        time.sleep(3)

        # 3. Scrape EVERYTHING currently in the HTML
        all_elements = driver.find_elements(By.CSS_SELECTOR, "div[role='gridcell'][data-iso]")
        logger.info(f"Total elements found in HTML: {len(all_elements)}")

        results = []
        for cell in all_elements:
            # We ignore aria-hidden here to see 'ghost' elements too
            date_iso = cell.get_attribute("data-iso")
            price = None
            
            try:
                # Look for the price div
                price_el = cell.find_element(By.CSS_SELECTOR, "div[jsname='qCDwBb']")
                price_label = price_el.get_attribute("aria-label")
                if price_label:
                    digits = re.sub(r'\D', '', price_label)
                    if digits:
                        price = int(digits)
            except:
                pass
            
            results.append({"departure_date": date_iso, "price": price})

        # 4. Analyze what we found
        df = pd.DataFrame(results)
        # Sort by date to see the range we actually captured
        df = df.sort_values('departure_date').drop_duplicates(subset=['departure_date'])

        return df

    except Exception as e:
        logger.error(f"Critical error during scrape: {e}")
        return pd.DataFrame(columns=['departure_date', 'price'])
    finally:
        driver.quit()


def edit_flight_data(df: pd.DataFrame) -> pd.DataFrame:
    df['scraped_at'] = datetime.now().strftime('%Y-%m-%d')

    return df


def get_flight_route_data(
        origin: str, 
        dest: str, 
        depature_date: str, 
        return_date: str | None = None, 
        one_way: bool = True,
        ) -> pd.DataFrame:
    
    url, _ = generate_google_flights_url(origin, dest, depature_date, return_date, one_way)
    data = scrape_google_flights(url)
    return edit_flight_data(data)


def main():
    # Simple test run
    # Example: Search Vienna to Agadir
    date_today = datetime.now().strftime('%Y-%m-%d')
    search_url, encoded_query = generate_google_flights_url("Vienna", "Agadir", date_today)

    df = scrape_google_flights(search_url)
    df = edit_flight_data(df)

    df.to_csv(f"flight_prices_{encoded_query}.csv", mode='a', index=False, header=not os.path.isfile(f"flight_prices_{encoded_query}.csv"))
    logger.info(f"Saved {len(df)} flights to csv.")


if __name__ == "__main__":
    main()