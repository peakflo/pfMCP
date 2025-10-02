FROM python:3.10.12

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD python -m memory_profiler ./src/servers/main.py --port ${PORT}