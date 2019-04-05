import asyncio
import os
import unittest
from unittest.mock import (
    patch,
)

import aiohttp
from aiohttp import web

import proxy


def async_test(func):
    def wrapper(*args, **kwargs):
        future = func(*args, **kwargs)
        loop = asyncio.get_event_loop()
        loop.run_until_complete(future)
    return wrapper


class TestHttpWebsocketsProxy(unittest.TestCase):

    def add_async_cleanup(self, coroutine):
        loop = asyncio.get_event_loop()
        self.addCleanup(loop.run_until_complete, coroutine())

    @patch.dict(os.environ, {'PORT': '8000', 'UPSTREAM_ROOT': 'http://localhost:9000'})
    @async_test
    async def test_happy_path_behaviour(self):
        """Asserts on almost all of the happy path behaviour of the proxy
        """
        loop = asyncio.get_event_loop()

        # Start the proxy
        proxy_future = loop.run_in_executor(None, proxy.main)

        async def cleanup_proxy():
            proxy_future.cancel()
            await asyncio.sleep(0)
        self.add_async_cleanup(cleanup_proxy)

        # Start the upstream echo server
        async def handle_http(request):
            data = {
                'method': request.method,
                'content': (await request.read()).decode(),
                'headers': dict(request.headers),
            }
            return web.json_response(data, status=405, headers={
                'from-upstream': 'upstream-header-value',
            })

        upstream = web.Application()
        upstream.add_routes([
            # Using patch as it's one that can be forgotten about
            web.patch('/http', handle_http),
        ])
        upstream_runner = web.AppRunner(upstream)
        await upstream_runner.setup()
        upstream_site = web.TCPSite(upstream_runner, '0.0.0.0', 9000)
        await upstream_site.start()

        # There doesn't seem to be a way to wait for uvicorn start
        await asyncio.sleep(1)

        # Make a request to the proxy
        async with aiohttp.ClientSession() as session:
            sent_content = 'Some content'
            sent_headers = {
                'from-downstream': 'downstream-header-value',
            }
            async with session.request(
                    'PATCH', 'http://localhost:9000/http',
                    data=sent_content, headers=sent_headers) as response:
                received_content = await response.json()
                received_headers = response.headers

        # Assert that we received the echo
        self.assertEqual(received_content['method'], 'PATCH')
        self.assertEqual(received_content['headers']['from-downstream'], 'downstream-header-value')
        self.assertEqual(received_content['content'], 'Some content')
        self.assertEqual(received_headers['from-upstream'], 'upstream-header-value')
