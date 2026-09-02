FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Cache buster: invalidate layers below when build is run
ARG BUILD_TIMESTAMP=unknown
RUN echo "Build timestamp: $BUILD_TIMESTAMP"

COPY app/ ./app/

ENV KEYBOT_DATA_DIR=/data
ENV PORT=8000

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Force rebuild trigger - App version update
ENV APP_BUILD_DATE="2026-09-02-19-30"
