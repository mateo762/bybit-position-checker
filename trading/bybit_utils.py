import bybit
from datetime import datetime, timezone
import time
from bson import ObjectId
from pybit.unified_trading import HTTP
from utils.logger_module import setup_logger
from dotenv import load_dotenv
import hmac
import hashlib
import os
import requests

# Bybit API endpoint for closing a position
BYBIT_ENDPOINT = "https://api.bybit.com/v5/order/create"

load_dotenv()

logger = setup_logger(__name__, 'my_app.log')


def generate_signature(secret, data):
    return hmac.new(bytes(secret, 'latin-1'), msg=bytes(data, 'latin-1'), digestmod=hashlib.sha256).hexdigest()


class BybitUtils:
    def __init__(self, api_key, api_secret, mongo):
        self.mongo = mongo
        self.client = bybit.bybit(api_key=api_key, api_secret=api_secret, test=False)
        self.positions_cache = None
        self.last_cache_update = datetime.min.replace(tzinfo=timezone.utc)

    def get_current_price(self, symbol):
        """
        Fetch the current price for a given symbol.
        """
        return float(self.client.Market.Market_symbolInfo().result()[0]['result'][0]['last_price'])

    def get_position_for_symbol(self, symbol):
        """
        Fetch the position for a given symbol.
        """
        positions = self.client.Positions.Positions_myPosition().result()[0]['result']
        return next((item for item in positions if item["symbol"] == symbol), None)

    def close_position(self, position, account_number, last_transaction_number, position_status):
        # Initialize the Bybit session
        session = HTTP(
            testnet=False,  # Set to False if you're using the live environment
            api_key=os.getenv("BYBIT_API_KEY"),
            api_secret=os.getenv("BYBIT_API_SECRET"),
        )

        # Extract position details
        symbol = position['data']['symbol']
        transaction_id = position['transaction_id']
        position = self.get_position_for_symbol(symbol)
        flag_closing = self.mongo.get_transaction_state(transaction_id)
        logger.info(f"Trying to close, position: {position}, closing: {flag_closing}")
        if position and not flag_closing:
            side = "Sell" if position['data']['side'] == "Buy" else "Buy"
            qty = str(position['data']['size'])

            # Place the order to close the position
            response = session.place_order(
                category="linear",  # Since it's a USDT perpetual future
                symbol=symbol,
                side=side,
                orderType="Market",  # Close at market price
                qty=qty,
                reduceOnly=True,  # Ensure this order only reduces the position
                orderLinkId=f"{account_number}_{symbol}_{last_transaction_number}_{position_status}_safety"
            )

            print(response)
            return response
        else:
            logger.info(f"No long position for {symbol}. No action taken")

    def close_short_position(self, symbol, quantity, account_number, last_transaction_number, position_status):
        """
        Close a short position by buying.
        """
        print(f'Closing Short {account_number}_{symbol}_{last_transaction_number}_{position_status}')
        self.client.LinearOrder.LinearOrder_new(side='Buy', symbol=symbol, order_type='Market', qty=quantity,
                                                time_in_force='GoodTillCancel', reduce_only=True, close_on_trigger=True)

    def get_all_open_positions(self, force_update=False):
        """
        Fetch all open positions. Use cached data if available and not stale.
        """
        now = datetime.now(timezone.utc)
        cache_duration = now - self.last_cache_update

        if not self.positions_cache or cache_duration.total_seconds() > 60 or force_update:
            logger.info("Start refreshing cache...")

            positions = self.client.LinearPositions.LinearPositions_myPosition().result()[0]['result']
            fresh_positions_cache = [position for position in positions if float(position['data']['size']) != 0]
            cache_before_copy = self.positions_cache

            cache_dict = {pos['order_id']: pos for pos in self.positions_cache} if self.positions_cache else {}

            new_cache_dict = {}

            for position in fresh_positions_cache:
                transaction = self.mongo.get_most_recent_transaction_for_symbol(position['data']['symbol'],
                                                                                ObjectId('63dc0d4d04fe7e634851ff77'))
                position['order_id'] = transaction['order_id']

                # Check if 'order_id' already exists in the cache
                if position['order_id'] not in cache_dict:
                    position['transaction_id'] = transaction['_id']
                    position['orderParams'] = self.mongo.get_order_for_transaction(transaction['order_id'])
                    position['accountNumber'], position[
                        'lastTransactionNumber'] = self.mongo.get_account_and_transaction_number(
                        transaction['account_id'])
                    position['status'] = 'OPEN'
                    logger.info(f"Adding new {position['data']['symbol']} position to cache: {position}")

                    # Add to the dictionary
                    cache_dict[position['order_id']] = position
                else:
                    position = cache_dict[position['order_id']]
                    if position['status'] in ['C_SL', 'C_13', 'C_23', 'C_TP3']:
                        logger.info(
                            f"Cache ignoring the following {position['data']['symbol']} position: {position}, status: {position['status']}")
                        continue

                new_cache_dict[position['order_id']] = position

            self.positions_cache = list(new_cache_dict.values())
            self.last_cache_update = now

            if force_update:
                logger.info(
                    f"Forced refresh cache, positions fetched: {fresh_positions_cache}, cache before: {cache_before_copy}, cache after: {self.positions_cache}")
            else:
                logger.info(
                    f"Refresh cache, positions fetched: {fresh_positions_cache}, cache before: {cache_before_copy}, cache after: {self.positions_cache}")

            # If there are no open positions, wait for 2 seconds
            if not self.positions_cache:
                time.sleep(2)

        return self.positions_cache

# Usage example:
# bybit = BybitUtils(BYBIT_API_KEY, BYBIT_API_SECRET)
# current_price = bybit.get_current_price('BTCUSDT')
# print(current_price)
