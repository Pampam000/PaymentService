FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml constraints.txt ./
COPY payment_service ./payment_service
RUN python -m pip install --no-cache-dir -c constraints.txt . \
    && useradd --system --uid 10001 --home-dir /nonexistent --no-create-home payment

USER 10001:10001
EXPOSE 8002
CMD ["uvicorn", "payment_service.main:app", "--host", "0.0.0.0", "--port", "8002"]
