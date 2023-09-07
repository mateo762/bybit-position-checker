from bson.objectid import ObjectId
from utils.email_module import send_email
from utils.logger_module import setup_logger
from trading.bybit_utils import close_position
import time

logger = setup_logger(__name__, 'my_app.log')

LIFE_CYCLE_MAP = {
    'PENDING': 'continue',
    'OPEN': 'stopLoss',
    'BREAK_EVEN': 'point13',
    'CANCELED': 'continue',
    'STOP_LOSS': 'stopLoss',
    'FIRST_MOVE': 'point13',
    'SECOND_MOVE': 'point23',
    'TAKE_PROFIT_2': 'point23',
    'TAKE_PROFIT_3': 'point23',
    'MANUALLY_CLOSED': 'continue',
    'BREAK_EVEN_PLUS': 'point23'
}


def check_would_close(current_price, position_type, threshold_low, threshold_high, close="NONE"):
    # Logic to determine if position should be closed
    change_status = False
    would_close = False
    closed_tp3 = False
    if position_type == "Long":
        if current_price <= threshold_low:
            would_close = True
        elif current_price >= threshold_high:
            change_status = True
            if close == 'TP3':
                closed_tp3 = True
                would_close = True
    else:  # Short position
        if current_price >= threshold_low:
            would_close = True
        elif current_price <= threshold_high:
            change_status = True
            if close == 'TP3':
                closed_tp3 = True
                would_close = True
    return would_close, change_status, closed_tp3


def check_and_close_position(position, current_price, mongo, bybit):
    if current_price == "NaN":
        return
    symbol = position['data']['symbol']
    position_amount = float(position['data']['size'])

    if position_amount == 0:
        return

    position_type = "Short" if position['data']['side'] == 'Sell' else "Long"
    would_close = False
    threshold_low = 0
    threshold_high = 0
    if position['status'] == "OPEN":
        threshold_low = position['orderParams']['stopLoss']
        threshold_high = position['orderParams']['point38']
        would_close, change_status, _ = check_would_close(current_price, position_type, threshold_low, threshold_high)
        if change_status and not would_close:
            position['status'] = 'PROTECCION_13'
        elif would_close:
            position['status'] = 'CLOSED_STOPLOSS'
    elif position['status'] == 'PROTECCION_13':
        threshold_low = position['orderParams']['point13']
        threshold_high = position['orderParams']['point61']
        would_close, change_status, _ = check_would_close(current_price, position_type, threshold_low, threshold_high)
        if change_status and not would_close:
            position['status'] = 'PROTECCION_23'
        elif would_close:
            position['status'] = 'CLOSED_PROTECCION_13'
    elif position['status'] == 'PROTECCION_23':
        threshold_low = position['orderParams']['point23']
        threshold_high = position['orderParams']['takeProfit3']
        would_close, _, closed_tp3 = check_would_close(current_price, position_type, threshold_low, threshold_high,
                                                       close="TP3")
        if would_close:
            if closed_tp3:
                position['status'] = 'CLOSED_TP3'
            else:
                position['status'] = 'CLOSED_PROTECCION_23'


    close_status = "Would Close" if would_close else "Would Not Close"

    if would_close:
        # Log the details
        logger.info(
            f"Symbol: {symbol}, Current Price: {current_price}, Position Status: {position['status']}, 'Low': {threshold_low}, 'High': {threshold_high}, Position Type: {position_type}, Status: {close_status}")
        # Send email notification
        email_subject = f"Position Alert for {symbol}"
        email_body = f"Symbol: {symbol}, Current Price: {current_price}, Position Status: {position['status']}, 'Low': {threshold_low}, 'High': {threshold_high}, Position Type: {position_type}, Status: {close_status}"
        send_email(email_subject, email_body)
        if position_type == "Short":
            quantity_to_buy = abs(position_amount)
            logger.info(f"Closing short position by buying {quantity_to_buy} {symbol}")
            time.sleep(1)
            close_position(position, position['accountNumber'], position['lastTransactionNumber'] + 1, position['status'])

        else:  # Long position
            logger.info(f"Closing long position by selling {position_amount} {symbol}")
            time.sleep(1)
            close_position(position, position['accountNumber'], position['lastTransactionNumber'] + 1, position['status'])
        bybit.get_all_open_positions(force_update=True)
