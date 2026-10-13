FROM python:3.13-slim

RUN useradd --create-home --uid 10001 app
WORKDIR /app

COPY pyproject.toml ./
COPY waggi_auth ./waggi_auth
COPY waggi_shared ./waggi_shared
RUN pip install --no-cache-dir .

USER app
EXPOSE 8001

# Keys are mounted at runtime (JWT_PRIVATE_KEY_PATH / JWT_PUBLIC_KEY_PATH).
CMD ["uvicorn", "waggi_auth.main:app", "--host", "0.0.0.0", "--port", "8001", \
     "--proxy-headers"]
