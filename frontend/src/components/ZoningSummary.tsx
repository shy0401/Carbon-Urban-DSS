import { Scale } from 'lucide-react';
import type { ZoningCheck } from '../types';
import { districtPlanLabel, zoneBasisLabel, zoneName, zoningSourceNote, zoningTitle, zoningTone } from '../lib/zoning';

/** 대지에 걸친 용도지역과 조례·시행령 기본 상한, 그리고 계획의 1차 판정 (시뮬레이션 결과와 검토 보고서가 같은 표를 쓴다). */
export function ZoningSummary({ zoning, saved, title, compact = false }: { zoning: ZoningCheck; saved: boolean; title?: string; compact?: boolean }) {
  const check = zoning.check;
  const tone = zoningTone(check?.label);
  const special = zoning.special;
  return <div className={compact ? 'zoning-summary compact' : 'zoning-summary'}>
    <div className="zoning-summary-head"><Scale size={16} aria-hidden="true" /><strong>{title ?? `${zoningTitle(zoning)} 1차 확인`}</strong><span className={`status-tag ${tone}`}>{check?.label ?? '판단 보류'}</span>{!compact && <small>{saved ? '계산 시점 기준' : '현재 입력 기준'}</small>}</div>
    {(special?.greenbelt || special?.district_plans?.length) ? <p className="zoning-special">
      {special.greenbelt && <span className="status-tag bad">개발제한구역 {special.greenbelt.share.toFixed(0)}%</span>}
      {special.district_plans.map((area) => <span key={`${area.name}-${area.area_m2}`} className="status-tag warn">{districtPlanLabel(area.name)} {area.share.toFixed(0)}%</span>)}
    </p> : null}
    <table><thead><tr><th>용도지역</th><th>근거</th><th className="num">대지 비율</th><th className="num">건폐율 상한</th><th className="num">용적률 상한</th></tr></thead>
      <tbody>{zoning.zones.length ? zoning.zones.map((z) => <tr key={`${z.zone}-${z.zone_name}-${z.gap ? 'gap' : ''}`}><td>{zoneName(z)}{z.note && <small>{z.note}</small>}</td><td>{zoneBasisLabel(z)}</td><td className="num">{z.share != null ? `${z.share.toFixed(1)}%` : '-'}</td><td className="num">{(z.applied_bcr_limit ?? z.bcr_limit) != null ? `${z.applied_bcr_limit ?? z.bcr_limit}%` : '규정 없음'}</td><td className="num">{(z.applied_far_limit ?? z.far_limit) != null ? `${z.applied_far_limit ?? z.far_limit}%` : '확인 필요'}</td></tr>) : <tr><td colSpan={5}>{zoning.reason ?? '대지와 겹치는 용도지역 자료가 없습니다.'}</td></tr>}</tbody>
    </table>
    {check?.notes?.length ? <ul>{check.notes.map((n) => <li key={n}>{n}</li>)}</ul> : null}
    {zoning.source && <p className="muted">근거: <a href={zoning.source.url} target="_blank" rel="noreferrer">{zoning.source.name}</a>{zoning.source.articles ? ` ${zoning.source.articles}` : ''} ({[zoning.source.number, zoning.source.effective ? `${zoning.source.effective} 시행` : null, zoning.source.checked ? `${zoning.source.checked} 확인` : null].filter(Boolean).join(', ')}). {zoningSourceNote(zoning)}</p>}
  </div>;
}
