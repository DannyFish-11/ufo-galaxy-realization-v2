FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8113

RUN addgroup --system --gid 1000 galaxy \
    && adduser --system --uid 1000 --ingroup galaxy --no-create-home galaxy \
    && chown -R galaxy:galaxy /app
USER galaxy

CMD ["python", "main.py"]
