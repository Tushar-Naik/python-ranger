import logging
import sys


def default_serialize_func(o):
    """
    Use like this: logging.debug(f"print this object: {json.dumps(myobject, indent=4, sort_keys=True, default=default_serialize_func)}")
    """
    if hasattr(o, '__dict__'):
        return o.__dict__
    return f"<could not serialize {o.__class__}>"


def get_default_logger():
    logger = logging.getLogger('ranger')
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    formatter = logging.Formatter('[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s')
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    logger.setLevel(logging.INFO)
    return logger
