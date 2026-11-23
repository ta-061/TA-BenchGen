FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY python-packages.txt /tmp/e12-python-packages.txt
RUN python -m pip install --no-cache-dir -c /tmp/e12-python-packages.txt libclang==18.1.1 openai==1.109.1 requests==2.32.5 tiktoken==0.12.0 tabulate==0.9.0 PyYAML==6.0.3
WORKDIR /workspace
