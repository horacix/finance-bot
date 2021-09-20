FROM python:3.6-buster

RUN python -m pip install --upgrade pip
RUN apt-key adv --recv-keys --keyserver keyserver.ubuntu.com 0xcbcb082a1bb943db
RUN curl -LsS https://downloads.mariadb.com/MariaDB/mariadb_repo_setup | bash
RUN apt-get update && apt-get install -y --no-install-recommends libmariadb3 libmariadb-dev chromium-driver && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /app
WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY *.py *.yml ./
ENTRYPOINT [ "python", "mint.py" ]