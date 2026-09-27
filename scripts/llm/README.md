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

새 모델의 응답 오류가 줄고 `pass_rate`가 같거나 높을 때만 `.env`에 `OLLAMA_NARRATIVE_MODEL=carbon-area-narrator`를 넣고 api·worker를 다시 만듭니다(`docker compose ... up -d --force-recreate --no-deps api worker`). `compose.yaml`이 이 값을 읽습니다.

- `OLLAMA_NARRATIVE_MODEL`: 지역 보고서의 **요약 문단**을 쓰는 모델. 학습·평가한 작업이 이것뿐이므로 학습 모델은 여기에만 씁니다.
- `OLLAMA_MODEL`: 격자 보고서의 **근거 ID 선택**(다른 작업)에 쓰는 모델. 학습 모델로 바꾸지 않습니다(그 작업으로 평가하지 않았음).

되돌리려면 `OLLAMA_NARRATIVE_MODEL` 줄을 지우고 api·worker를 다시 만들면 됩니다 (요약도 `OLLAMA_MODEL`, 기본 `qwen2.5:1.5b`).

## 6GB GPU(RTX 2060)에서 Docker로 학습하기 (2026-09-27, 실제 실행)

PC에 파이썬이 없어도 Docker Desktop의 GPU 지원(WSL2)으로 학습합니다. `data/ops/claude-runner/train.sh`·`convert.sh`가 그 절차입니다.

```powershell
docker run --rm --gpus all -v "${PWD}:/work" -v claude-hf-cache:/root/.cache -w /work pytorch/pytorch:2.4.1-cuda12.4-cudnn9-runtime bash -lc "pip install -q 'transformers>=4.46,<5' 'peft>=0.13' 'accelerate>=0.34' safetensors sentencepiece 'bitsandbytes>=0.43' gguf; python scripts/llm/train_lora.py --data data/llm/area-narrative --out scripts/llm/out --epochs 2 --batch 1 --accum 16 --load-4bit"
```

- `--load-4bit`: 기본 가중치를 4bit(QLoRA)로 올립니다. 학습 뒤 CPU에서 fp16 기본 모델에 어댑터를 합칩니다.
- 손실은 답변 토큰 위치의 logits만 계산합니다(`logits_to_keep`). 152k 어휘 × 1,250 토큰 logits 3벌이 6GB를 넘겨 첫 스텝이 진행되지 않던 문제의 해결책입니다.
- 실측: 예시 8개 연습 실행에서 스텝(4예시)당 31초. 본 학습(319예시 × 2 epoch, 유효 배치 16 → 40스텝)은 3시간 6분(11,138초, 스텝당 약 80초)이 걸렸습니다.
- GGUF 변환은 같은 컨테이너에서 llama.cpp `convert_hf_to_gguf.py`(q8_0)로 하고, `docker compose cp`로 Ollama 컨테이너에 넣어 `ollama create` 합니다.

## 상태 (2026-09-27)

- 학습 자료: PC DB로 `llm-dataset --from 2015 --to 2025` → 학습 319, 평가 54 (관측 연도 2024·2025).
- 기준 모델 `qwen2.5:1.5b` 평가(54개): 통과 45, 불합격 1(근거에 없는 숫자), 응답 오류 8(JSON 파싱 실패). 통과율(응답 중) 97.8%. 응답 시간 중앙값 23초(CPU Ollama).
- QLoRA 학습(2026-09-27 01:41~04:51 KST, RTX 2060 6GB): Qwen2.5-1.5B-Instruct, LoRA rank 16, lr 2e-4, 2 epoch. 학습 손실 4.09 → 0.17, 평가 손실 0.0188(1 epoch) → 0.0110(2 epoch).
- 변환·등록: GGUF q8_0 1.65GB, Ollama 모델 `carbon-area-narrator:latest`.
- 학습 모델 평가(같은 54개, 학습에 쓰지 않은 지역): **통과 54, 불합격 0, 응답 오류 0**. 통과율 100%. 응답 시간 중앙값 20.5초(최대 31초, CPU Ollama).
- 기준 모델의 응답 오류 8개는 모두 JSON 파싱 실패(`JSONDecodeError`)였고, 학습 모델은 0개입니다.
- 판정: 기준(응답 오류 감소·통과율 유지 이상)을 만족해 PC `.env`에 `OLLAMA_NARRATIVE_MODEL=carbon-area-narrator`를 넣고 적용했습니다. 근거 ID 선택(`OLLAMA_MODEL`)은 `qwen2.5:1.5b` 그대로입니다.
- 적용 후 실제 앱 확인(2026-09-27 09:20 KST, PC DB·Ollama, `POST /api/area-reports`, 목표 40%): 덕진구 금암1동·금암2동·덕진동 3개 모두 `LOCAL_SLM_NARRATIVE`(숫자 검증 위반 0). 응답 시간은 첫 요청 65초(모델 적재), 이후 28초.
- 한계: 학습·평가 예시의 정답은 계산 엔진의 근거 문장을 이어 붙인 서식 문단입니다. 그래서 학습 모델은 근거 문장을 거의 그대로 골라 잇는 **추출형** 요약을 씁니다. 숫자 검증은 통과하지만 자유로운 해설 문장이 늘어난 것은 아니며, 평가 지역도 같은 전주 자료에서 나왔습니다. 다른 도시나 새 근거 유형에서는 다시 평가해야 합니다. 앱은 어느 모델이든 숫자·증감 방향이 근거와 다르면 게시하지 않고 검증된 서식으로 바꿉니다.
