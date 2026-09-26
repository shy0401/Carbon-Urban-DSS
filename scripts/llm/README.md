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

## 6GB GPU(RTX 2060)에서 Docker로 학습하기 (2026-09-27, 실제 실행)

PC에 파이썬이 없어도 Docker Desktop의 GPU 지원(WSL2)으로 학습합니다. `data/ops/claude-runner/train.sh`·`convert.sh`가 그 절차입니다.

```powershell
docker run --rm --gpus all -v "${PWD}:/work" -v claude-hf-cache:/root/.cache -w /work pytorch/pytorch:2.4.1-cuda12.4-cudnn9-runtime bash -lc "pip install -q 'transformers>=4.46,<5' 'peft>=0.13' 'accelerate>=0.34' safetensors sentencepiece 'bitsandbytes>=0.43' gguf; python scripts/llm/train_lora.py --data data/llm/area-narrative --out scripts/llm/out --epochs 2 --batch 1 --accum 16 --load-4bit"
```

- `--load-4bit`: 기본 가중치를 4bit(QLoRA)로 올립니다. 학습 뒤 CPU에서 fp16 기본 모델에 어댑터를 합칩니다.
- 손실은 답변 토큰 위치의 logits만 계산합니다(`logits_to_keep`). 152k 어휘 × 1,250 토큰 logits 3벌이 6GB를 넘겨 첫 스텝이 진행되지 않던 문제의 해결책입니다.
- 실측: 예시 8개 연습 실행에서 스텝(4예시)당 31초. 319예시 × 2 epoch ≈ 1.5시간.
- GGUF 변환은 같은 컨테이너에서 llama.cpp `convert_hf_to_gguf.py`(q8_0)로 하고, `docker compose cp`로 Ollama 컨테이너에 넣어 `ollama create` 합니다.

## 상태 (2026-09-27)

- 학습 자료: PC DB로 `llm-dataset --from 2015 --to 2025` → 학습 319, 평가 54 (관측 연도 2024·2025).
- 기준 모델 `qwen2.5:1.5b` 평가(54개): 통과 45, 불합격 1(근거에 없는 숫자), 응답 오류 8(JSON 파싱 실패). 통과율(응답 중) 97.8%. 응답 시간 중앙값 23초(CPU Ollama).
- QLoRA 학습·GGUF 변환·Ollama 등록·평가를 PC에서 자동 실행합니다. 새 모델은 응답 오류가 줄고 통과율이 같거나 높을 때만 `.env`의 `OLLAMA_MODEL`로 씁니다.
