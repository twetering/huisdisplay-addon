# Plain Python image: wheels exist for every dependency on arm64 and amd64.
FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY fonts ./fonts
COPY firmware ./firmware
COPY hub ./hub
CMD ["python", "-m", "hub.server"]
