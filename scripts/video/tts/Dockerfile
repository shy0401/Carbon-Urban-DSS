# 사용 영상 나레이션용 한국어 TTS (MeloTTS, MIT) + 받아쓰기 점검(Whisper, MIT). 이 PC에서만 쓰는 도구 이미지.
FROM python:3.10-slim
ENV PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends git build-essential mecab libmecab-dev mecab-ipadic-utf8 ffmpeg \
    && rm -rf /var/lib/apt/lists/*
RUN pip install "numpy<2" torch==2.3.1 torchaudio==2.3.1 --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple
RUN pip install git+https://github.com/myshell-ai/MeloTTS.git
RUN pip install "numpy<2" python-mecab-ko
# openai-whisper 20240930의 setup.py는 pkg_resources가 필요하다(최신 setuptools에는 없음) → 옛 setuptools로 격리 없이 빌드
RUN pip install "setuptools<70" wheel && pip install --no-build-isolation "numpy<2" openai-whisper==20240930
RUN python -m unidic download
RUN python -c "from melo.api import TTS; TTS(language='KR', device='cpu')" && python -c "import whisper; whisper.load_model('small')"
WORKDIR /work
