FROM python:3-alpine

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /app/defaults && cp -r /app/data/* /app/defaults/

RUN chmod +x entrypoint.sh

ENTRYPOINT ["/bin/sh", "/app/entrypoint.sh"]

CMD ["python", "main.py"]
