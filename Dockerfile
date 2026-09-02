FROM python:3.12-slim

WORKDIR /app

COPY webapp/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY webapp/app ./app/

ENV KEYBOT_DATA_DIR=/tmp/keybot_data
ENV PORT=8000

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
