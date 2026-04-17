FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir gunicorn

COPY . .

RUN mkdir -p data

EXPOSE 5110

CMD ["gunicorn", "--bind", "0.0.0.0:5110", "--workers", "2", "--timeout", "120", "app:app"]
