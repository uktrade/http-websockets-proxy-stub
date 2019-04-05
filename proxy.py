import asyncio
import os
import urllib.parse

import aiohttp
import uvicorn

MAX_CHUNK_SIZE = 65536


async def proxy(upstream_root, session, scope, receive, send):
    path = scope['path']
    query = scope['query_string'].decode('utf-8')

    headers_from_downstream = [
        (str(key), str(value)) for (key, value) in scope['headers']
    ]

    if scope['type'] == 'http':
        await proxy_http(upstream_root, session, receive, send,
                         scope['method'], path, query, headers_from_downstream)
    elif scope['type'] == 'websocket':
        await proxy_websockets(upstream_root, session, receive, send,
                               path, query, headers_from_downstream)
    else:
        assert False


async def proxy_http(upstream_root, session, receive, send,
                     method, path, query, headers_from_downstream):
    async def yield_http_data():
        while True:
            event = await receive()
            yield event['body']
            if not event['more_body']:
                break

    upstream_url = upstream_root + path
    params = [
        (key, value)
        for key, values in urllib.parse.parse_qs(query).items()
        for value in values
    ]

    print('HTTP: connection from downstream')
    print('HTTP: uploading to upstream...')
    async with session.request(
            method, upstream_url, params=params,
            data=yield_http_data(), headers=headers_from_downstream) as response:
        print('HTTP: uploading to upstream... (done)')

        headers_from_upstream_str = response.headers.items()
        headers_from_upstream_bytes = [
            (key.encode(), value.encode()) for (key, value) in headers_from_upstream_str
        ]

        print('HTTP: sending headers to downstream...')
        await send({
            'type': 'http.response.start',
            'status': response.status,
            'headers': headers_from_upstream_bytes,
        })
        print('HTTP: sending headers to downstream... (done)')

        print('HTTP: sending data downstream...')
        try:
            while True:
                data = await response.content.read(MAX_CHUNK_SIZE)
                await send({
                    'type': 'http.response.body',
                    'body': data,
                    'more_body': True,
                })
                if not data:
                    break
            print('HTTP: sending data downstream... (done)')
        finally:
            print('HTTP: end of downstream HTTP response')
            await send({
                'type': 'http.response.body',
                'body': b'',
                'more_body': False,
            })

        print('HTTP: end of downstream HTTP response')

    print('HTTP: sending data downstream... (done)')


async def proxy_websockets(upstream_root, session, receive, send,
                           path, query, headers_from_downstream):

    print('Websockets: connection from downstream')

    async def upstream_reader(upstream_ws):
        async for msg in upstream_ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                await send({
                    'type': 'websocket.send',
                    'text': msg.data,
                })

            elif msg.type == aiohttp.WSMsgType.BINARY:
                await send({
                    'type': 'websocket.send',
                    'bytes': msg.data,
                })

            elif msg.type == aiohttp.WSMsgType.CLOSE:
                await send({
                    'type': 'websocket.close',
                })

            elif msg.type == aiohttp.WSMsgType.ERROR:
                await send({
                    'type': 'websocket.close',
                })

    async def downstream_reader(upstream_ws, upstream_reader_task):
        while True:
            event = await receive()
            if event['type'] == 'websocket.receive' and 'text' in event:
                await upstream_ws.send_str(event['text'])

            elif event['type'] == 'websocket.receive' and 'bytes' in event:
                await upstream_ws.send_bytes(event['text'])

            elif event['type'] == ('websocket.close', 'websocket.disconnect'):
                upstream_reader_task.cancel()
                break

    event = await receive()
    assert event['type'] == 'websocket.connect'

    upstream_url = upstream_root + path + (('?' + query) if query else '')
    async with session.ws_connect(upstream_url, headers=headers_from_downstream) as upstream_ws:
        await send({
            'type': 'websocket.accept',
            'subprotocol': upstream_ws.protocol,
        })

        upstream_reader_task = asyncio.ensure_future(upstream_reader(upstream_ws))
        await downstream_reader(upstream_ws, upstream_reader_task)

    await send({
        'type': 'websocket.close',
    })

    print('Websockets: end of connection from downstream')


def memoize(func):
    # MIT https://github.com/michalc/aiomemoize

    cache = {}

    async def cached(*args, **kwargs):
        key = (args, tuple(kwargs.items()))

        try:
            future = cache[key]
        except KeyError:
            future = asyncio.Future()
            cache[key] = future

            try:
                result = await func(*args, **kwargs)
            except BaseException as exception:
                del cache[key]
                future.set_exception(exception)
            else:
                future.set_result(result)

        return await future

    def invalidate(*args, **kwargs):
        key = (args, tuple(kwargs.items()))
        del cache[key]

    return cached, invalidate


def main():
    port = int(os.environ['PORT'])
    upstream_root = os.environ['UPSTREAM_ROOT']

    # The slightly convoluted startup is so
    #
    # - We can inject dynamic values into the handler, `proxy`
    #
    # - The session, which is the HTTP/websocket connection pool, must be
    #   created only once for an application, and must be created from the
    #   _same_ loop as its used. uvicorn makes its own loops, and offers no
    #   "init" callback, and so we pass a memoized getter to the handler
    async def _get_session():
        return aiohttp.ClientSession()
    get_session, _ = memoize(_get_session)

    async def _proxy(scope, receive, send):
        session = await get_session()
        return await proxy(upstream_root, session, scope, receive, send)

    uvicorn.run(
        _proxy,
        host='0.0.0.0', port=port, log_level='info',
    )


if __name__ == '__main__':
    main()
