ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}
WORKDIR /app
COPY benchmark_service.py bench_control.py wireless_medium.py medium_control.py /app/
ENV PYTHONUNBUFFERED=1 PORT=8080 HTTP_TIMEOUT_SECONDS=3.0 FORWARD_TIMEOUT_SECONDS=5.0
EXPOSE 8080
CMD ["python", "/app/benchmark_service.py"]
