# encoding: utf-8

from .api import HttpRunner

try:
    # monkey patch at beginning to avoid RecursionError when running locust.

    # from gevent import monkey;monkey.patch_all()
    pass
except ImportError:
    pass
from httprunner.api import HttpRunner
