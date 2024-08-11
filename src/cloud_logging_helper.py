import logging
import sys


class CloudLoggingHandler(logging.Handler):
    def emit(self, record):
        message = self.format(record)
        print(message, file=sys.stderr)

def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    
    handler = CloudLoggingHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    
    logger.addHandler(handler)
    
    return logger