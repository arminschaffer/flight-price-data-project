import os
import json
import logging
import schedule
import time
from logging.handlers import RotatingFileHandler
from datetime import datetime

from web_scraper import get_flight_route_data
from db import Session, engine, Search


# --- 1. LOGGING SETUP ---
logger = logging.getLogger("FlightPriceTracker")
logger.setLevel(logging.INFO)

# Rotate logs at 5MB, keep 3 backup files
file_handler = RotatingFileHandler(
    "tracker.log", 
    maxBytes=2*1024*1024, 
    backupCount=3,
    delay=False
    )
stream_handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

file_handler.setFormatter(formatter)
stream_handler.setFormatter(formatter)
logger.addHandler(file_handler)
logger.addHandler(stream_handler)


def get_or_create_search(session, **kwargs) -> Search:
    """
    Checks if a search with specific parameters exists, 
    otherwise creates a new one.
    """
    # 1. Attempt to find the existing record
    instance = session.query(Search).filter_by(**kwargs).first()

    if instance:
        logger.info(f"Search found in DB (ID: {instance.id}).")
        return instance
    
    # 2. If not found, create it using the same dictionary
    instance = Search(**kwargs)
    session.add(instance)
    session.commit()
    session.refresh(instance)
    logger.info(f"New search created (ID: {instance.id}).")

    return instance


def load_searches(filepath="searches.json"):
    # 1. Check if the file even exists
    if not os.path.exists(filepath):
        logger.warning(f"File not found: {filepath}")
        return []

    try:
        with open(filepath, 'r') as f:
            data = json.load(f)
            
            # 2. Check if data is a list and has items
            if isinstance(data, list) and data:
                return data
            else:
                logger.warning(f"{filepath} is empty or not a valid list.")
                return []
                
    except json.JSONDecodeError:
        logger.warning(f"Failed to decode JSON in {filepath}. Check for syntax errors.")
        return []


def run_tracker():
    logger.info("=== Starting flight price data accumulation ===")

    try:
        # Setup DB session
        SessionLocal = Session()

        search_configs = load_searches('searches.json')

        for search_config in search_configs:
            logger.info(f"Start search for {search_config['origin']} -> {search_config['destination']}...")
            
            search = get_or_create_search(SessionLocal, **search_config)

            date_today = datetime.now().strftime('%Y-%m-%d')

            df = get_flight_route_data(origin=search.origin, dest=search.destination, depature_date=date_today)
            df["search_id"] = search.id
            df.to_sql('price_time_series', con=engine, if_exists='append', index=False)

            logger.info(f"Completed search for {search.origin} -> {search.destination}.")
        
        logger.info("Flight price accumulation run completed.")
        
    except Exception as e:
        logger.error(f"Scheduled task failed: {e}")
        

# Schedule the task
schedule.every().day.at("11:00").do(run_tracker)

if __name__ == "__main__":
    # logger.info("Scheduler active. Waiting...")
    # while True:
    #     schedule.run_pending()
    #     time.sleep(60) # Check every minute
    logger.info("Run price tracker once...")
    run_tracker()