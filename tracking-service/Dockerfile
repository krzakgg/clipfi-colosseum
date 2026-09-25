FROM python:3.12-slim

RUN useradd --create-home --uid 10001 app
WORKDIR /app

COPY pyproject.toml ./
COPY tracking ./tracking
RUN pip install --no-cache-dir .

USER app
EXPOSE 8000

# h11 instead of httptools: httptools has no header size limit.
# No access log: it would contain visitor IPs.
CMD ["uvicorn", "tracking.app:app", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--http", "h11", "--h11-max-incomplete-event-size", "16384", \
     "--no-proxy-headers", "--no-server-header", "--no-access-log"]
