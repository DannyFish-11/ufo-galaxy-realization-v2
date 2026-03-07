FROM python:3.11-slim

WORKDIR /app

# 安装 Tesseract OCR（降级引擎）及多语言包
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    tesseract-ocr-chi-tra \
    tesseract-ocr-jpn \
    tesseract-ocr-kor \
    libtesseract-dev \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
RUN pip install --no-cache-dir \
    aiohttp \
    Pillow \
    pytesseract \
    httpx

COPY . .

EXPOSE 8015

RUN addgroup --system --gid 1000 galaxy && adduser --system --uid 1000 --ingroup galaxy --no-create-home galaxy
RUN chown -R galaxy:galaxy /app
USER galaxy

CMD ["python", "main.py"]
