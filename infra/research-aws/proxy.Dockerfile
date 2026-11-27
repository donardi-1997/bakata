# Separate proxy image: no WordPress, AWS SDK or secrets.
FROM python:3.12-slim@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b
WORKDIR /opt/bakata
COPY services/intelligence/intelligence/research_egress.py /opt/bakata/intelligence/research_egress.py
COPY services/intelligence/intelligence/research_proxy.py /opt/bakata/intelligence/research_proxy.py
COPY services/intelligence/intelligence/research_proxy_auth.py /opt/bakata/intelligence/research_proxy_auth.py
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 65534:65534
ENTRYPOINT ["python","-m","intelligence.research_proxy"]
