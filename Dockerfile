FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt pyproject.toml ./
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY autoops ./autoops
COPY README.md PROJECT_TASKS.md ./

CMD ["python3", "-m", "autoops.main", "show health for checkout-service"]
