FROM python:3.12-slim

WORKDIR /srv

COPY app/requirements.txt app/requirements.txt
RUN pip install --no-cache-dir -r app/requirements.txt

COPY app app
COPY idl idl

CMD ["python", "-m", "app.indexer"]
