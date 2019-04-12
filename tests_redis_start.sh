#!/bin/bash -xe

docker run --rm --name proxy-stub-redis -d -p 6379:6379 redis:4.0.10
