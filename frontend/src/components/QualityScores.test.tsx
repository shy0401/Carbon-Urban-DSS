import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { QualityScores } from './QualityScores';

describe('QualityScores', () => {
  it('구성 점수의 결측을 0점으로 오인하지 않는다', () => {
    render(<QualityScores scores={{ coverage_score: 0.82, completeness_score: null, temporal_score: 0, spatial_match_score: 0.65, overall: null }} />);
    expect(screen.getByText('82%')).toBeInTheDocument();
    expect(screen.getAllByText('미산정').length).toBeGreaterThan(0);
    expect(screen.getByText('0%')).toBeInTheDocument();
  });

  it('근거를 포함한 중첩 품질 점수 계약을 표시한다', () => {
    render(<QualityScores scores={{ overall: 0.7, dimensions: { coverage: { score: 0.8, evidence: '10/12개월' }, completeness: { score: null, evidence: '검사 전' }, temporal: { score: 0.6, evidence: '2025' }, spatial_match: { score: 0.4, evidence: '4/10건' } } }} />);
    expect(screen.getByText('80%')).toBeInTheDocument();
    expect(screen.getByText('10/12개월')).toBeInTheDocument();
  });
});
