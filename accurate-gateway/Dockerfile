FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

ENV GATEWAY_HOST=0.0.0.0
ENV GATEWAY_PORT=8091
ENV GATEWAY_MODE=fixture

EXPOSE 8091
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8091"]
