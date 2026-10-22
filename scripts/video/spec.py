"""사용 영상 대본·촬영 계획 한 곳에: python spec.py → lines.json(TTS), capture.json(PC 촬영), spec.json(합성).

각 줄(line)은 나레이션 한 문장 묶음 + 그때 보여 줄 화면 하나.
- say: TTS가 읽을 글(숫자·영문은 한글 읽기), sub: 자막(화면 표기 그대로)
- card: 화면 대신 그림 카드(제목·안내·제한 자료 설명). 촬영하지 않음
- url/scope/actions/scroll/focus: PC 촬영 지시(focus 상자를 강조하고 그쪽으로 확대)
- pre: 동작 전 화면을 먼저 찍어, 영상에서 '누르는 동작'(커서·물결) 뒤 바뀐 화면으로 넘어감
"""
import json
import sys

J01 = "/area?region=52110&area=admin:35012650&from=2015&to=2025&window=3&plan=90000&target=20&basis=apartments&mx=30,10,2000"
SCOPE_JEONJU = {"year": 2025, "gridId": "cell_968500_1762000", "region": None}
HIDE_NOTE = "국토통계지도·선도소프트·팀 변화 모델 화면은 반출 제한으로 영상에 싣지 않음"

L = []


def line(id, say, sub=None, **kw):
    L.append({"id": id, "say": say, "sub": sub or say, **kw})


# ── 0. 인트로 ──────────────────────────────────────────────
line("c00_01", "카본 어반 디에스에스 사용 안내 영상입니다.", "Carbon Urban DSS 사용 안내",
     card={"kind": "title", "title": "Carbon Urban DSS", "subtitle": "사용 안내 영상", "foot": "도시 탄소 의사결정 지원 도구 · 2026-10"})
line("c00_02", "이 도구는 공공기관이 공개한 건물 에너지 관측값으로 도시의 운영 탄소를 계산하고, 개발 계획이 탄소를 얼마나 바꾸는지 미리 보는 의사결정 지원 도구입니다.",
     "공공기관이 공개한 건물 에너지 관측값으로 도시의 운영 탄소를 계산하고, 개발 계획이 탄소를 얼마나 바꾸는지 미리 봅니다.",
     url="/", scope=SCOPE_JEONJU, actions=[{"waitFor": ".metric-card"}, {"wait": 2500}])
line("c00_03", "켜고 끄는 방법부터 화면 구성, 지도와 대시보드, 지역 시뮬레이션, 삼차원 계획안, 보고서, 자료 수집까지 모든 메뉴를 차례로 살펴보겠습니다.",
     "켜기·끄기 → 화면 구성 → 지도·대시보드 → 지역 시뮬레이션 → 3D 계획안 → 보고서 → 자료 수집",
     card={"kind": "chapters", "title": "이 영상에서 다루는 것", "items": [
         "켜기·끄기와 접속", "화면 구성과 값 읽는 법", "전국 지역", "지도 분석", "대시보드 · 분석 · 모델",
         "지역 시뮬레이션", "시뮬레이션 (3D 계획안)", "검토 보고서", "수집 데이터", "사용 방법과 마무리"]})

# ── 1. 켜기·끄기 ───────────────────────────────────────────
line("c01_01", "바탕화면의 카본 디에스에스 켜기 버튼을 누르면 도커와 서비스가 차례로 올라옵니다. 이삼 분 뒤 이 컴퓨터의 브라우저에서 로컬호스트 오천백칠십삼 번으로 접속합니다.",
     "바탕화면 [Carbon DSS 켜기] → 2~4분 뒤 브라우저에서 http://localhost:5173",
     card={"kind": "power", "chapter": "1. 켜기·끄기와 접속", "focus": "on"})
line("c01_02", "밖에서 볼 때는 깃허브 페이지 안내 주소 하나만 알리면 됩니다. 이 주소가 그때그때 바뀌는 시연 서버로 연결해 주고, 시연 계정으로 로그인해야 합니다.",
     "밖에서는 안내 주소 https://shy0401.github.io/Carbon-Urban-DSS/ 하나만 알리면 됩니다 (시연 계정 로그인)",
     card={"kind": "power", "chapter": "1. 켜기·끄기와 접속", "focus": "pages"})
line("c01_03", "다 쓰면 끄기 버튼을 누릅니다. 데이터베이스를 안전하게 멈춘 뒤 도커를 끕니다. 자료를 수집하는 동안에는 끄지 말고 켜 둡니다.",
     "[Carbon DSS 끄기]: DB를 안전하게 멈추고 Docker를 끕니다. 수집 중에는 켜 둡니다.",
     card={"kind": "power", "chapter": "1. 켜기·끄기와 접속", "focus": "off"})

# ── 2. 화면 구성 ───────────────────────────────────────────
line("c02_01", "왼쪽은 메뉴입니다. 전국 지역부터 사용 방법까지 열 개의 화면이 있습니다.", "왼쪽 메뉴: 화면 10개",
     url="/", scope=SCOPE_JEONJU, actions=[{"waitFor": ".metric-card"}, {"wait": 1500}], focus="aside.sidebar nav", chapter="2. 화면 구성과 값 읽는 법")
line("c02_02", "위쪽 표제란에는 지금 보고 있는 분석 지역, 분석 연도, 격자 크기, 선택 격자, 최근 수집일, 온라인 모드가 늘 표시됩니다.",
     "표제란: 분석 지역 · 분석연도 · 격자 · 선택 격자 · 최근 수집일 · 모드", focus=".title-block-wrap")
line("c02_03", "오른쪽 위에서 시도와 시군구, 분석 연도를 고르면 모든 화면이 그 지역과 연도 기준으로 함께 바뀝니다. 기본 대상지로 버튼은 그 지역의 기본 격자로 돌아갑니다.",
     "시·도 → 시·군·구 → 분석연도를 고르면 모든 화면이 함께 바뀝니다", focus=".scope-controls")
line("c02_04", "값마다 실측, 계산, 추정, 시나리오 같은 배지가 붙습니다. 관측이 없는 값은 영으로 채우지 않고, 빗금과 자료 없음으로 표시합니다.",
     "값의 종류 배지: 실측 · 계산 · 추정 · 시나리오. 관측 없는 값은 0이 아니라 빗금·'자료 없음'",
     focus="section[aria-label=\"핵심 지표 8개\"]")

# ── 3. 전국 지역 ───────────────────────────────────────────
line("c03_01", "전국 지역 화면에서는 전국 시군구의 인구와 주택 개요를 지도와 표로 봅니다. 위쪽 카드는 전국 공통 자료의 범위입니다.",
     "전국 지역: 전국 시·군·구 개요와 전국 공통 자료 범위", url="/regions", actions=[{"waitFor": ".national-figure"}, {"wait": 6000}],
     focus=".national-figure >> xpath=..", chapter="3. 전국 지역")
line("c03_02", "색 기준을 바꾸면 인구밀도, 가구, 공동주택 단지 수 같은 지표로 지도를 다시 칠합니다.", "지도 색 기준 바꾸기",
     focus=".regions-map-panel")
line("c03_03", "오른쪽 목록은 상세 자료를 준비한 지역과 그 상태입니다. 지역을 누르면 인구와 주택 요약, 준비 단계가 보입니다.",
     "준비한 지역과 상태 → 지역을 누르면 요약과 준비 단계", pre=True,
     actions=[{"click": ".ready-list button:has-text(\"완주군\")"}, {"wait": 3000}],
     focus=".region-detail")
line("c03_04", "아직 준비하지 않은 시군구는 상세 자료 수집을 눌러 격자, 행정동, 용도지역, 건물, 건축물대장, 에너지 자료를 차례로 모읍니다. 처음 고르기만 해도 전국 공통 자료로 기본 지도를 몇 초 안에 만듭니다.",
     "새 시·군·구: 처음 고르면 기본 지도(몇 초), '상세 자료 수집'으로 에너지·건물·용도지역까지", scroll=".region-detail .step-list", focus=".region-detail")

# ── 4. 지도 분석 ───────────────────────────────────────────
line("c04_01", "지도 분석은 세 단계입니다. 첫째, 전국 보기에서 시도를 지도나 왼쪽 목록에서 고르고 시도끼리 비교합니다.",
     "지도 분석 ① 전국 · 시·도 선택", url="/map?view=national", actions=[{"waitFor": ".map-views"}, {"wait": 12000}],
     focus=".map-views", chapter="4. 지도 분석")
line("c04_02", "시도를 고르면 그 안의 시군구가 칠해지고, 시군구를 누르면 요약을 본 뒤 그 지도로 들어갑니다.",
     "시·도를 고르면 시·군·구가 칠해지고, 누르면 요약 → 그 지도로", url="/map?view=national&sido=52",
     actions=[{"waitFor": ".map-views"}, {"wait": 12000}])
line("c04_03", "둘째, 시도 오백 미터 격자 보기는 시도 전체를 공식 오백 미터 격자로 나눠 인구와 주택 같은 전국 공통 지표로 칠합니다.",
     "② 시·도 500m 격자: 전국 공통 지표", url="/map?view=province&sido=52", actions=[{"waitFor": ".map-views"}, {"wait": 15000}])
line("c04_04", "셋째, 시군구 보기에서는 분석 격자와 읍면동을 봅니다. 왼쪽 위에서 지도 지표를 고르고, 범례에는 구간별 격자 수와 자료 미확보 격자가 따로 나옵니다.",
     "③ 시·군·구 · 읍면동: 지표 고르기, 범례(구간별 격자 수 · 자료 미확보)", url="/map?view=region", scope=SCOPE_JEONJU,
     actions=[{"mapReady": True}, {"wait": 3000}], focus=".map-rail")
line("c04_05", "지표는 전력, 가스, 탄소, 원단위, 인구, 밀도, 용적률, 용도지역처럼 묶음별로 나뉘고, 각 지표의 정의와 산식, 활용법을 범례에서 펼쳐 볼 수 있습니다.",
     "지표 묶음: 에너지 · 탄소 · 원단위 · 인구 · 밀도 · 용도지역 …", pre=True,
     actions=[{"click": ".metric-trigger"}, {"wait": 1200}], focus=".metric-picker")
line("c04_06", "레이어 버튼으로 건물, 공동주택 단지, 용도지역, 행정동 경계를 겹쳐 봅니다. 겹쳐 보기는 한 번에 하나씩 켜집니다.",
     "레이어: 건물 · 단지 · 용도지역 · 행정동 (겹쳐 보기는 하나씩)", pre=True,
     actions=[{"click": ".metric-trigger"}, {"wait": 600}, {"click": "button.tool-button:has-text(\"레이어\")"}, {"wait": 1500}], focus=".map-tools")
line("c04_07", "격자를 누르면 오른쪽에 격자 상세가 열립니다. 연간 전력과 가스, 원단위, 탄소, 건물 수, 건폐율과 용적률이 근거와 함께 나오고, 이 격자가 모든 분석 화면의 대상지가 됩니다.",
     "격자 상세: 지표 8개와 근거 · 이 격자가 모든 화면의 대상지",
     actions=[{"selectGrid": "cell_966500_1764500"}, {"wait": 4000}], focus=".map-detail")
line("c04_08", "읍면동을 고르거나 동별 비교를 누르면 격자 지표를 동 단위로 모아 나란히 비교합니다.", "읍면동 · 동별 비교", pre=True,
     actions=[{"click": "button.tool-button:has-text(\"동별 비교\")"}, {"wait": 3000}], focus=".dong-panel")
line("c04_09", "이 컴퓨터에서만 보이는 기능도 있습니다. 국토통계지도 백 미터 격자, 선도소프트 탄소공간지도 백 미터 전기 배출, 팀 변화 모델의 개발 변화 예측입니다. 반출이 제한된 자료라 공개 주소와 이 영상에는 실제 화면을 싣지 않습니다.",
     "이 PC에서만: 100m 격자(국토통계지도) · 100m 전기 배출(선도소프트) · 개발 변화 예측(팀 변화 모델)",
     card={"kind": "restricted", "chapter": "4. 지도 분석", "items": [
         ["100m 격자 (국토통계지도)", "레이어에서 켜고 확대(13 이상) → 인구·건물·연면적·사용승인연도로 칠함, 격자 상세에 5×5 = 25칸"],
         ["100m 전기 배출 (탄소공간지도, 선도소프트)", "전주 2023·2024 건물 전기 배출(tCO₂eq), 지역 시뮬의 기준 건물 '탄소공간지도 100m'"],
         ["개발 변화 예측 (팀 변화 모델 7차)", "53개 지역 500m 칸: 신축·철거 연면적 → 배출 변화(tCO₂e/년)와 80% 구간"]],
           "foot": "국외 반출 금지·이용 조건 확인 전 자료 → 공개 시연 주소와 이 영상에는 실제 화면을 싣지 않습니다"})

# ── 5. 대시보드 ────────────────────────────────────────────
line("c05_01", "대시보드는 선택 격자의 핵심 지표를 카드로 보여 줍니다. 전력과 가스 사용량, 전력 탄소, 원단위, 세대당 전력, 건폐율, 추정 용적률, 주거지역 비율입니다.",
     "대시보드: 선택 격자의 핵심 지표 8개", url="/", scope=SCOPE_JEONJU, actions=[{"waitFor": ".metric-card"}, {"wait": 2500}],
     focus="section[aria-label=\"핵심 지표 8개\"]", chapter="5. 대시보드 · 분석 · 모델")
line("c05_02", "카드 아래에는 산식과 근거 범위가 붙어 있어, 숫자가 어떤 지번과 몇 개월 관측에서 나왔는지 바로 확인할 수 있습니다.",
     "카드마다 산식과 근거 범위", focus=".metric-card:nth-child(3)")
line("c05_03", "아래로 내리면 월별 관측 에너지와 관측 범위, 건물 용도 구성, 공동주택 단지, 행정동과 인구 정보가 이어집니다.",
     "월별 관측 에너지 · 관측 범위 · 건물 용도 · 단지 · 행정동", scroll=".chart-panel", focus=".dashboard-grid")
line("c05_04", "분석 화면은 난방도일과 월별 에너지, 행정동 인구, 분석 격자 안 용도지역 면적, 포함된 자료 출처를 함께 보여 줘 해석의 범위를 판단하게 합니다.",
     "분석: 난방도일 · 행정동 인구 · 용도지역 면적 · 자료 출처", url="/analysis", scope=SCOPE_JEONJU, actions=[{"wait": 8000}])
line("c05_05", "모델 화면은 전력과 가스 원단위 모델을 공간 블록 교차검증으로 평가한 결과입니다. 관측이 기준보다 적으면 성능을 만들지 않고 학습 자료 부족으로 표시합니다.",
     "모델: 공간 블록 교차검증 · 관측 부족이면 '학습 자료 부족'", url="/model", actions=[{"wait": 6000}])
line("c05_06", "아래에서는 건축허브 합계를 한전 시군구 전력 같은 공식 통계와 맞대어 보고, 어느 쪽도 정답으로 보지 않고 차이와 그 까닭을 함께 봅니다.",
     "공식 통계와 맞대기: 건축HUB ↔ 한전 시군구 전력", scroll="h3:has-text(\"공식 통계와 맞대기\")", focus="section:has(h3:has-text(\"공식 통계와 맞대기\")), .panel:has(h3:has-text(\"공식 통계와 맞대기\"))")

# ── 6. 지역 시뮬레이션 ─────────────────────────────────────
line("c06_01", "지역 시뮬레이션은 이 도구의 중심 기능입니다. 행정동, 반경, 직접 그리기, 용도지역, 기준 격자의 다섯 가지 방법으로 구역을 고릅니다.",
     "지역 시뮬레이션: 구역 고르기 5가지 (행정동 · 반경 · 직접 그리기 · 용도지역 · 기준 격자)", url=J01, scope=SCOPE_JEONJU,
     actions=[{"waitFor": "[data-testid=\"area-summary\"]"}, {"wait": 4000}], focus="#area-step-area", chapter="6. 지역 시뮬레이션")
line("c06_02", "예를 들어 전주 덕진구 송천일동을 고르고, 이천십오년부터 이천이십오년까지를 봅니다. 아래에는 이 구역에 어떤 연도의 자료가 출처별로 있는지 나옵니다.",
     "예: 전주 덕진구 송천1동, 2015~2025 → 출처별 자료 연도", focus=".area-coverage, .area-collect")
line("c06_03", "결과 요약 막대는 화면을 내려도 머리 아래에 붙어 있습니다. 구역, 기준 배출, 계획 반영 배출, 필요 감축량, 감축 수단 조합, 같은 시군 행정동 비교 순위를 한눈에 보고, 번호를 누르면 그 단계로 이동합니다.",
     "결과 요약 막대: 기준 배출 · 계획 반영 · 필요 감축량 · 수단 조합 · 행정동 비교 (단계 ①~⑤)", focus="[data-testid=\"area-summary\"]")
line("c06_04", "구역 지도에는 공동주택 단지가 개발 연도 기준으로 색이 나뉘고, 연도 슬라이더나 재생 버튼으로 해마다 단지가 들어서는 모습을 봅니다.",
     "구역 지도와 연도 슬라이더 · 재생", scroll=".area-map-stage", focus=".area-map-stage")
line("c06_05", "아래 차트는 연도별 전력 사용량, 사용승인 세대, 기상, 인구입니다. 관측이 없는 해는 빗금으로, 관측 단지가 적은 해는 일부 단지로 표시해 사용량이 줄어든 것처럼 읽히지 않게 합니다.",
     "과거와 현재: 연도별 전력 · 개발 이력 · 기상 · 인구 (관측 없음 · 일부 단지는 빗금)", scroll="h3:has-text(\"연도별 전력 사용량\")",
     focus=".panel:has(h3:has-text(\"연도별 전력 사용량\"))")
line("c06_06", "건물 전체 에너지 표는 건축허브 계측값입니다. 공동주택만이 아니라 상가와 업무 건물까지 포함하고, 같은 지번끼리 비교한 변화도 함께 나옵니다.",
     "건물 전체 에너지 (건축HUB): 상가·업무 포함, 같은 지번끼리 비교", scroll="section[aria-label=\"건물 전체 에너지\"]",
     focus="section[aria-label=\"건물 전체 에너지\"]")
line("c06_07", "개발 전후 영향에서는 개발 연도를 고르고 앞뒤 몇 년의 평균을 비교합니다. 관측 범위가 달라 비교하기 어려운 값은 흐리게 하고 비교 주의를 붙입니다.",
     "개발 전후 영향: 개발 연도 앞뒤 평균 비교, 비교 어려운 값은 '비교 주의'", scroll=".area-before-after", focus=".area-before-after")
line("c06_08", "미래 개발과 감축 노력에 추가할 연면적과 목표 감축률, 기준 건물을 넣으면, 목표를 지키기 위한 필요 감축량과 지역 전체 효율 개선률, 재생에너지 상쇄량, 태양광 설비 용량을 계산합니다.",
     "미래 개발과 감축 노력: 필요 감축량 · 효율 개선률 · 재생에너지 상쇄 · 태양광 kW", scroll="#area-step-plan", focus=".area-effort-layout")
line("c06_09", "기준 건물은 주거지에서는 공동주택, 상가와 업무가 많은 곳에서는 건물 전체를 고릅니다. 고른 기준에 근거가 없으면 다른 기준으로 자동 전환하고 알려 줍니다.",
     "기준 건물: 공동주택(K-apt) / 건물 전체(건축HUB) — 근거가 없으면 자동 전환", focus="[aria-label=\"감축 노력 기준 건물\"]")
line("c06_10", "같은 시군의 행정동과 원단위를 비교해 이 구역이 낮은 쪽부터 몇 번째인지 보여 줍니다. 등급이 아니라 같은 시군 안의 위치입니다.",
     "같은 시·군 행정동 비교: 원단위 순위(등급 아님)", scroll="section[aria-label=\"같은 시·군·구 행정동 비교\"]", focus="section[aria-label=\"같은 시·군·구 행정동 비교\"]")
line("c06_11", "감축 수단 조합에는 신축 절감률, 기존 건물 절감률, 태양광 용량을 함께 넣어 필요 감축량을 채우는지 확인합니다. 남은 양을 태양광으로 채우기 버튼도 있습니다.",
     "감축 수단 조합: 신축 % + 기존 건물 % + 태양광 kW → 필요 감축량 대비", scroll="#area-step-measures", focus="section[aria-label=\"감축 수단 조합\"]")
line("c06_12", "시나리오 저장으로 여러 안을 저장하면 최대 네 개를 나란히 비교하고, 엑셀에서 여는 씨에스브이 파일로 내보낼 수 있습니다.",
     "시나리오 저장 → 최대 4개 비교 · CSV 내보내기",
     actions=[{"click": "[data-testid=\"area-summary\"] button:has-text(\"시나리오 저장\")"}, {"wait": 1200},
              {"fill": ["input[aria-label=\"목표 감축률\"]", "30"]}, {"wait": 6000},
              {"click": "[data-testid=\"area-summary\"] button:has-text(\"시나리오 저장\")"}, {"wait": 1500}],
     scroll="#area-step-compare", focus="[data-testid=\"area-compare\"]")
line("c06_13", "마지막 단계에서 보고서를 작성합니다. 보고서의 숫자는 모두 계산 엔진의 근거 문장에서만 가져오고, 인쇄하거나 피디에프로 저장할 수 있습니다.",
     "보고서: 숫자는 계산 엔진 근거 문장에서만 · 인쇄·PDF", scroll="#area-step-report", focus=".area-report-form, #area-step-report")
line("c06_14", "링크 복사를 누르면 구역과 입력이 담긴 주소가 복사돼, 다른 사람도 같은 조건으로 바로 열 수 있습니다. 링크로 분석 지역이 바뀌면 화면 위에 알림과 되돌리기 버튼이 나옵니다.",
     "링크 복사: 같은 조건으로 다시 열기 · 링크가 지역을 바꾸면 알림과 되돌리기", url="/simulation?region=52710", scope={"year": 2025, "gridId": None, "region": None},
     actions=[{"waitFor": "[data-testid=\"linked-region-notice\"]"}, {"wait": 2500}], focus="[data-testid=\"linked-region-notice\"]")

# ── 7. 시뮬레이션 (3D) ─────────────────────────────────────
SIM = ("/simulation?region=52110&grid=cell_966500_1764500&year=2025&site=127.132190,35.880124,0&site_area=40000&building_count=10"
       "&footprint_per_building=600&floors=15&households=1000&population=2500&efficiency_factor=0.8&pv_ratio=0.15&green_ratio=0.3"
       "&average_household_area=84&min_households=900&min_population=2200")
line("c07_01", "시뮬레이션 화면에서는 대지 하나에 건물 배치안을 놓고 삼차원으로 봅니다. 왼쪽에 대지 면적, 건물 수, 동별 건축면적, 층수, 세대수와 인구, 효율 계수와 태양광 대체율을 넣습니다.",
     "시뮬레이션: 개발 조건 입력 (대지·규모·세대·효율·태양광)", url=SIM, scope={"year": 2025, "gridId": "cell_966500_1764500", "region": None},
     actions=[{"waitFor": ".massing-3d-canvas"}, {"wait": 12000}], focus=".scenario-form", chapter="7. 시뮬레이션 (3D 계획안)")
line("c07_02", "층수 빠른 설정 버튼은 연면적과 평균 세대면적으로 세대수를 다시 계산합니다.", "층수·수용량 빠른 설정", focus=".floor-presets")
line("c07_03", "오른쪽 삼차원 화면에서는 조감, 평면, 남측 투시 시점과 탑상형, 판상형 배치, 동 간격과 배치 방향을 바꾸고, 동지와 하지의 시각별 그림자를 봅니다.",
     "3D: 시점 · 동 형태 · 간격 · 방향 · 일조(동지·춘분·하지, 시각)", focus=".massing-panel")
line("c07_04", "대지 옮기기를 누르고 지도를 클릭하면 대지가 그 위치로 옮겨지고, 그 자리의 용도지역과 조례 상한을 바로 다시 확인합니다.",
     "대지 옮기기 → 그 자리의 용도지역 · 조례 상한 1차 확인", scroll=".massing-zoning", focus=".massing-zoning")
line("c07_05", "시나리오 계산을 누르면 연간 운영탄소, 기준안 대비 절감률, 일인당과 세대당 탄소, 조례 상한 일차 확인이 나옵니다.",
     "시나리오 계산 → 연간 운영탄소 · 기준안 대비 절감률 · 1인당 탄소 · 상한 확인", pre=True,
     actions=[{"click": "button:has-text(\"시나리오 계산\")"}, {"waitFor": ".hero-main"}, {"wait": 4000}], scroll=".hero-main", focus=".hero-main",
     record="scenario")
line("c07_06", "아래에는 계획안과 기준안의 전력, 가스, 탄소 표와 월별 운영탄소 그래프, 산정 방법과 가정이 이어집니다.",
     "계획안 ↔ 기준안 표 · 월별 운영탄소 · 산정 방법과 가정", scroll=".energy-table", focus=".energy-table")
line("c07_07", "도시구조 최적화에 최소 세대수와 인구를 넣고 최적안 탐색을 누르면, 법적 상한 안에서 탄소가 가장 적은 안과 수용량이 가장 큰 안을 찾아 줍니다.",
     "도시구조 최적화: 상한 안에서 탄소 최소 · 세대당 최소 · 수용량 최대", pre=True,
     actions=[{"scrollTo": ".optimization-panel"}, {"click": "button:has-text(\"최적안 탐색\")"}, {"waitFor": ".optimization-results"}, {"wait": 2500}],
     scroll=".optimization-panel", focus=".optimization-panel")
line("c07_08", "보고서 작성을 누르면 삼차원 장면을 저장하고, 이 계획안의 보고서를 바로 엽니다.", "보고서 작성 → 3D 장면 저장 후 보고서로",
     pre=True, actions=[{"scrollTo": ".hero-main"}, {"click": "button:has-text(\"보고서 작성\")"}, {"waitFor": "h2:has-text(\"1.\"), .report-section"}, {"wait": 5000}],
     record="report", chapter="8. 검토 보고서")

# ── 8. 검토 보고서 ─────────────────────────────────────────
line("c08_01", "보고서는 핵심 결과, 대상지 개요, 계획 개요, 에너지와 탄소 산정, 용도지역과 조례 상한, 유의사항, 자료 출처의 일곱 절로 구성됩니다.",
     "보고서 7절: 핵심 결과 · 대상지 · 계획 · 산정 · 상한 · 유의사항 · 출처", scroll=".report-section", focus="main")
line("c08_02", "검토 보고서 화면에서는 같은 대상지의 계획안을 최대 세 개까지 골라 비교 보고서를 만들고, 문서 내려받기와 인쇄를 할 수 있습니다. 계획안 없이 현황 보고서만 쓸 수도 있습니다.",
     "계획안 최대 3개 비교 · 문서 내려받기 · 인쇄 · 현황 보고서", scrollY=0)
line("c08_03", "로컬 에이아이로 요약 문장 고르기를 켜도, 숫자는 모두 계산 엔진에서만 가져옵니다. 에이아이 문장의 숫자나 연도가 근거와 하나라도 다르면 검증된 서식으로 바꿉니다.",
     "로컬 AI 요약도 숫자는 계산 엔진에서만 — 다르면 검증된 서식으로", focus="label:has-text(\"로컬 AI\")")

# ── 9. 수집 데이터 ─────────────────────────────────────────
line("c09_01", "수집 데이터 화면에서는 빠진 자료 전부 수집 버튼 한 번으로 아직 없는 연도와 자료를 모두 받습니다. 이미 있는 자료와 키가 없는 자료는 건너뜁니다.",
     "빠진 자료 전부 수집: 버튼 한 번, 있는 자료·키 없는 자료는 건너뜀", url="/data", scope={"year": 2025, "gridId": None, "region": None},
     actions=[{"waitFor": "#collect-missing"}, {"wait": 5000}], focus="#collect-missing", chapter="9. 수집 데이터")
line("c09_02", "연도별 표는 완료, 수집 예정, 다시 시도, 미공표, 그리고 인증키나 승인이 필요한 경우를 색으로 나눕니다. 건축허브는 이천이십년부터 제공되고, 이천이십오년 에스지아이에스 인구는 아직 공표 전입니다.",
     "연도별 상태: 완료 · 수집 예정 · 다시 시도 · 미공표 · 키·승인 필요", scroll=".missing-table", focus=".missing-table")
line("c09_03", "일일 호출 한도에 걸리면 다음 날 영시 이십 분에 자동으로 이어서 받습니다. 그동안 컴퓨터와 도커가 켜져 있어야 합니다.",
     "일일 한도 → 다음 날 00:20 자동 재개 (PC·Docker 켜 두기)", focus="#collect-missing")
line("c09_04", "머리에서 다른 시군구를 고르면, 그 지역의 연도별 수집 진행표가 함께 나옵니다.", "다른 시·군·구: 지역별 연도 수집 진행",
     url="/data", scope={"year": 2025, "gridId": None, "region": "52710"}, actions=[{"waitFor": "[data-testid=\"region-year-progress\"]"}, {"wait": 3000}],
     focus="[data-testid=\"region-year-progress\"]")
line("c09_05", "아래에는 출처별 상태 카드와 수동 수집 양식, 파일 업로드가 있습니다. 파일은 원본 그대로 두고 열 매핑과 기준 기간을 확인한 뒤 가져옵니다.",
     "출처별 상태 · 수동 수집 · 파일 업로드(원본 보존, 열 매핑 확인)", scroll=".source-cards", focus=".source-cards")

# ── 10. 사용 방법·마무리 ───────────────────────────────────
line("c10_01", "사용 방법 화면에는 이 영상의 내용과 데이터 기준, 인증키 설정, 로컬 에이아이, 문제 해결이 정리되어 있습니다.",
     "사용 방법: 화면 안내 · 데이터 기준 · 인증키 · 로컬 AI · 문제 해결", url="/guide", scope={"year": 2025, "gridId": None, "region": None},
     actions=[{"wait": 2500}], chapter="10. 사용 방법과 마무리")
line("c10_02", "같은 코드와 같은 자료, 같은 입력이면 어느 컴퓨터에서나 같은 숫자가 나오도록 자료 묶음과 사례 검증 명령을 함께 제공합니다. 자세한 내용은 사용설명서를 참고하세요. 감사합니다.",
     "같은 코드 + 같은 자료 + 같은 입력 = 같은 숫자 · 자세한 내용은 사용설명서(docs/USER_MANUAL.md)",
     card={"kind": "end", "title": "Carbon Urban DSS", "lines": ["사용설명서  docs/USER_MANUAL.md", "자료 범위  docs/DATA_COVERAGE.md",
                                                               "저장소  github.com/shy0401/Carbon-Urban-DSS", "안내 주소  shy0401.github.io/Carbon-Urban-DSS"]})

if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    json.dump([{"id": x["id"], "text": x["say"]} for x in L], open(f"{out}/lines.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    keys = ("id", "url", "scope", "actions", "scroll", "scrollY", "focus", "pre", "record")
    json.dump([{k: x[k] for k in keys if k in x} for x in L if "card" not in x], open(f"{out}/capture.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(L, open(f"{out}/spec.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    chars = sum(len(x["say"]) for x in L)
    print(len(L), "lines,", sum(1 for x in L if "card" not in x), "captured,", chars, "chars (~", round(chars / 7.0 / 60, 1), "min at 7 chars/s)")
