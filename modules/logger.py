"""
日誌模組 - 配置日誌系統
"""
import logging
from .config import DEBUG_MODE

def setup_logger():
    """設定日誌系統"""
    if DEBUG_MODE:
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
            handlers=[
                logging.FileHandler('debug.log', encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        print(f"🐛 DEBUG模式已啟用，詳細日誌將保存到 debug.log")
    else:
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

    logger = logging.getLogger(__name__)
    logger.info("=== 台股推薦機器人啟動 ===")
    logger.info(f"DEBUG_MODE: {DEBUG_MODE}")

    return logger

def get_logger(name=__name__):
    """取得 logger 實例"""
    return logging.getLogger(name)