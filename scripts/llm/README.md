# 로컬 보고서 작성 모델 학습 (지역 요약)

## 역할 나누기

| 누가 | 하는 일 |
|---|---|
| 계산 엔진 (`backend/app/area.py`) | 모든 숫자: 연도별 관측·추정, 개발 전후, 감축 노력 |
| 근거 문장 (`area_facts`) | 엔진 숫자를 담은 검증 문장 |
| 로컬 모델 (Ollama) | 근거 문장을 요약 문단으로 다시 쓰기만 함 |
| 검증기 (`verify_narrative`) | 모델 문장의 숫자·연도·증감 방향·금지 표현을 근거와 대조. 하나라도 다르면 게시하지 않고 검증된 서식으로 바꿈 |

학습은 모델이 근거를 더 잘 따라 쓰도록 해서 불채택(대체) 비율을 줄이는 일입니다. 보고서에 틀린 숫자가 실리지 않는 것은 학습이 아니라 검증기가 보장합니다.

## 1. 학습 자료 만들기 (PC, Docker)

과거 자료를 먼저 수집하면 관측 전후 비교 문장이 들어간 예시가 생깁니다.

```powershell
scripts\dss.cmd CollectHistory -FromYear 2015 -ToYear 2025
docker compose -p carbon-urban-dss -f compose.yaml -f compose.demo.yaml exec -T api python -m app.cli llm-dataset --from 2015 --to 2025
```

결과는 `data/llm/area-narrative/`에 생깁니다 (Git 제외).

- `train.jsonl`, `eval.jsonl`: `{"id", "messages": [system, user, assistant]}`. 평가 파일에는 `facts`도 들어 있습니다.
- `manifest.json`: 개수, 분할 규칙(지역 단위, 평가 15%), 프롬프트 해시, 수집 범위.

정답 문장은 엔진 근거 문장만 이어 붙여 만들고, 앱과 같은 검증기를 통과한 것만 넣습니다.

미리보기 DB(2025년 관측 3개 지번)로 만들었을 때는 학습 319개, 평가 54개였습니다. 실제 수치는 PC DB에 따라 달라집니다.

## 2. 현재 모델 기준 성능 재기

```powershell
scripts\setup-local-llm.ps1
docker compose -p carbon-urban-dss -f compose.yaml -f compose.demo.yaml --profile local-ai exec -T api python -m app.cli llm-eval --limit 40
```

결과는 `data/llm/area-narrative/eval-<모델>-<시각>.json`에 저장됩니다.

| 항목 | 뜻 |
|---|---|
| `pass` | 앱이 모델 문장을 그대로 게시 |
| `rejected` | 검증기가 막고 서식으로 대체 |
| `error` | 응답 없음 |

## 3. LoRA 학습 (GPU 컴퓨터 또는 Colab)

```powershell
python -m venv .venv-llm
.venv-llm\Scripts\activate
pip install -r scripts\llm\requirements.txt
python scripts\llm\train_lora.py --data data\llm\area-narrative --out scripts\llm\out
```

- 기본 모델: `Qwen/Qwen2.5-1.5B-Instruct` (현재 Ollama `qwen2.5:1.5b`와 같은 계열)
- 기본 설정: LoRA r=16, 3 epoch, 답변 부분만 손실 계산
- VRAM 8GB 이상 권장

결과물:

- `scripts/llm/out/adapter`
- `scripts/llm/out/merged`
- `scripts/llm/out/training.json`

`scripts/llm/out/`는 Git에서 제외됩니다.

## 4. GGUF 변환과 Ollama 등록

```powershell
git clone https://github.com/ggml-org/llama.cpp
pip install -r llama.cpp\requirements.txt
python llama.cpp\convert_hf_to_gguf.py scripts\llm\out\merged --outfile scripts\llm\out\carbon-area-narrator.gguf --outtype q8_0
copy scripts\llm\Modelfile scripts\llm\out\Modelfile
docker compose -p carbon-urban-dss -f compose.yaml -f compose.demo.yaml --profile local-ai cp scripts\llm\out ollama:/root/carbon-area-narrator
docker compose -p carbon-urban-dss -f compose.yaml -f compose.demo.yaml --profile local-ai exec -T ollama sh -c "cd /root/carbon-area-narrator && ollama create carbon-area-narrator -f Modelfile"
```

## 5. 비교 후 교체

```powershell
docker compose -p carbon-urban-dss -f compose.yaml -f compose.demo.yaml --profile local-ai exec -T api python -m app.cli llm-eval --model carbon-area-narrator
```

새 모델의 `pass_rate`가 기존보다 높을 때만 `.env`에 `OLLAMA_MODEL=carbon-area-narrator`를 넣고 런처를 다시 실행합니다. `compose.yaml`이 이 값을 읽습니다.

되돌리려면 그 줄을 지우면 됩니다 (기본 `qwen2.5:1.5b`).

## 상태 (2026-09-25)

- 자료 생성기(`llm-dataset`)와 평가(`llm-eval`)는 미리보기 DB와 단위 테스트로 확인했습니다.
- 실제 Ollama 모델을 대상으로 한 평가는 아직 하지 않았습니다.
- `train_lora.py`는 문법 검사만 했습니다. GPU가 없어 학습, GGUF 변환, Ollama 등록은 아직 실행하지 않았습니다.
