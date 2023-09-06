from db.mongo_utils import MongoUtils
from trading.bybit_utils import BybitUtils
from utils.logger_module import setup_logger
from utils.position_utils import check_and_close_position
import os
import time
from dotenv import load_dotenv

logger = setup_logger(__name__, 'my_app.log')

# Load the .env file
load_dotenv()

# Access the variables
MONGODB_URI = os.getenv('MONGODB_URI')
MONGODB_DATABASE = os.getenv('MONGODB_DATABASE')
BYBIT_API_KEY = os.getenv('BYBIT_API_KEY')
BYBIT_API_SECRET = os.getenv('BYBIT_API_SECRET')

# Initialize MongoDB and Bybit utilities
mongo = MongoUtils(MONGODB_URI, MONGODB_DATABASE)
bybit = BybitUtils(BYBIT_API_KEY, BYBIT_API_SECRET, mongo)

# Global dictionary to store the latest price for each symbol
current_prices = {}

while True:
    open_positions = bybit.get_all_open_positions()

    for position in open_positions:
        try:
            symbol = position['data']['symbol']
            current_price_symbol = ticker = bybit.client.Market.Market_symbolInfo(symbol=symbol).result()[0]['result'][0]['last_price']
            print(f"symbol: {symbol}, price: {current_price_symbol}")
            check_and_close_position(position, float(current_price_symbol), mongo, bybit)
        except Exception as e:
            logger.error(f"Error while checking and closing position: {e}")

    time.sleep(0.1)
