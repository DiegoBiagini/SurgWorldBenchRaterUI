FROM python:3.11-slim

# Host proxy (docker build --build-arg HTTP_PROXY --build-arg HTTPS_PROXY --build-arg NO_PROXY …)
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY
ARG http_proxy
ARG https_proxy
ARG no_proxy

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY run_human_rating.py run_aggregate_human_ratings.py ./
COPY harness/ harness/
COPY .streamlit/ .streamlit/

EXPOSE 8501

ENTRYPOINT ["python", "run_human_rating.py"]
