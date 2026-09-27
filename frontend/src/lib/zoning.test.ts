import { describe, expect, it } from 'vitest';
import type { ZoningCheck } from '../types';
import { zoneBasisLabel, zoneName, zoningSourceNote, zoningTitle, zoningTone } from './zoning';

const base: ZoningCheck = { status: 'OK', zones: [], covered_share: 100, bcr_limit: 50, far_limit: 250, mixed: false };

describe('zoning labels', () => {
  it('names the rule table the limits came from', () => {
    expect(zoningTitle({ ...base, basis: 'ORDINANCE', rules_kind: 'ORDINANCE' })).toBe('용도지역·조례 상한');
    expect(zoningTitle({ ...base, basis: 'DECREE', rules_kind: 'DECREE' })).toBe('용도지역·시행령 상한');
    expect(zoningTitle({ ...base, basis: 'MIXED', rules_kind: 'ORDINANCE' })).toBe('용도지역·조례(일부 시행령) 상한');
    expect(zoningTitle({ ...base, basis: 'DECREE' })).toBe('용도지역·시행령 상한');
  });
  it('marks assumptions and gaps per zone', () => {
    expect(zoneBasisLabel({ zone: '보전녹지지역', zone_name: '도시지역', share: 100, bcr_limit: 20, far_limit: 80, basis: 'DECREE', assumed: '제79조' })).toBe('시행령 · 가정');
    expect(zoneName({ zone: '보전녹지지역', zone_name: '도시지역', share: 100, bcr_limit: 20, far_limit: 80, assumed: '제79조' })).toBe('도시지역 → 보전녹지지역');
    expect(zoneName({ zone: '자연환경보전지역', zone_name: null, share: 40, bcr_limit: 20, far_limit: 80, gap: true })).toBe('용도지역 자료 없음');
    expect(zoningTone('개발제한구역 — 건축 원칙적 제한')).toBe('bad');
    expect(zoningTone('조례 기본 상한 이내 (1차 확인) · 일부 가정')).toBe('good');
  });
  it('explains the source in one sentence', () => {
    expect(zoningSourceNote({ ...base, rules_kind: 'DECREE', basis: 'DECREE', issuer: { code: '11000', name: '서울특별시', rule: '' } })).toContain('서울특별시 도시·군계획 조례를 받지 못해');
    expect(zoningSourceNote({ ...base, rules_kind: 'ORDINANCE', basis: 'MIXED', assumed_share: 10, source: { name: '수원시 도시계획 조례', url: 'x', parsed: true } }))
      .toBe('수원시 도시계획 조례 기본 상한, law.go.kr 원문에서 읽은 값, 조례에 없는 용도지역은 시행령 상한, 세분·지정되지 않은 부분은 국토계획법 제79조 기준(가정)입니다. 완화 규정·지구단위계획 지침·경관지구 제한은 반영하지 않았습니다.');
  });
});
