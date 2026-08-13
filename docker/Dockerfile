FROM python:3.12-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

RUN addgroup -S relay && adduser -S -G relay relay

WORKDIR /app
COPY src/ /app/src/

USER relay
EXPOSE 8080

ENTRYPOINT ["python", "-m", "asterisk_webhook_relay"]
