# Separate proxy image: no WordPress, AWS SDK or secrets.
FROM python:3.12-slim
WORKDIR /opt/bakata
COPY services/intelligence/intelligence/research_egress.py /opt/bakata/intelligence/research_egress.py
COPY services/intelligence/intelligence/research_proxy.py /opt/bakata/intelligence/research_proxy.py
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 65534:65534
ENTRYPOINT ["python","-m","intelligence.research_proxy"]
