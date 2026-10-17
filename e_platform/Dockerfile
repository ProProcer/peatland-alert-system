# syntax=docker/dockerfile:1
FROM python:3.12-slim
WORKDIR /app
COPY contracts/requirements.txt /tmp/requirements.txt
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then \
      PIP_CERT=/run/secrets/proxy_ca python -m pip install --no-cache-dir -r /tmp/requirements.txt; \
    else \
      python -m pip install --no-cache-dir -r /tmp/requirements.txt; \
    fi
COPY contracts ./contracts
COPY a_data ./a_data
COPY b_model/mock_output.json ./b_model/mock_output.json
COPY c_agent ./c_agent
COPY d_frontend ./d_frontend
COPY e_platform ./e_platform
EXPOSE 8000
CMD ["sh", "-c", "python -m e_platform.prepare_demo && exec python -m e_platform.serve --host 0.0.0.0 --data-dir data/demo"]
