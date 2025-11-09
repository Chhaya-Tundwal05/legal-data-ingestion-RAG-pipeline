FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install torch CPU wheels first
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.3.0

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

CMD ["sleep", "infinity"]
