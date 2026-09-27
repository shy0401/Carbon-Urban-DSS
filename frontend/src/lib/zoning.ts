import type { ZoningCheck, ZoningZone } from '../types';

/** Panel title: which rule table the limits came from. */
export function zoningTitle(zoning: ZoningCheck | null | undefined): string {
  if (!zoning) return '용도지역·법적 상한';
  if (zoning.rules_kind === 'DECREE' || (!zoning.rules_kind && zoning.basis === 'DECREE')) return '용도지역·시행령 상한';
  return zoning.basis === 'ORDINANCE' || !zoning.basis ? '용도지역·조례 상한' : '용도지역·조례(일부 시행령) 상한';
}

/** Short tag per zone row: 조례 / 시행령 / 가정. */
export function zoneBasisLabel(zone: ZoningZone): string {
  if (zone.gap) return '자료 없음 · 가정';
  const basis = zone.basis === 'ORDINANCE' ? '조례' : zone.basis === 'DECREE' ? '시행령' : '조례·시행령';
  return zone.assumed ? `${basis} · 가정` : basis;
}

export function zoneName(zone: ZoningZone): string {
  if (zone.gap) return '용도지역 자료 없음';
  if (zone.assumed && zone.zone_name && zone.zone_name !== zone.zone) return `${zone.zone_name} → ${zone.zone}`;
  return zone.zone ?? zone.zone_name ?? '이름 없음';
}

/** Tone of the 1차 확인 label. */
export function zoningTone(label: string | undefined): 'bad' | 'good' | 'warn' {
  if (!label) return 'warn';
  if (label.includes('초과') || label.includes('개발제한')) return 'bad';
  return label.includes('이내') ? 'good' : 'warn';
}

/** One sentence on where the limits come from. */
export function zoningSourceNote(zoning: ZoningCheck): string {
  const source = zoning.source;
  if (zoning.rules_kind === 'DECREE' || (!zoning.rules_kind && zoning.basis === 'DECREE')) {
    const issuer = zoning.issuer ? `${zoning.issuer.name} 도시·군계획 조례` : '이 지역 도시계획 조례';
    return `${issuer}를 받지 못해 국토계획법 시행령 제84·85조 상한(전국 공통)을 썼습니다. 조례 상한은 더 낮을 수 있으므로 '이내'는 조례를 더 확인해야 합니다.`;
  }
  const parts = [`${source?.name ?? '도시계획 조례'} 기본 상한`];
  if (source?.parsed) parts.push('law.go.kr 원문에서 읽은 값');
  if (zoning.basis !== 'ORDINANCE') parts.push('조례에 없는 용도지역은 시행령 상한');
  if ((zoning.assumed_share ?? 0) > 0) parts.push('세분·지정되지 않은 부분은 국토계획법 제79조 기준(가정)');
  return `${parts.join(', ')}입니다. 완화 규정·지구단위계획 지침·경관지구 제한은 반영하지 않았습니다.`;
}

/** District plan name for a tag: VWorld often names the area just '지구단위계획구역'. */
export function districtPlanLabel(name: string | null | undefined): string {
  const text = (name ?? '').trim();
  if (!text) return '지구단위계획구역';
  return text.includes('지구단위') ? text : `지구단위계획구역 ${text}`;
}
