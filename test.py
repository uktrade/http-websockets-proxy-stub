import asyncio
import unittest

import proxy


def async_test(func):
    def wrapper(*args, **kwargs):
        future = func(*args, **kwargs)
        loop = asyncio.get_event_loop()
        loop.run_until_complete(future)
    return wrapper


class TestHttpWebsocketsProxy(unittest.TestCase):

    @async_test
    async def test_happy_path_behaviour(self):
        """Asserts on almost all of the happy path behaviour of the proxy
        """

        loop = asyncio.get_event_loop()

        # Start the proxy
        loop.run_in_executor(None, proxy.main)
