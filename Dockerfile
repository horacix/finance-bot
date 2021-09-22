FROM python:3.9-bullseye

RUN python -m pip install --upgrade pip
RUN apt-get update && apt-get install -y --no-install-recommends libmariadb3 libmariadb-dev chromium-driver && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /app
WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY *.py *.yml ./
ENTRYPOINT [ "python", "mint.py" ]