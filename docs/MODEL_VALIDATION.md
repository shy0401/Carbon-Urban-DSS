# 모델 방법과 검증

현재 서비스의 시나리오 모델은 월별 관측kWh/매칭된 연면적을 사용하는 `INTENSITY_ESTIMATE`다. 학습된 AI 예측으로 부르지 않는다. 기준연면적 또는 에너지가 없으면 값을 만들지 않는다.

추가 비교는 에너지원별 최소120 관측,10개 격자,3개2km 공간 블록,10개 월을 갖춘 자료에서만 실행한다. 이 문턱은 최소 안전장치이며 검증 정확도 보증이 아니다. 전체 건물면적을 임의의 관측 부분집합 분모로 사용하지 않는다.

비교 후보는 월별 원단위 기준, ElasticNet, RandomForestRegressor, HistGradientBoostingRegressor, spline+Ridge 가산모형이다. 공간 블록 GroupKFold를 사용하고 전처리는 각 학습 fold에서만 적합한다. 검증 대상은 보류한 공간 블록이며 학습 정확도를 성공 기준으로 사용하지 않는다.

지표는 kWh로 환산한 MAE,RMSE,R²,NMAE,sMAPE다. NMAE와 sMAPE는0–1 비율이며 상수 관측에서R²는 미정의/null이다. 실제 실행 결과만 `model_runs`에 저장한다.

```powershell
docker compose exec api python -m app.cli validate-models --year 2025
```

실제 사용량 자료가 없거나 매칭표본이 부족하면 상태는 `INSUFFICIENT_TRAINING_DATA`, 지표는 null이다. 입력 변수 후보 중 자료가 없는 인구·세대·연령·층수·FAR·BCR를 조작해 넣지 않는다. 상세 상태는 `/model` 및 최종 실행 보고서를 참조한다.
