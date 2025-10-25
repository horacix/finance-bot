FROM python:3.12-slim-bullseye

RUN python -m pip install --upgrade pip
RUN mkdir -p /app
WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY *.py *.yml ./
ENTRYPOINT [ "python", "main.py" ]