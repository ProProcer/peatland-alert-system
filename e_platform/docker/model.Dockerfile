# syntax=docker/dockerfile:1
FROM python:3.12-slim
WORKDIR /app
COPY b_model/requirements.txt /tmp/requirements.txt
COPY constraints.txt /tmp/constraints.txt
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then \
      PIP_CERT=/run/secrets/proxy_ca python -m pip install --no-cache-dir -c /tmp/constraints.txt -r /tmp/requirements.txt; \
    else \
      python -m pip install --no-cache-dir -c /tmp/constraints.txt -r /tmp/requirements.txt; \
    fi
COPY b_model ./b_model
COPY data/processed ./data/processed
CMD ["python", "-m", "b_model.predict", "--input", "data/processed/features.json", "--output", "data/demo/risk.json"]
