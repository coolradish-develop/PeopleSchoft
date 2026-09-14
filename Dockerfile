# PeopleSchoft - PeopleSoft HCM emulator for identity lifecycle demos (stdlib only, no pip installs)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PS_HOST=0.0.0.0 \
    PS_PORT=8080 \
    PS_DB_PATH=/app/data/peopleschoft.db

WORKDIR /app
COPY peopleschoft/ ./peopleschoft/
COPY scripts/ ./scripts/
COPY start.sh Makefile README.md .env.example ./

RUN mkdir -p /app/data && useradd --create-home --uid 10001 peoplesoft && chown -R peoplesoft:peoplesoft /app
USER peoplesoft

VOLUME ["/app/data"]
EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
  CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/v1/health', timeout=2).status == 200 else 1)"

# Seeds the GBI demo organisation on first start (the data volume keeps it between restarts).
CMD ["python3", "-m", "peopleschoft", "serve"]
