"""배출계수: 전력은 GIR 승인 계수(원문 증빙 확인), 도시가스는 고정 규칙으로 정한 가정 계수.

도시가스 규칙 (가정, 화면·보고서에 '가정'으로 표시):
  IPCC 2006 기본 배출계수(천연가스, 가정·상업) CO₂ 56,100 · CH₄ 5 · N₂O 0.1 kg/TJ, GWP(AR5) CH₄ 28 · N₂O 265
  → 56,266.5 kgCO₂eq/TJ(순발열량) = 0.20256 kgCO₂eq/kWh(순발열량 기준 kWh).
  건축HUB 가스 kWh는 도시가스 요금 기준인 총발열량 열량을 kWh로 바꾼 값이라고 가정하고, 에너지법 시행규칙
  별표의 도시가스(LNG) 순/총발열량 38.5/42.7 MJ/Nm³로 맞춰 0.20256 × 38.5/42.7 = 0.1826 kgCO₂eq/kWh.
  순발열량 기준 kWh라면 0.2026(약 +10.9%)입니다. 공식 가스 계수가 등록되면 그 계수가 이 규칙을 대신합니다.
"""
import json
from .models import EmissionFactor,DataSource
from .collectors import RAW,record_asset,update_source,client

GIR_URL='https://www.gir.go.kr/home/board/read.do?boardId=82&boardMasterId=2&menuId=36'
IPCC_URL='https://www.ipcc-nggip.iges.or.jp/public/2006gl/vol2.html'
GAS_FACTOR_ID='rule-city-gas-ipcc2006-gcv'
GAS_NCV_FACTOR=round((56100+5*28+0.1*265)*3.6e-6,5)      # 0.20256 kgCO2eq/kWh (순발열량 기준 kWh)
GAS_FACTOR=round(GAS_NCV_FACTOR*38.5/42.7,4)              # 0.1826 kgCO2eq/kWh (총발열량 기준 kWh, 적용값)
GAS_FACTOR_NOTE=('가정 계수(고정 규칙): IPCC 2006 천연가스 기본 배출계수 CO2 56,100·CH4 5·N2O 0.1 kg/TJ, AR5 GWP(28·265) → 56,266.5 kgCO2eq/TJ. '
                 '건축HUB 가스 kWh를 총발열량 기준으로 보고 에너지법 시행규칙 도시가스 순/총발열량 38.5/42.7 MJ/Nm3로 환산. '
                 f'순발열량 기준이면 {GAS_NCV_FACTOR:.4f}(+10.9%). 공식 가스 계수 등록 시 대체.')

def ensure_gas_factor(db):
    """Register the fixed city-gas rule once (an official GAS factor with a later reference year takes precedence)."""
    db.merge(EmissionFactor(id=GAS_FACTOR_ID,energy_type='GAS',factor=GAS_FACTOR,factor_unit='kgCO2eq/kWh',reference_year=2006,
                            source='도시가스 가정 계수 (IPCC 2006 기본 배출계수 × 에너지법 시행규칙 발열량)',source_url=IPCC_URL,
                            effective_from='2000-01-01',notes=GAS_FACTOR_NOTE))
    db.commit()
    return GAS_FACTOR

def collect_factors(db):
    path=RAW/'research'/'gir_2024_approved_electricity_factors.pdf'
    evidence=RAW/'research'/'gir_2024_approved_electricity_factors.txt'
    if not path.exists() or not evidence.exists():
        source=db.get(DataSource,'factors');source.status='MANUAL_DOWNLOAD_REQUIRED';source.source_url=GIR_URL;source.quality='GIR 원문 PDF와 검증 텍스트 필요';db.commit();return 0
    text=evidence.read_text(encoding='utf-8')
    if not all(s in text for s in ['0.4541','소비단','2024']):raise ValueError('배출계수 증빙 불일치')
    db.merge(EmissionFactor(id='gir-2024-approved-consumption',energy_type='ELECTRICITY',factor=.4541,factor_unit='kgCO2eq/kWh',reference_year=2024,source='GIR 2024 승인 국가 온실가스 배출계수 / 소비단',source_url=GIR_URL,effective_from='2025-03-31',notes='공표일 2025-03-31; 통계기간 2020–2022. 별도 법적 발효일 미제시. 2025 전체 비교에 회고적으로 동일 계수를 적용하는 프로젝트 방법이며, 2025 실측 전력계통 계수라는 뜻이 아님. tCO2eq/MWh = kgCO2eq/kWh.'))
    record_asset(db,'factors',{'path':str(path),'url':GIR_URL,'timestamp':path.stat().st_mtime},1,'2024 승인 /2020–2022 통계/2025-03-31 공표')
    source=db.get(DataSource,'factors');source.source_url=GIR_URL;source.reference_period='2024 승인 / 2025-03-31 공표';source.limitation=f'전기 소비단 0.4541 kgCO2eq/kWh (GIR 승인). 도시가스는 고정 규칙의 가정 계수 {GAS_FACTOR} kgCO2eq/kWh (IPCC 2006 기본값, 총발열량 기준 kWh 가정; 순발열량이면 {GAS_NCV_FACTOR:.4f}).'
    ensure_gas_factor(db)
    update_source(db,'factors',2,2,status='PARTIAL',quality='전기 GIR 승인 계수 / 가스 가정 계수(IPCC 2006, 공식 계수 확인 필요)',missing=0)
    return 1
