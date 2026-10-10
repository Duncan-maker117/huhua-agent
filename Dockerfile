FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8765

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./backend/app
COPY backend/main.py ./backend/main.py
COPY backend/scripts ./backend/scripts
COPY web ./web
COPY data/sample_resume.json data/jargon_dict.csv data/tech_terms.txt ./data/
COPY data/jianlimoban/capacity.json ./data/jianlimoban/capacity.json
COPY data/jianlimoban/html-template ./data/jianlimoban/html-template

RUN groupadd --gid 10001 huhua \
    && useradd --uid 10001 --gid huhua --create-home huhua \
    && mkdir -p /var/lib/huhua /app/backend/data \
    && chown -R huhua:huhua /var/lib/huhua /app/backend/data

WORKDIR /app/backend
USER huhua
EXPOSE 8765
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
