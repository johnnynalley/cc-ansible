FROM python:3-alpine

RUN apk add --no-cache ffmpeg

USER 1000:1000
