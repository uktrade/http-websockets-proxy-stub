# http-websockets-proxy-stub [![CircleCI](https://circleci.com/gh/uktrade/http-websockets-proxy-stub.svg?style=svg)](https://circleci.com/gh/uktrade/http-websockets-proxy-stub) [![Test Coverage](https://api.codeclimate.com/v1/badges/99f8b4689729734f7464/test_coverage)](https://codeclimate.com/github/uktrade/http-websockets-proxy-stub/test_coverage)

A stub HTTP and websockets proxy. This is designed as starting point for projects that need to proxy and intercept such requests; for example to check authentication, send HTTP redirects, or show temporary "loading" pages. It is expected to be used in projects where the proxy should have no knowledge of which path is HTTP, or which path is Websockets.

There are no "hooks" offered: the code must be directly incorporated into the relevant codebase. A "hookable" proxy that is re-usable in various situations is not part of the scope.


## Usage

To proxy `http://localhost:8000` to `http://localhost:8888`, with Redis already running locally:

```bash
pip install -r requirements.txt
PORT=8000 \
  UPSTREAM_ROOT=http://localhost:8888 \
  SSO_CLIENT_ID=some-client \
  SSO_CLIENT_SECRET=some-secret \
  SSO_BASE_URL=https://sso.base \
  REDIS_URL=redis://localhost:6379 \
  python3 proxy.py
```
