FROM python:3.12-slim

WORKDIR /work

COPY scripts/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

ENV PYTHONPATH=/work/scripts

CMD ["python", "scripts/e2e.py"]
