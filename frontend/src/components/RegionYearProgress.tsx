import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../lib/api';

type YearStates = Record<string, string>;
const ROWS: Array<[string, string]> = [['energy_years', '건축HUB 건물 에너지 (전 지번)'], ['kapt_years', 'K-apt 단지 월 에너지']];
const LABEL: Record<string, [string, string]> = {
  DONE: ['완료', 'good'], PARTIAL: ['일부', 'warn'], WAITING: ['한도 대기', 'warn'], BLOCKED: ['막힘', 'bad'], FAILED: ['실패', 'bad'], SKIPPED: ['건너뜀', 'neutral'],
};
const FIRST_YEAR = 2015;

/** 머리에서 고른 지역의 연도별 수집 진행(UX 검토 F10): 지역 준비가 남긴 study_regions.datasets.energy_years·kapt_years. */
export function RegionYearProgress({ code, name, lastYear }: { code: string; name: string; lastYear: number }) {
  const [datasets, setDatasets] = useState<Record<string, unknown> | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true; setDatasets(null); setFailed(false);
    api<{ datasets?: Record<string, unknown> }>(`/regions/${code}`)
      .then((body) => { if (alive) setDatasets(body.datasets ?? {}); })
      .catch(() => { if (alive) setFailed(true); });
    return () => { alive = false; };
  }, [code]);
  const years = Array.from({ length: Math.max(lastYear - FIRST_YEAR + 1, 1) }, (_, i) => FIRST_YEAR + i);
  return <section className="panel region-year-progress" id="region-years" aria-label={`${name} 연도별 수집 진행`} data-testid="region-year-progress">
    <div className="panel-title"><h3>{name} 연도별 수집 진행</h3></div>
    {failed ? <p className="muted" role="alert">지역 진행 기록을 읽지 못했습니다.</p>
      : !datasets ? <p className="muted" role="status">지역 진행 기록을 읽는 중입니다…</p>
        : <>
          <div className="table-wrap" tabIndex={0}><table>
            <thead><tr><th>자료</th>{years.map((y) => <th key={y} className="num">{y}</th>)}</tr></thead>
            <tbody>{ROWS.map(([key, label]) => {
              const states = (datasets[key] ?? {}) as YearStates;
              return <tr key={key}><th scope="row">{label}</th>{years.map((y) => {
                const state = states[String(y)];
                const [text, tone] = state ? LABEL[state] ?? [state, 'neutral'] : ['—', 'none'];
                return <td key={y} className="num"><span className={tone === 'none' ? 'muted' : `status-tag ${tone}`} title={state ? undefined : '이 지역 준비에서 이 해를 받은 기록이 없습니다'}>{text}</span></td>;
              })}</tr>;
            })}</tbody>
          </table></div>
          <p className="muted">'—'는 이 지역 준비에서 그 해를 받은 기록이 없다는 뜻입니다(사용량 0이 아님). 이 지역 자료는 <Link to={`/regions?select=${code}`}>전국 지역</Link>에서 받습니다.</p>
        </>}
  </section>;
}
