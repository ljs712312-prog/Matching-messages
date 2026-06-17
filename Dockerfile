FROM mcr.microsoft.com/playwright/python:v1.59.0-noble

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 10000

CMD streamlit run app.py --server.address 0.0.0.0 --server.port ${PORT:-10000}

