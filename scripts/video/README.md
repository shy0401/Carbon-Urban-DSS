# 사용 영상 만들기

`docs/USER_MANUAL.md` 부록 E의 사용 안내 영상을 다시 만드는 도구입니다. 영상 파일(mp4)은 크기가 커서 Git에 올리지 않습니다(`docs/video/`).

| 순서 | 어디서 | 명령 |
|---|---|---|
| 1. 대본·촬영 계획 | 아무 데서나 | `python scripts/video/spec.py build` → `lines.json`(나레이션), `capture.json`(촬영), `spec.json`(합성) |
| 2. 화면 촬영 | 자료를 가진 PC (서비스 켠 상태) | Playwright 컨테이너에서 `node video_capture.cjs` (`DSS_URL`, `PLAN`, `SHOT_DIR`). 줄마다 1920×1080 JPG와 강조 상자 `boxes.json`. 계획안·보고서를 만든 줄의 id는 `created-video.json`에 남기고 촬영 뒤 지움 |
| 3. 나레이션 | PC Docker | `docker build -t carbon-tts scripts/video/tts` → `docker run --rm -v <폴더>:/work carbon-tts python /work/tts.py /work/lines.json /work/out` (MeloTTS 한국어, Whisper로 받아쓰기 점검 `check.json`) |
| 4. 합성 | Python 3 + ffmpeg | `python scripts/video/render.py spec.json <촬영 폴더> <나레이션 폴더> <출력 폴더> --jobs 2` → `video.mp4`, `subtitles.srt` |

- 배경음악은 `music.py`가 직접 합성합니다(저작권 걱정 없는 원곡, 84 BPM, 나레이션 중에는 자동으로 낮춤).
- 촬영은 국토통계지도·선도소프트 100m·팀 변화 모델 패널과 그 레이어 줄을 숨기고 찍습니다. 숨김이 실패해 그런 패널이 보이면 그 줄은 저장하지 않습니다. 이 기능들은 영상에 설명 카드로만 들어갑니다.
