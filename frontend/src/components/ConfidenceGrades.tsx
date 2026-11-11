/**
 * 숫자의 신뢰도 등급. 공식 온실가스 통계·탄소공간지도와 맞대 본 분석 결과로 정한 기준이다
 * (ASHRAE Guideline 14의 월 CV 15%·편향 5%, IPCC 2006 불확도 지침 참고).
 * 등급은 분석 문서 기준의 고정값이며, 화면 값이 바뀌어도 자동으로 다시 매기지 않는다.
 */
export interface ConfidenceRow { id: 'region' | 'rank' | 'cell' | 'measure'; target: string; grade: 'B' | 'C'; basis: string; use: string }

export const CONFIDENCE_ROWS: ConfidenceRow[] = [
  { id: 'region', target: '시·군·구 건물 전력 총량', grade: 'B', basis: '보정 3단계(빠진 건물·부문 범위·그해 계수)를 적용하면 2023년 19개 시·군·구 공식 온실가스 통계와 평균 차이 8.1%(최대 22%, 보정값은 자기 지역을 빼고 구함). 화면의 지역 합계는 보정 전 계측 건물 합계로, 같은 비교에서 평균 44% 작습니다.', use: '총량 판단에 사용 · 보정 전 합계는 하한으로 읽기' },
  { id: 'rank', target: '500m 칸 순서', grade: 'B', basis: '탄소공간지도와 순위 상관 0.73~0.94(5개 지역, 2024년 전력)', use: '어디가 많이 쓰는지 비교' },
  { id: 'cell', target: '500m 칸 하나의 값', grade: 'C', basis: '다른 지역 원단위로 예측한 칸 값의 중앙 오차 65%', use: '값 대신 순서로만 사용' },
  { id: 'measure', target: '감축 수단 지표', grade: 'C', basis: '단열·창호 가스 −23.6%(준공 시기만 다른 단지 78쌍 실측) · 운영 절약 전력 −4.8%(실측 문헌 6건 중앙값) · 지붕 이용 60% · 태양광 성능비 0.80 · 녹지 흡수 연 1.0 kgCO2/m²(가정)', use: '실측 지표와 가정을 구분해 표시 · 사업마다 달라질 수 있음' },
];

const GRADE_NOTE = '등급 B = 공식 통계·독립 자료와 맞대어 범위를 확인함, C = 오차가 크거나 가정값임.';

/** Full table (에너지 모델) or a one-line summary of selected rows (시뮬레이션·보고서). */
export function ConfidenceGrades({ ids, compact = false }: { ids?: ConfidenceRow['id'][]; compact?: boolean }) {
  const rows = ids ? CONFIDENCE_ROWS.filter((r) => ids.includes(r.id)) : CONFIDENCE_ROWS;
  if (compact) {
    return <p className="confidence-line" data-testid="confidence-line"><b>신뢰도</b>{rows.map((r) => <span key={r.id} title={r.basis}> · {r.target} <em className={`grade grade-${r.grade}`}>{r.grade}</em> ({r.use})</span>)}</p>;
  }
  return <section className="panel confidence-grades" aria-label="신뢰도 등급" data-testid="confidence-grades">
    <div className="panel-title"><h3>신뢰도 등급</h3><span className="status-tag neutral">분석 기준 고정값</span></div>
    <div className="table-wrap"><table><thead><tr><th>대상</th><th>등급</th><th>근거</th><th>쓰는 법</th></tr></thead>
      <tbody>{rows.map((r) => <tr key={r.id}><td>{r.target}</td><td><em className={`grade grade-${r.grade}`}>{r.grade}</em></td><td>{r.basis}</td><td>{r.use}</td></tr>)}</tbody></table></div>
    <p className="muted">{GRADE_NOTE} 기준은 ASHRAE Guideline 14(월 CV 15%, 편향 5%)와 IPCC 2006 불확도 지침을 참고해 정했습니다. 관측이 없는 곳은 0이 아니라 ‘자료 없음’입니다.</p>
  </section>;
}
