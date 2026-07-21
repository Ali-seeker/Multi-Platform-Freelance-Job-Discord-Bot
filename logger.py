import logging
import os
from logging.handlers import RotatingFileHandler

def get_logger(name: str) -> logging.Logger:
    """
    Returns a configured logger with both stream and file handlers.
    Creates the logs/ directory if it doesn't exist.
    """
    logger = logging.getLogger(name)
    
    # If already configured, return it
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    
    # Detailed formatter for file
    file_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    
    # Clean formatter for terminal
    console_formatter = logging.Formatter('%(message)s')

    # Stream Handler (Terminal)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(console_formatter)
    logger.addHandler(stream_handler)

    # File Handler (logs/bot.log)
    log_dir = os.path.join(os.path.dirname(__file__), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    
    log_file = os.path.join(log_dir, 'bot.log')
    # Using RotatingFileHandler to prevent log file from growing infinitely
    file_handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    return logger
