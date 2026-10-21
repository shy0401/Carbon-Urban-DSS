# 팀 변화 모델 서비스(urban-carbon 7차). 팀 코드·자료는 이미지에 넣지 않고 data/raw/team_urban_carbon을 읽기 전용으로 붙인다.
# 의존성은 팀 pyproject.toml(requires-python >=3.12, numpy 2, pandas 3, scikit-learn 1.7+)과 같은 범위.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN pip install "numpy>=2.0,<3" "pandas>=3.0,<4" "scikit-learn>=1.7,<2" "PyYAML>=6.0,<7" "pyshp>=3.1,<4" "pytest>=9,<10"
WORKDIR /app
COPY server.py /app/server.py
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8090/health',timeout=4)"
CMD ["python", "/app/server.py"]
