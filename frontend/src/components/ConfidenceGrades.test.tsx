import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ConfidenceGrades, CONFIDENCE_ROWS } from './ConfidenceGrades';

describe('ConfidenceGrades', () => {
  it('네 대상의 등급과 근거를 표로 보여 준다', () => {
    render(<ConfidenceGrades />);
    expect(screen.getByRole('heading', { name: '신뢰도 등급' })).toBeInTheDocument();
    expect(screen.getAllByRole('row')).toHaveLength(CONFIDENCE_ROWS.length + 1);
    expect(screen.getByText('500m 칸 하나의 값')).toBeInTheDocument();
    expect(screen.getByText(/보정 전 계측 건물 합계/)).toBeInTheDocument();
  });

  it('요약 줄은 고른 대상만 보여 준다', () => {
    render(<ConfidenceGrades compact ids={['cell', 'measure']} />);
    const line = screen.getByTestId('confidence-line');
    expect(line).toHaveTextContent('500m 칸 하나의 값');
    expect(line).toHaveTextContent('감축 수단 상수');
    expect(line).not.toHaveTextContent('시·군·구');
  });
});
