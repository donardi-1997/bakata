FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY intelligence /app/intelligence
COPY tests /app/tests
RUN mkdir -p /var/lib/bakata-intelligence && chown 65532:65532 /var/lib/bakata-intelligence && chmod 0700 /var/lib/bakata-intelligence
USER 65532:65532
CMD ["python", "-m", "intelligence"]
