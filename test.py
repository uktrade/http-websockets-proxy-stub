import asyncio
import json
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
        proxy_task = asyncio.ensure_future(proxy.async_main())

        async def cleanup_proxy():
            proxy_task.cancel()
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

        async def handle_websockets(request):
            wsock = web.WebSocketResponse()
            await wsock.prepare(request)

            await wsock.send_str(json.dumps(dict(request.headers)))

            async for msg in wsock:
                if msg.type == aiohttp.WSMsgType.CLOSE:
                    await wsock.close()
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await wsock.send_str(msg.data)
                if msg.type == aiohttp.WSMsgType.BINARY:
                    await wsock.send_bytes(msg.data)

            return wsock

        upstream = web.Application()
        upstream.add_routes([
            # Using patch as it's one that can be forgotten about
            web.patch('/http', handle_http),
            web.get('/websockets', handle_websockets),
        ])
        upstream_runner = web.AppRunner(upstream)
        await upstream_runner.setup()
        upstream_site = web.TCPSite(upstream_runner, '0.0.0.0', 9000)
        await upstream_site.start()

        # There doesn't seem to be a way to wait for uvicorn start
        await asyncio.sleep(1)

        # Make a http request to the proxy
        session = aiohttp.ClientSession()

        async def cleanup_session():
            await session.close()
            await asyncio.sleep(0.25)
        self.add_async_cleanup(cleanup_session)

        async def sent_content():
            for _ in range(10000):
                yield b'Some content'

        sent_headers = {
            'from-downstream': 'downstream-header-value',
        }
        async with session.request(
                'PATCH', 'http://localhost:8000/http',
                data=sent_content(), headers=sent_headers) as response:
            received_content = await response.json()
            received_headers = response.headers

        # Assert that we received the echo
        self.assertEqual(received_content['method'], 'PATCH')
        self.assertEqual(received_content['headers']['from-downstream'], 'downstream-header-value')
        self.assertEqual(received_content['content'], 'Some content'*10000)
        self.assertEqual(received_headers['from-upstream'], 'upstream-header-value')

        # Make a websockets connection to the proxy
        # (We deliberatly use the same session to ensure to assert on re-used connections)
        sent_headers = {
            'from-downstream-websockets': 'websockets-header-value',
        }
        async with session.ws_connect(
                'http://localhost:9000/websockets', headers=sent_headers) as wsock:
            msg = await wsock.receive()
            headers = json.loads(msg.data)

            await wsock.send_bytes(b'some-\0binary-data')
            msg = await wsock.receive()
            received_binary_content = msg.data

            await wsock.send_str('some-text-data')
            msg = await wsock.receive()
            received_text_content = msg.data

            await wsock.close()

        self.assertEqual(headers['from-downstream-websockets'], 'websockets-header-value')
        self.assertEqual(received_binary_content, b'some-\0binary-data')
        self.assertEqual(received_text_content, 'some-text-data')
