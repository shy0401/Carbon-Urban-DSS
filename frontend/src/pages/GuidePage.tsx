import { AlertTriangle, BookOpen, CheckCircle2, ChevronRight, Info } from 'lucide-react';
import { useEffect, type ReactNode } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { PageHeader } from '../components/PageHeader';
import { ProvenanceBadge } from '../components/ProvenanceBadge';
import { MAP_LAYERS } from '../lib/mapLayers';
import { METRIC_GROUPS, METRICS } from '../lib/mapMetrics';

/** 목차: 해시(#id)로 바로 열 수 있다. 다른 화면의 "사용 방법" 링크가 이 id를 쓴다. */
export const GUIDE_SECTIONS = [
  ['start', '처음 시작하기'],
  ['screens', '화면 구성'],
  ['nation', '전국 지역·지역 준비'],
  ['map-info', '지도 정보와 활용'],
  ['rules', '값 읽는 법'],
  ['area', '지역 시뮬레이션'],
  ['grid', '격자 분석·계획안·검토 보고서'],
  ['collect', '자료 수집'],
  ['sgis', 'SGIS 격자 통계 (1km)'],
  ['keys', '인증키 설정'],
  ['ai', '로컬 AI'],
  ['faq', '문제 해결'],
] as const;

function Section({ id, title, lead, children }: { id: string; title: string; lead?: string; children: ReactNode }) {
  return <section className="guide-section" id={id} aria-labelledby={`${id}-title`}>
    <h2 id={`${id}-title`}>{title}</h2>
    {lead && <p className="guide-lead">{lead}</p>}
    {children}
  </section>;
}

function Steps({ items }: { items: ReactNode[] }) {
  return <ol className="guide-steps">{items.map((item, i) => <li key={i}><b aria-hidden="true">{i + 1}</b><div>{item}</div></li>)}</ol>;
}

function Note({ tone = 'info', children }: { tone?: 'info' | 'warn' | 'good'; children: ReactNode }) {
  const Icon = tone === 'warn' ? AlertTriangle : tone === 'good' ? CheckCircle2 : Info;
  return <div className={`guide-note ${tone}`}><Icon size={16} aria-hidden="true" /><div>{children}</div></div>;
}

function Go({ to, children }: { to: string; children: ReactNode }) {
  return <Link className="guide-go" to={to}>{children}<ChevronRight size={14} aria-hidden="true" /></Link>;
}

const SCREENS: Array<[string, string, string, string]> = [
  ['/regions', '전국 지역', '전국 시·군·구의 인구·가구·밀도·공동주택 단지 수를 지도와 표로 보고, 분석할 지역을 골라 자료를 수집해 준비합니다.', '준비가 끝난 지역은 위쪽 "분석 지역"에서 고릅니다.'],
  ['/', '대시보드', '선택 격자의 관측 에너지·전력 탄소·도시 형태를 지표 카드와 월별 차트로 봅니다.', '값마다 산식과 근거 범위가 아래에 붙습니다.'],
  ['/map', '지도 분석', '1단계 전국: 지도에서 시·도를 누르거나 왼쪽 메뉴에서 골라 시·도끼리 비교하고(인구·밀도·가구·2015년 대비 인구 증감·주택·종사자·공동주택 단지), 고른 시·도의 시·군·구를 같은 지표로 봅니다. 시·군·구를 누르면 요약과 함께 그 지도로 들어갑니다. 2단계 시·도 500m 격자(제주 제외): 시·도 전체를 SGIS 500m 격자로 봅니다. 3단계 시·군·구·읍면동: 처음 여는 시·군·구는 전국 자료로 격자·읍면동을 몇 초 만에 만들고(기본 지도), 전주·수원처럼 상세 자료를 모은 곳은 에너지·탄소·건물·용도지역까지 봅니다. 읍면동을 고르면 격자 지표를 동 단위로 모으고 동별로 비교합니다.', '격자 색은 지표 하나만 칠합니다. 건물·단지·용도지역·행정동은 레이어의 겹쳐 보기에서 한 번에 하나씩 켭니다. 기본 지도에서 \'상세 자료 수집 시작\'을 누르면 그 지역의 에너지·건물 자료를 모읍니다.'],
  ['/analysis', '분석', '난방도일과 월별 에너지, 행정동 인구, 격자 내 용도지역 면적, 포함 출처를 봅니다.', '해석 범위를 판단하는 화면입니다.'],
  ['/model', '모델', '에너지 모델의 공간 교차검증 상태와 직전 저장 검증을 봅니다.', '관측이 부족하면 성능을 만들지 않고 "학습 자료 부족"으로 표시합니다.'],
  ['/area', '지역 시뮬레이션', '행정동·반경·직접 그린 구역·용도지역을 골라 2015~2025 변화, 개발 전후, 목표 감축에 필요한 노력을 계산합니다.', '이 안내의 "지역 시뮬레이션" 절을 보세요.'],
  ['/simulation', '시뮬레이션', '선택 격자에서 층수·동수·세대 조건을 바꿔 계획안의 에너지·탄소를 계산하고 최적안을 찾습니다.', '계산한 계획안은 검토 보고서에서 비교합니다.'],
  ['/data', '수집 데이터', '빠진 자료를 한 번에 수집하고, 출처별 상태·키·오류·원본을 확인하고, 파일을 업로드합니다.', '이 안내의 "자료 수집" 절을 보세요.'],
  ['/reports', '검토 보고서', '격자 계획안(최대 3개)을 비교한 한국어 보고서를 만들고 내려받거나 인쇄합니다.', '근거 해시로 같은 결과를 다시 확인할 수 있습니다.'],
];

const KEYS: Array<[string, string, string]> = [
  ['DATA_GO_KR_SERVICE_KEY', '공공데이터포털 일반 인증키(Decoding)', 'K-apt 에너지(15012964) · 기상청 ASOS(15059093) · 건축HUB 에너지(15135963) · 건축물대장(15134735). 서비스마다 활용신청 승인이 따로 필요합니다.'],
  ['SGIS_CONSUMER_KEY / SGIS_CONSUMER_SECRET', 'SGIS 오픈API 서비스 키', '행정동 인구·가구와 공식 행정동 경계 (연도별)'],
  ['VWORLD_API_KEY / VWORLD_DOMAIN', 'VWorld 인증키와 등록 도메인', '용도지역·도로명주소 건물·연속지적. 키의 활용 API에서 "2D데이터 API"를 체크하고, 서비스 URL과 VWORLD_DOMAIN을 같게(http://localhost) 둡니다.'],
];

export function GuidePage() {
  const { hash } = useLocation();
  useEffect(() => {
    if (!hash) return;
    const target = document.getElementById(decodeURIComponent(hash.slice(1)));
    target?.scrollIntoView({ block: 'start' });
  }, [hash]);

  return <div className="page guide-page" data-testid="guide-page">
    <PageHeader title="사용 방법" description="이 사이트로 무엇을 할 수 있는지, 화면마다 어떻게 쓰는지, 자료를 어떻게 채우는지 순서대로 설명합니다." action={<span className="badge"><BookOpen size={13} />2026-09-25 기준</span>} />
    <div className="guide-layout">
      <nav className="guide-toc" aria-label="사용 방법 목차">
        <strong>목차</strong>
        <ol>{GUIDE_SECTIONS.map(([id, label]) => <li key={id}><a href={`#${id}`}>{label}</a></li>)}</ol>
      </nav>
      <div className="guide-body">

        <Section id="start" title="처음 시작하기" lead="전국 시·군·구 가운데 고른 지역(처음 연구 지역은 전주시)의 에너지·탄소를 500m 격자와 원하는 구역 단위로 보고, 개발 계획의 영향과 필요한 감축 노력을 계산하는 의사결정 지원 도구입니다.">
          <h3>서버 켜기와 접속</h3>
          <Steps items={[
            <>PC에서 Docker Desktop을 켭니다. 첫 실행은 1~2분 걸립니다.</>,
            <>바탕화면의 <b>Carbon Urban DSS 서버 실행</b>을 두 번 누릅니다. DB·API·수집 작업자·화면·로컬 AI·외부 접속용 터널을 차례로 준비한 뒤 브라우저를 엽니다.</>,
            <>같은 PC에서는 <code>http://localhost:5173</code>으로 접속합니다. 다른 기기에서는 런처가 만든 외부 주소로 접속하고 비밀번호를 입력합니다. 주소는 PC의 <code>data/deployment/public-url.txt</code>, 계정은 <code>.secrets/prototype-access.md</code>에 있습니다.</>,
          ]} />
          <Note tone="warn">외부 주소는 PC와 Docker가 켜져 있는 동안만 열리고, 런처를 다시 실행하면 바뀔 수 있습니다. 새 기능이 보이지 않으면 런처를 다시 실행하세요(새 코드로 다시 빌드합니다).</Note>
          <h3>추천 순서</h3>
          <div className="guide-flow">
            <article><span>1</span><strong>자료 채우기</strong><p>수집 데이터에서 <b>빠진 자료 전부 수집</b>을 누릅니다.</p><Go to="/data#collect-missing">수집 데이터</Go></article>
            <article><span>2</span><strong>구역 비교</strong><p>지역 시뮬레이션에서 동이나 개발 예정지를 고르고 과거와 현재를 봅니다.</p><Go to="/area">지역 시뮬레이션</Go></article>
            <article><span>3</span><strong>감축 노력·보고서</strong><p>목표 감축률을 넣고 필요한 노력을 확인한 뒤 보고서로 남깁니다.</p><Go to="/area">보고서 작성</Go></article>
          </div>
        </Section>

        <Section id="screens" title="화면 구성" lead="왼쪽 메뉴에서 화면을 고릅니다. 위쪽 표제란은 지금 보고 있는 범위를 알려 줍니다.">
          <div className="guide-callout-grid">
            <div><strong>표제란</strong><p>분석 지역 · 분석연도 · 격자(500m) · 선택 격자 · 최근 수집일 · 모드(온라인/오프라인, 배경지도 여부)를 보여 줍니다.</p></div>
            <div><strong>분석 지역</strong><p>오른쪽 위에서 <b>시·도</b>를 고른 뒤 <b>시·군·구</b>를 고르면 모든 화면이 그 지역으로 바뀝니다. 전국 어느 시·군·구든 고를 수 있고, 아직 지도가 없는 곳은 전국 공통 자료로 몇 초 만에 기본 지도를 만듭니다. <b>전국 지도에서 고르기</b>를 누르면 지도에서 시·도와 시·군·구를 고릅니다.</p></div>
            <div><strong>분석연도</strong><p>오른쪽 위에서 바꾸면 대시보드·지도·분석·시뮬레이션·보고서에 함께 적용됩니다. 격자를 고른 뒤 <b>기본 대상지로</b>를 누르면 예비 선정 격자로 돌아갑니다.</p></div>
          </div>
          <div className="table-wrap guide-table"><table>
            <thead><tr><th>메뉴</th><th>할 수 있는 일</th><th>알아 둘 점</th></tr></thead>
            <tbody>{SCREENS.map(([to, label, what, tip]) => <tr key={to}><td><Link to={to}><strong>{label}</strong></Link></td><td>{what}</td><td><small>{tip}</small></td></tr>)}</tbody>
          </table></div>
        </Section>

        <Section id="nation" title="전국 지역·지역 준비" lead="전국 어느 시·군·구든 고르면 그 지역 자료를 공공 API에서 직접 받아 전주시와 같은 분석을 할 수 있게 만듭니다.">
          <h3>전국 기초 자료</h3>
          <p className="guide-p">전국 지역 화면의 <b>전국 기초 자료 수집·갱신</b>은 요청 수가 적은 층만 전국으로 받습니다: 법정 행정구역 코드(행정안전부), SGIS 시군구·행정동 인구·가구·경계, K-apt 공동주택 단지 목록, SGIS 공식 500m 격자 경계. SGIS 1km 격자 통계는 공공데이터포털 파일(15141768)을 전국 그대로 넣었습니다.</p>
          <h3>지역 준비 단계</h3>
          <Steps items={[
            <><b>500m 분석 격자</b>: 그 지역 SGIS 시군구의 공식 500m 격자를 받아 분석 격자로 만듭니다(전주시 격자와 같은 좌표 체계).</>,
            <><b>SGIS 행정동</b> 인구·가구·경계, <b>K-apt 단지</b> 목록과 상세(세대수·연면적·사용승인일), <b>기상</b>(ERA5-Land, 지역 중심 좌표)을 받습니다.</>,
            <><b>VWorld</b> 용도지역·도로명주소 건물·연속지적을 1km 타일 단위로 받고, <b>건축물대장</b> 표제부를 법정동·리마다 받습니다.</>,
            <><b>건축HUB 건물 에너지</b>(분석연도 전 지번)와 <b>K-apt 월별 에너지</b>를 받습니다. 일일 호출 한도에 걸리면 그 단계만 '한도 대기'로 두고 다음 날 00:20에 자동으로 이어서 받습니다.</>,
            <><b>연결·기본 대상지</b>: 에너지를 격자에 잇고, K-apt 세대수가 가장 많은 격자를 기본 대상지로 정합니다.</>,
          ]} />
          <Note tone="warn">받지 못한 층은 0으로 채우지 않고 '자료 없음'으로 둡니다. 법적 상한은 지역마다 <b>그 지역 도시·군계획 조례</b>(특별·광역시의 구·군은 시 조례, 제주시·서귀포시는 도 조례)를 law.go.kr에서 받아 읽은 값이고, 조례에 없는 용도지역은 <b>국토계획법 시행령 제84·85조 상한</b>, 세부 용도지역이 없는 땅은 <b>국토계획법 제79조</b>(도시지역 → 보전녹지, 관리지역 → 보전관리, 미지정 → 자연환경보전) 기준입니다. 개발제한구역·지구단위계획구역과 겹치면 따로 표시합니다. 도시가스 탄소는 공식 계수가 아니라 가정 계수(0.1826 kgCO₂eq/kWh)입니다. 기상은 ASOS 관측이 아니라 ERA5-Land 재분석값입니다.</Note>
          <Go to="/regions">전국 지역 열기</Go>
        </Section>

        <Section id="map-info" title="지도 정보와 활용" lead="지도 분석 화면에서 고를 수 있는 지표와 레이어 전부입니다. 지도 범례의 '정의·산식·활용'과 격자 상세에도 같은 설명이 나옵니다.">
          <h3>지표 ({METRICS.length}개)</h3>
          <p className="guide-p">격자 색은 고른 지표 하나의 값입니다. 빗금 격자는 그 지표를 계산할 자료가 없는 곳이며 0이 아닙니다. 에너지는 관측된 공동주택 단지만의 값이라, 격자 안 모든 건물의 합이 아닙니다.</p>
          <div className="table-wrap guide-table guide-metrics"><table>
            <thead><tr><th>지표 (단위)</th><th>무엇인가</th><th>어떻게 쓰나</th><th>산식 · 출처</th></tr></thead>
            {METRIC_GROUPS.map((group) => <tbody key={group}>
              <tr className="guide-group-row"><th colSpan={4}>{group}</th></tr>
              {METRICS.filter((m) => m.group === group).map((m) => <tr key={m.key}>
                <td><strong>{m.label}</strong><small>{m.unit}</small></td>
                <td>{m.definition}</td>
                <td>{m.use}</td>
                <td><code>{m.formula}</code><small>{m.source}</small></td>
              </tr>)}
            </tbody>)}
          </table></div>
          <h3>레이어 ({MAP_LAYERS.length}개)</h3>
          <div className="table-wrap guide-table"><table>
            <thead><tr><th>레이어</th><th>무엇인가</th><th>어떻게 쓰나</th><th>출처</th></tr></thead>
            <tbody>{MAP_LAYERS.map((l) => <tr key={l.key}><td><strong>{l.label}</strong></td><td>{l.what}</td><td>{l.use}</td><td><small>{l.source}</small></td></tr>)}</tbody>
          </table></div>
          <h3>이렇게 조합해서 봅니다</h3>
          <ul className="guide-list">
            <li><b>도시 탄소 규모</b>: 건물 전체 전력 탄소(건축HUB 전 지번)로 격자별 배출 규모를 보고, 주거 연면적 비율(건축물대장)로 주거·상업 중 어느 쪽이 큰지 가립니다.</li>
            <li><b>개선 우선 지역</b>: 전력·가스 원단위가 높고, 2000년 이전 주택 비율(SGIS)이나 2000년 이전 준공 연면적 비율(건축물대장)이 높은 격자.</li>
            <li><b>에너지 복지</b>: 65세 이상 비율이 높고 가스 원단위가 높은 격자. 난방비 부담이 큰 곳입니다.</li>
            <li><b>개발 여지</b>: 주거지역 비율은 높은데 용적률(건축물대장)이나 추정 용적률이 낮은 격자. 신축 부하는 전력 원단위 × 계획 연면적으로 가늠합니다(시뮬레이션·지역 시뮬레이션).</li>
            <li><b>값의 대표성</b>: 에너지 관측 완전성이 낮거나 아파트 비율(SGIS)이 낮은 격자는 관측 단지가 격자를 잘 대표하지 못합니다.</li>
          </ul>
          <Go to="/map?view=region">시·군·구 상세 지도 열기</Go>
        </Section>

        <Section id="rules" title="값 읽는 법" lead="모든 값에는 어디서 왔는지 표시가 붙습니다. 없는 값을 0으로 채우지 않습니다.">
          <div className="guide-badges">
            <div><ProvenanceBadge kind="observed" /><p>공공기관이 측정·공표한 관측값</p></div>
            <div><ProvenanceBadge kind="computed" /><p>관측값에 공식 계수·면적을 곱해 계산한 값</p></div>
            <div><ProvenanceBadge kind="estimated" /><p>가정이 들어간 근사값 (차트에서는 점선)</p></div>
            <div><ProvenanceBadge kind="scenario" /><p>계획안 입력에 따른 가정 결과 (짧은 점선)</p></div>
            <div><ProvenanceBadge kind="fallback" /><p>공식 자료가 없어 대체 출처(예: ERA5-Land 기상)를 쓴 값</p></div>
            <div><ProvenanceBadge kind="missing" /><p>자료가 없어 계산하지 않음. 빗금과 "—", 사유로 표시하며 0이 아닙니다.</p></div>
          </div>
          <ul className="guide-list">
            <li><b>12개월 완전 관측만</b> 연간 값에 씁니다. 일부 달만 있는 지번은 연간 합계에서 뺍니다.</li>
            <li><b>행정동 통계(인구·가구)</b>는 격자나 반경으로 나누어 배분하지 않고, 겹치는 행정동 값을 참고로만 보여 줍니다.</li>
            <li><b>전력 탄소</b>는 등록된 최신 전력 배출계수(0.4541 kgCO₂eq/kWh)를 모든 연도에 같게 적용합니다. 가스는 공식 계수를 확정한 뒤 넣습니다.</li>
            <li>차트의 <b>빗금 띠</b>는 그 기간에 관측이 없다는 뜻입니다.</li>
            <li>모든 결과는 운영 단계 1차 추정입니다. 법적 적합성이나 넷제로 달성을 판정하지 않습니다.</li>
          </ul>
        </Section>

        <Section id="area" title="지역 시뮬레이션" lead="어느 동이든, 지도에서 고른 어느 곳이든 과거·현재를 비교하고, 개발 전후 영향과 앞으로 필요한 감축 노력을 계산합니다.">
          <h3>1. 구역 고르기</h3>
          <div className="table-wrap guide-table"><table>
            <thead><tr><th>방식</th><th>고르는 법</th><th>포함 기준</th></tr></thead>
            <tbody>
              <tr><td><strong>행정동</strong></td><td>목록에서 고르거나 지도에서 동을 누릅니다. 바로 계산합니다.</td><td>동 경계 안의 격자·단지</td></tr>
              <tr><td><strong>반경</strong></td><td>지도에서 개발 예정지 중심을 누르고 반경(100~5,000m)을 정합니다.</td><td>원과 겹치는 격자, 원 안의 단지</td></tr>
              <tr><td><strong>직접 그리기</strong></td><td>지도를 눌러 꼭짓점을 3개 이상 찍고 <b>구역 확정·분석</b>을 누릅니다. <b>마지막 점 취소</b>·<b>지우기</b>로 고칩니다.</td><td>그린 구역과 겹치는 격자, 구역 안의 단지</td></tr>
              <tr><td><strong>용도지역</strong></td><td>주거·상업·공업·녹지 중 고릅니다.</td><td>그 용도지역이 가장 넓은 격자</td></tr>
              <tr><td><strong>기준 격자</strong></td><td>예비 선정 격자 하나를 봅니다.</td><td>격자 1개</td></tr>
            </tbody>
          </table></div>
          <p className="guide-p">시작·끝 연도를 바꾸면 다시 계산합니다. 위쪽 띠에는 전력 관측이 있는 연도, 12개월 기상이 있는 연도, 인구 연도, 격자·단지 수가 나옵니다.</p>

          <h3>2. 지도와 연도 슬라이더</h3>
          <ul className="guide-list">
            <li>원 하나가 공동주택 단지 하나이고, 원 크기는 세대수입니다. <b>회색</b>은 기존 단지, <b>호박색</b>은 비교에 쓰는 개발 연도의 단지, <b>보라</b>는 그 이후 단지입니다.</li>
            <li>슬라이더를 움직이거나 <b>재생</b>을 누르면 그 해에 아직 준공되지 않은 단지는 빈 원으로, 그 해 준공된 단지는 검은 테로 바뀝니다.</li>
            <li>오른쪽 카드는 슬라이더 연도의 준공 누적 단지·세대, 연면적, 그 해 사용승인, 전력(관측/추정), 전력 탄소, 인구입니다.</li>
          </ul>

          <h3>3. 과거와 현재 차트</h3>
          <ul className="guide-list">
            <li><b>연도별 전력 사용량</b>: 막대는 관측(단지 준공 시기별로 쌓음), 점선은 준공 연면적 × 전주 관측 원단위로 낸 추정입니다. 관측이 없는 해는 빗금 띠입니다.</li>
            <li><b>개발 이력</b>: K-apt 사용승인일 기준 연도별 세대수입니다. 막대에 마우스를 올리면 단지명이 나옵니다.</li>
            <li><b>모든 건물의 개발 이력(건축물대장)</b>: 아파트 외 상가·업무·공공 건물까지 용도군별 연면적입니다. 건축물대장을 수집하면 나타납니다.</li>
            <li><b>기상·인구</b>: 난방도일·냉방도일(12개월 있는 해만)과 행정동 인구·가구입니다.</li>
          </ul>

          <h3>4. 개발 전후 영향</h3>
          <p className="guide-p"><b>개발 연도</b>는 자동(세대가 가장 많이 늘어난 해)으로 두거나 직접 고릅니다. <b>비교 기간</b>은 앞뒤 1~5년이고, 개발 연도 자체는 전환기라 뺍니다.</p>
          <ul className="guide-list">
            <li><b>관측</b>: 전후 연평균 전력 변화, 같은 기존 단지끼리의 변화, 개발 후 신규 단지 비중</li>
            <li><b>추정</b>: 이 개발로 늘어난 연면적과 이 개발만의 전력 증가(직전 연도 재고 대비). 다른 해의 개발과 섞지 않습니다.</li>
            <li><b>맥락</b>: 전후 난방도일·냉방도일·인구. 사용량 차이 일부는 기상 차이일 수 있습니다.</li>
          </ul>

          <h3>5. 미래 개발과 감축 노력</h3>
          <Steps items={[
            <><b>계획 조건</b>을 넣습니다. <b>연면적 직접</b> 또는 <b>층수 × 동수</b>(동별 건축면적)로 넣고, 철거할 연면적이 있으면 함께 넣습니다. 처음 값은 예시입니다.</>,
            <><b>목표 감축률</b>(기준 연도 대비 0~100%)을 슬라이더나 숫자로 넣습니다. 값을 바꾸면 곧바로 다시 계산합니다.</>,
            <>태양광 설비 용량(kW)이 필요하면 <b>kW당 연 발전량</b>을 근거가 있을 때만 넣습니다. 비워 두면 상쇄해야 할 전력량(kWh)만 보여 줍니다.</>,
          ]} />
          <div className="table-wrap guide-table"><table>
            <thead><tr><th>결과</th><th>뜻</th></tr></thead>
            <tbody>
              <tr><td>기준 · 개발 후 · 목표 막대</td><td>기준 연도 탄소, 추가 대책 없이 개발했을 때, 목표선 (tCO₂eq/년)</td></tr>
              <tr><td>필요 감축량</td><td>개발 후 탄소에서 목표선까지 줄여야 하는 양</td></tr>
              <tr><td>신축 건물만 개선할 때</td><td>새 건물 전력만 줄여 목표를 맞추려면 몇 % 줄여야 하는지. 100%를 넘으면 신축만으로는 불가능하다는 뜻입니다.</td></tr>
              <tr><td>지역 전체 건물 효율 개선</td><td>기존 + 신축 건물 전력을 함께 몇 % 줄여야 하는지</td></tr>
              <tr><td>재생에너지로 상쇄할 전력</td><td>같은 목표를 발전으로 맞출 때 필요한 연간 kWh</td></tr>
              <tr><td>목표별 곡선</td><td>목표를 10%씩 바꿨을 때 필요한 효율 개선률</td></tr>
            </tbody>
          </table></div>
          <Note>기준 부하 배지가 <b>관측</b>이면 그 구역의 12개월 관측 전력으로, <b>추정</b>이면 단지 연면적 × 전주 관측 원단위로 계산한 것입니다. 추정은 관측 지번이 적을수록 오차가 큽니다. 과거 자료를 수집하면 관측 기준이 늘어납니다.</Note>

          <h3>6. 지역 보고서</h3>
          <Steps items={[
            <>제목을 비워 두면 "구역 이름 + 개발 영향·감축 검토"로 만듭니다.</>,
            <><b>로컬 AI로 요약 문장 쓰기</b>를 켜면 로컬 모델이 요약을 씁니다. 숫자·연도·증감 방향이 계산 결과와 하나라도 다르면 쓰지 않고 검증된 서식 문장으로 바꾸며, 그 사유를 보여 줍니다.</>,
            <><b>현재 조건으로 보고서 작성</b>을 누르면 저장됩니다. <b>마크다운 내려받기</b>로 파일을 받고, <b>최근 지역 보고서</b>에서 다시 엽니다.</>,
          ]} />
          <Go to="/area">지역 시뮬레이션 열기</Go>
        </Section>

        <Section id="grid" title="격자 분석·계획안·검토 보고서" lead="한 격자(500m)를 자세히 보고 계획안을 비교할 때 쓰는 흐름입니다.">
          <Steps items={[
            <><b>지도 분석</b>에서 격자를 누르면 그 격자가 모든 화면의 선택 격자가 됩니다. 왼쪽 위 지표 선택으로 전력·원단위·용적률·주거지역 비율 등을 바꾸고, 레이어에서 용도지역·행정동·건물·단지를 켭니다.</>,
            <><b>대시보드</b>와 <b>분석</b>에서 그 격자의 월별 관측, 탄소, 도시 형태, 기상, 출처를 확인합니다.</>,
            <><b>시뮬레이션</b>에서 층수 빠른 설정(5~40층)이나 직접 입력으로 계획안을 계산합니다. <b>최적안 탐색</b>은 최소 세대수·인구를 만족하는 후보를 같은 조건에서 항상 같은 순서로 보여 줍니다.</>,
            <><b>3D 배치·일조</b>(시뮬레이션 오른쪽)는 선택 격자 위에 기존 공식 건물(층당 3m, 높이별 색)과 계획 블록을 같은 축척으로 세웁니다. <b>대지 옮기기</b>를 누르고 지도를 클릭해 대지를 옮기고, <b>배치 방향</b>·<b>탑상형/판상형</b>·<b>동 간격</b>(높이 대비)을 바꿀 수 있습니다. <b>동지·춘분·하지</b>와 시각을 고르면 그 시각의 그림자와 그림자가 닿는 기존 건물 수가 나옵니다. 왼쪽 위 요약에는 건폐율·용적률과 대지 용도지역의 <b>법적 상한</b>(그 지역 도시계획 조례 기본 상한, 조례에 없으면 국토계획법 시행령 상한, 세분되지 않은 땅은 제79조 기준)과 용도지역마다의 근거(조례·시행령·가정)가 함께 표시됩니다(완화 규정·지구단위계획 미반영 1차 확인). 계산한 계획안이 있으면 <b>보고서용 장면 저장</b>으로 그림을 계획안에 붙입니다. 블록은 규칙적으로 늘어놓은 규모 비교용이며 실제 배치안이 아닙니다.</>,
            <><b>검토 보고서</b>에서 같은 연도·격자의 계획안을 최대 3개 골라 보고서를 만듭니다. 선택 순서대로 계획안 A·B·C 색을 씁니다. 보고서는 검토 요약 → 대상지 개요(SGIS 공식 500m 격자 코드 포함) → 에너지·탄소 현황(공동주택 관측, 건축HUB 전 지번, 제외 지번, 모델 검증 오차) → 계획안 비교(표와 3D 그림) → 해석 범위와 유의사항 → 데이터 출처 → 재현 정보 순서이며, <b>문서 내려받기</b>(마크다운)와 <b>인쇄 · PDF 저장</b>도 같은 구조입니다.</>,
          ]} />
        </Section>

        <Section id="collect" title="자료 수집" lead="필요한 자료는 대부분 버튼 한 번으로 받습니다. 수집은 이 PC의 Docker에서 실행됩니다.">
          <h3>빠진 자료 전부 수집</h3>
          <Steps items={[
            <><Link to="/data#collect-missing">수집 데이터</Link> 맨 위에서 시작·끝 연도(기본 2015~2025)를 확인합니다.</>,
            <>표에서 연도별·자료별 상태를 봅니다. 문장으로 "수집할 항목 N개"가 요약됩니다.</>,
            <><b>빠진 자료 전부 수집 시작</b>을 누릅니다. 창을 닫아도 PC에서 계속 수집합니다.</>,
          ]} />
          <div className="guide-cells">
            <span><i className="cell done">완료</i>DB에 이미 있음 (호출하지 않음)</span>
            <span><i className="cell todo">수집 예정</i>이번 실행에서 받음</span>
            <span><i className="cell retry">다시 시도</i>지난번 일시 오류 · 일부만 받음</span>
            <span><i className="cell not_published">미공표</i>제공기관이 그 해 자료를 내지 않음</span>
            <span><i className="cell blocked">키·승인 필요</i>키가 없거나 거절됨 (호출하지 않음)</span>
          </div>
          <ul className="guide-list">
            <li>받는 순서는 최근 연도부터, 해마다 <b>SGIS 인구·가구 → 기상청 ASOS(없으면 ERA5-Land) → 건축HUB 전 지번 에너지</b>입니다. 그다음 현재 시점 자료인 <b>VWorld 용도지역 → 도로명주소 건물 → 연속지적 전체 → 건축물대장 표제부</b>를 한 번씩 받고, 호출이 가장 많은 <b>K-apt 단지 에너지</b>를 맨 끝에 받습니다.</li>
            <li>건축HUB 에너지는 <b>2024년 1월부터</b> 제공됩니다. 법정동 단위로 모든 계측 지번(상가·업무·학교·대형 공동주택)을 받으며, 그 전 연도는 두 번의 시험 호출로 '미공표'를 확인하고 넘어갑니다.</li>
            <li>K-apt는 단지마다 사용승인 이전 달을 건너뛰어 호출 수를 줄입니다. 개발계정 한도(하루 5,000건)로는 하루 약 1년치씩이라 2015년까지 채우는 데 열흘 넘게 걸립니다. 성공한 응답은 저장되므로 같은 요청을 반복하지 않습니다.</li>
            <li>K-apt 게이트웨이는 가끔 "04 HTTP 에러"를 냅니다. 오류가 나면 새 연결로 다시 묻고, 계속되면 3분씩 쉬며, 한 해를 다 돈 뒤 남은 달은 10분 뒤 다시 묻습니다. 제공기관 장애가 길면 그 실행을 멈추고 <b>2시간 뒤 스스로 다시 시작</b>합니다. 끝내 못 받은 달은 '다시 시도'로 남고 0으로 채우지 않습니다.</li>
            <li><b>일일 호출 한도</b>에 걸리면 그 자료만 멈추고, 다음 날 0시 20분(한국 시간)에 자동으로 이어서 받습니다. 기다리지 않으려면 <b>지금 바로 다시 시도</b>를 누릅니다.</li>
            <li>시작 전에 DB 백업이 필요하면 PC에서 명령으로 실행하세요(아래). 명령은 백업을 먼저 만듭니다.</li>
          </ul>
          <Note tone="warn">전체 수집은 자료량과 한도에 따라 여러 시간에서 며칠이 걸릴 수 있습니다. 그동안 PC와 Docker Desktop을 켜 두세요. 도중에 꺼져도 다시 시작하면 끝난 항목은 건너뜁니다.</Note>
          <h3>PC 명령으로 실행 (같은 기능)</h3>
          <pre className="guide-code">scripts\dss.cmd CollectAll -FromYear 2015 -ToYear 2025</pre>
          <p className="guide-p">백업 → 서비스 최신화 → 전체 수집 → 상태 기록 순서로 실행하고, 진행 내용을 창과 <code>data/ops/&lt;실행시각&gt;-collectall/collect-history.log</code>에 남깁니다. 일부만 받으려면 <code>-Datasets kapt_energy,energy</code>처럼 지정합니다.</p>
          <h3>하나씩 수집 (고급)</h3>
          <p className="guide-p">수집 데이터의 <b>데이터 수집 요청</b>에서 데이터셋·기간·범위를 골라 실행합니다. 범위는 <b>SMOKE</b>(최소 1건 확인) → <b>LIMITED</b>(제한 범위) → <b>FULL</b>(전체) 순서로 올립니다. FULL은 같은 출처의 SMOKE가 성공한 뒤에만 시작됩니다.</p>
          <h3>API로 받을 수 없는 자료</h3>
          <p className="guide-p">SGIS 500m 격자, 가스 배출계수·열량 기준, 연도별 전력 배출계수, 선도소프트 100m 탄소격자는 제공기관에 신청해 파일로 받습니다(SGIS 1km 격자 통계는 공공데이터포털 파일로 이미 적용되어 있습니다. 아래 <a href="#sgis">SGIS 격자 통계</a>). 받은 파일(CSV·XLSX·GeoJSON·SHP ZIP)은 수집 데이터 아래쪽 <b>수동 파일 업로드</b>에서 미리보기 → 열 매핑 → 가져오기 순서로 넣습니다.</p>
          <Go to="/data#collect-missing">빠진 자료 전부 수집으로 가기</Go>
        </Section>

        <Section id="sgis" title="SGIS 격자 통계 (1km)" lead="공공데이터포털 '국가데이터처_SGIS 격자 통계 및 경계'(2024년 6월 30일 기준)를 전국 그대로 넣었습니다(1km 격자 약 10만 8천 칸). 화면은 선택한 지역의 격자만 읽습니다.">
          <h3>어디에 보이나요</h3>
          <ul className="guide-list">
            <li><b>지도 분석</b> → 지표 선택 → <b>인구·주택 (SGIS 1km)</b>: 인구밀도, 주택밀도, 종사자밀도, 65세 이상 비율, 1인가구 비율, 2000년 이전 주택 비율, 아파트 비율. 격자를 누르면 상세 아래에 1km 격자 값이 나옵니다.</li>
            <li><b>대시보드</b> 아래 <b>인구·주택 (SGIS 1km 격자)</b>: 총계, 비율, 주택 건축연도·유형·규모, 가구 구성, 산업별 종사자.</li>
            <li><b>지역 시뮬레이션</b>의 <b>지역 특성</b>과 지역 보고서(근거 문장·마크다운 표).</li>
            <li>격자 검토 보고서의 근거 문장.</li>
          </ul>
          <h3>값 읽는 법</h3>
          <ul className="guide-list">
            <li>500m 격자에는 <b>그 격자가 속한 1km 격자 값</b>을 붙입니다. 같은 1km 격자에 든 500m 격자 4개는 같은 값입니다. 1km 값을 500m로 나누지 않습니다.</li>
            <li>공식 통계에 <b>비밀보호 잡음</b>이 있습니다. 인구·가구·주택은 5 미만 값을 0 또는 5로 무작위 대체하고, 그 이상은 최대 ±7을 더하거나 뺍니다. 사업체·종사자는 3 미만을 0 또는 3으로, 그 이상은 ±4입니다. 그래서 세부 항목의 합은 총계와 다를 수 있습니다.</li>
            <li>행이 없는 격자·항목은 <b>통계 없음</b>입니다(인구가 없거나 비공개). 0으로 채우지 않습니다.</li>
            <li>비율은 기준(인구·가구·주택)이 20 미만이면 잡음이 커서 계산하지 않습니다.</li>
            <li>지역 시뮬레이션은 구역이 걸친 1km 격자 <b>전체의 합(관측)</b>을 보여 줍니다. 구역보다 넓은 범위입니다. 면적 비례로 나눈 인구는 <b>추정</b> 배지를 붙여 따로 보여 줍니다.</li>
          </ul>
          <Note tone="warn">이 파일은 1km 격자만 있습니다. 500m·100m 격자 통계는 SGIS 자료신청으로 따로 받아야 하며, 500m는 총괄 항목(총인구·총가구·총주택·총사업체·총종사자)만 제공됩니다.</Note>
          <h3>새 연도 파일로 바꾸기</h3>
          <Steps items={[
            <>공공데이터포털에서 <b>국가데이터처_SGIS 격자 통계 및 경계</b>(15141768) 파일을 받아 프로젝트 폴더에 압축을 풉니다.</>,
            <>프로젝트 폴더에서 PowerShell로 아래 명령을 실행합니다. <code>--national</code>은 전국 그대로(약 620만 행) <code>data\raw\sgis_grid_1k\&lt;기준연도&gt;</code>에 둡니다. 격자코드와 경계 도형이 맞는지 모두 확인합니다.</>,
            <>아래 가져오기 명령을 먼저 실행합니다(전국은 5분쯤 걸리므로 API 시작 때 하지 않도록). 그다음 런처를 다시 실행하면 같은 행 수라 건너뜁니다.</>,
          ]} />
          <pre className="guide-code">{'docker compose run --rm --no-deps -v "${PWD}:/work" -w /work api python scripts/sgis/extract_sgis_grid.py --national --source "<압축 푼 폴더>/국가데이터처_SGIS 격자 통계 및 경계"'}</pre>
          <p className="guide-p"><code>--source</code>는 프로젝트 폴더 기준 상대 경로를 <code>/</code>로 적습니다(명령이 Docker 안에서 돌기 때문). 예: <code>국가데이터처_SGIS 격자 통계 및 경계_20250630/국가데이터처_SGIS 격자 통계 및 경계</code></p>
          <p className="guide-p">가져오기: <code>docker compose exec api python -m app.cli import-sgis-grid</code> (다시 넣으려면 <code>--force</code>).</p>
          <Go to="/map">지도 분석 열기</Go>
        </Section>

        <Section id="keys" title="인증키 설정" lead="키는 PC의 .env 파일에만 넣습니다. 화면·로그·보고서에는 키 값이 나오지 않습니다.">
          <div className="table-wrap guide-table"><table>
            <thead><tr><th>.env 항목</th><th>발급처</th><th>받는 자료</th></tr></thead>
            <tbody>{KEYS.map(([name, issuer, use]) => <tr key={name}><td><code>{name}</code></td><td>{issuer}</td><td><small>{use}</small></td></tr>)}</tbody>
          </table></div>
          <Steps items={[
            <>공공데이터포털에서 서비스마다 <b>활용신청</b>을 하고 승인을 기다립니다. 마이페이지의 일반 인증키(Decoding)를 복사합니다.</>,
            <>프로젝트 폴더의 <code>.env</code>를 메모장으로 열어 해당 줄의 <code>=</code> 뒤에 붙여 넣습니다. 따옴표·공백 없이 넣습니다.</>,
            <>런처를 다시 실행하면 API와 수집 작업자가 새 키를 읽습니다.</>,
            <>수집 데이터에서 상태를 확인합니다. <b>키·승인 필요</b>가 사라지면 <b>빠진 자료 전부 수집</b>을 누릅니다.</>,
          ]} />
          <Note>키 칸에 <b>형식 오류</b>가 보이면 예시 문구나 한글·공백이 들어간 값입니다. <b>거절됨</b>은 키는 맞지만 그 서비스의 활용신청 승인이 아직 없다는 뜻인 경우가 많습니다. 키를 바꾸면 이전 거절 기록과 관계없이 바로 다시 시도합니다.</Note>
        </Section>

        <Section id="ai" title="로컬 AI" lead="로컬 AI는 PC 안(Docker)에서만 동작하며, 숫자를 만들지 않고 문장만 씁니다.">
          <ul className="guide-list">
            <li>처음 한 번 PC에서 <code>scripts\setup-local-llm.ps1</code>을 실행하면 모델(qwen2.5:1.5b)을 받습니다. 수집 데이터 화면의 <b>로컬 LLM 운영 구조</b>에서 사용 가능 여부를 봅니다.</li>
            <li>모든 숫자는 계산 엔진이 만듭니다. 모델 문장의 숫자·연도·증감 방향이 계산 결과와 다르면 게시하지 않고 검증된 서식으로 바꿉니다. 그래서 보고서에 틀린 숫자가 실리지 않습니다.</li>
            <li>학습 자료 만들기·평가·LoRA 학습 절차는 저장소의 <code>scripts/llm/README.md</code>에 있습니다. 이 PC(RTX 2060 6GB)에서는 Docker의 CUDA 이미지로 QLoRA(4bit) 학습을 돌립니다(<code>data/ops/claude-runner/train.sh</code> 참고). 새 모델은 응답 오류가 줄고 합격률이 같거나 높을 때만 <code>.env</code>의 <code>OLLAMA_NARRATIVE_MODEL</code>(지역 요약 문단 전용)로 씁니다. 2026-09-27 학습한 <code>carbon-area-narrator</code>는 평가 54개에서 통과 54·오류 0(기준 모델 통과 45·오류 8)이라 요약 문단에 적용했고, 격자 보고서의 근거 선택은 기준 모델(<code>OLLAMA_MODEL</code>)을 그대로 씁니다.</li>
          </ul>
        </Section>

        <Section id="faq" title="문제 해결">
          <div className="guide-faq">
            <details><summary>화면이 열리지 않습니다</summary><p>Docker Desktop이 켜져 있는지 확인하고 런처를 다시 실행하세요. 같은 PC에서는 <code>http://localhost:5173</code>, 다른 기기에서는 <code>data/deployment/public-url.txt</code>의 최신 주소를 씁니다.</p></details>
            <details><summary>"자료 없음"과 빗금이 많이 보입니다</summary><p>아직 수집하지 않았거나 제공기관이 공표하지 않은 값입니다. 0으로 채우지 않습니다. 수집 데이터에서 빠진 자료를 수집하세요.</p></details>
            <details><summary>"키·승인 필요"가 사라지지 않습니다</summary><p>.env의 키 이름과 값을 확인하고 런처를 다시 실행하세요. 공공데이터포털은 서비스마다 활용신청 승인이 따로 필요합니다(K-apt 에너지, ASOS, 건축HUB 에너지, 건축물대장).</p></details>
            <details><summary>"한도 초과 — 자동 재개 대기"로 멈춰 있습니다</summary><p>정상입니다. 다음 날 0시 20분(한국 시간)에 자동으로 이어서 받습니다. 그때 PC와 Docker가 켜져 있어야 합니다. 기다리지 않으려면 <b>지금 바로 다시 시도</b>를 누릅니다.</p></details>
            <details><summary>수집 도중 PC가 꺼졌습니다</summary><p>PC를 켜고 런처를 실행한 뒤 <b>빠진 자료 전부 수집</b>을 다시 누르세요. 끝난 항목과 저장된 응답은 다시 요청하지 않습니다.</p></details>
            <details><summary>지역 시뮬레이션의 추정값을 얼마나 믿어도 되나요?</summary><p>추정은 준공 단지 연면적 × 전주 관측 원단위입니다. 관측 지번이 적으면 오차가 큽니다. 과거 전력을 수집하면 관측 막대와 관측 기준 전후 비교가 생기므로 그쪽을 우선하세요.</p></details>
            <details><summary>데이터를 지우지 않으려면 무엇을 조심해야 하나요?</summary><p><code>docker compose down -v</code>는 수집한 DB를 지우므로 쓰지 마세요. 외부 접속만 끄려면 <code>scripts\prototype.ps1 Stop</code>, 서버 전체를 멈추려면 Docker Desktop을 종료하거나 <code>docker compose stop</code>을 씁니다(데이터 유지). 큰 작업 전에는 <code>scripts\dss.cmd Backup</code>으로 백업합니다.</p></details>
          </div>
        </Section>
      </div>
    </div>
  </div>;
}
