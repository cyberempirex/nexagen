import logging
import logging.handlers

# Create a custom logger
logger = logging.getLogger('nexagen')
logger.setLevel(logging.DEBUG)  # Set the default logging level

# Create console handler and set level to debug
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)

# Create file handler and set level to info
fh = logging.handlers.RotatingFileHandler('nexagen.log', maxBytes=10**6, backupCount=5)
fh.setLevel(logging.INFO)

# Create formatter
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Add formatter to handlers
ch.setFormatter(formatter)
fh.setFormatter(formatter)

# Add handlers to logger
logger.addHandler(ch)
logger.addHandler(fh)