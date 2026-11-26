FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY intelligence /app/intelligence
COPY tests /app/tests
USER 65532:65532
CMD ["python", "-m", "intelligence"]
