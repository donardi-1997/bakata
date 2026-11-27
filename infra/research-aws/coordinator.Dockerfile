# Build from repository root. Test-only, no live supplier client.
FROM python:3.12-slim@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b
WORKDIR /opt/bakata
COPY infra/research-aws/coordinator-requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --disable-pip-version-check --require-hashes --no-deps --only-binary=:all: -r /tmp/requirements.lock && rm /tmp/requirements.lock && mkdir /exchange && chown 33:33 /exchange && chmod 0700 /exchange
COPY services/intelligence/intelligence/ /opt/bakata/intelligence/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 33:33
VOLUME ["/exchange"]
ENTRYPOINT ["python","-m","intelligence.research_worker"]
