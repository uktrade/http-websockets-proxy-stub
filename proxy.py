import asyncio
import logging
import os
import sys

import aiohttp
from aiohttp import web
from yarl import (
    URL,
)


async def async_main():
    stdout_handler = logging.StreamHandler(sys.stdout)
    for logger_name in ['aiohttp.server', 'aiohttp.web', 'aiohttp.access']:
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.DEBUG)
        logger.addHandler(stdout_handler)

    port = int(os.environ['PORT'])
    upstream_root = os.environ['UPSTREAM_ROOT']
    client_session = aiohttp.ClientSession()

    def without_transfer_encoding(headers):
        return {
            key: value for key, value in headers.items()
            if key.lower() != 'transfer-encoding'
        }

    async def handle(downstream_request):
        upstream_url = URL(upstream_root) \
            .with_path(downstream_request.url.path) \
            .with_query(downstream_request.url.query)
        is_websocket = \
            downstream_request.headers.get('connection', None) == 'Upgrade' and \
            downstream_request.headers.get('upgrade', None) == 'websocket'
        return \
            await handle_websocket(upstream_url, downstream_request) if is_websocket else \
            await handle_http(upstream_url, downstream_request)

    async def handle_websocket(upstream_url, downstream_request):

        async def on_msg(msg, to_ws):
            if msg.type == aiohttp.WSMsgType.TEXT:
                await to_ws.send_str(msg.data)

            elif msg.type == aiohttp.WSMsgType.BINARY:
                await to_ws.send_bytes(msg.data)

            elif msg.type == aiohttp.WSMsgType.CLOSE:
                await to_ws.close()

            elif msg.type == aiohttp.WSMsgType.ERROR:
                await to_ws.close()

        async with client_session.ws_connect(
                str(upstream_url),
                headers=without_transfer_encoding(downstream_request.headers)
        ) as upstream_ws:
            downstream_ws = web.WebSocketResponse()
            await downstream_ws.prepare(
                downstream_request,
            )

            async def ws_proxy(from_ws, to_ws):
                async for msg in from_ws:
                    await on_msg(msg, to_ws)

            upstream_reader_task = asyncio.ensure_future(ws_proxy(downstream_ws, upstream_ws))
            await ws_proxy(upstream_ws, downstream_ws)
            upstream_reader_task.cancel()

        return downstream_ws

    async def handle_http(upstream_url, downstream_request):
        async with client_session.request(
                downstream_request.method, str(upstream_url),
                params=downstream_request.url.query,
                headers=without_transfer_encoding(downstream_request.headers),
                data=downstream_request.content,
        ) as upstream_response:

            downstream_response = web.StreamResponse(
                status=upstream_response.status,
                headers=without_transfer_encoding(upstream_response.headers)
            )
            await downstream_response.prepare(downstream_request)
            while True:
                chunk = await upstream_response.content.readany()
                if chunk:
                    await downstream_response.write(chunk)
                else:
                    break

        return downstream_response

    app = web.Application()
    app.add_routes([
        getattr(web, method)(r'/{path:.*}', handle)
        for method in ['delete', 'get', 'head', 'options', 'patch', 'post', 'put']
    ])

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    await asyncio.Future()


def main():
    loop = asyncio.get_event_loop()
    loop.create_task(async_main())
    loop.run_forever()


if __name__ == '__main__':
    main()
