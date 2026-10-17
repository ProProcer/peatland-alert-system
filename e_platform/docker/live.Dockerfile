FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt constraints.txt ./
COPY contracts/requirements.txt contracts/requirements.txt
COPY a_data/requirements.txt a_data/requirements.txt
COPY b_model/requirements.txt b_model/requirements-training.txt b_model/
COPY e_platform/requirements-live.txt e_platform/requirements-live.txt
RUN python -m pip install --no-cache-dir -r e_platform/requirements-live.txt
COPY contracts ./contracts
COPY a_data ./a_data
COPY b_model ./b_model
COPY c_agent ./c_agent
COPY d_frontend ./d_frontend
COPY e_platform ./e_platform
# Real source data is mounted read-only; runtime output has a separate volume.
EXPOSE 8001
ENV OMP_NUM_THREADS=2 MKL_NUM_THREADS=2
CMD ["python", "-m", "e_platform.live_service", "--host", "0.0.0.0", "--port", "8001"]
