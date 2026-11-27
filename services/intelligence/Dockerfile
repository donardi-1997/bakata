FROM python:3.12-slim@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY intelligence /app/intelligence
COPY tests /app/tests
RUN mkdir -p /var/lib/bakata-intelligence && chown 65532:65532 /var/lib/bakata-intelligence && chmod 0700 /var/lib/bakata-intelligence
USER 65532:65532
CMD ["python", "-m", "intelligence"]
