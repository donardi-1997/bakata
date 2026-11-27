# Build from repository root. Test-only, no live supplier client.
FROM python:3.12-slim
WORKDIR /opt/bakata
RUN pip install --no-cache-dir 'boto3>=1.36,<2' && mkdir /exchange && chown 33:33 /exchange && chmod 0700 /exchange
COPY services/intelligence/intelligence/ /opt/bakata/intelligence/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 33:33
VOLUME ["/exchange"]
ENTRYPOINT ["python","-m","intelligence.research_worker"]
