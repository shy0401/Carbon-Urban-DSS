import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ConfidenceGrades, CONFIDENCE_ROWS, CORRECTION_STEPS } from './ConfidenceGrades';

describe('ConfidenceGrades', () => {
  it('네 대상의 등급과 근거를 표로 보여 준다', () => {
    render(<ConfidenceGrades />);
    expect(screen.getByRole('heading', { name: '신뢰도 등급' })).toBeInTheDocument();
    expect(screen.getAllByRole('row')).toHaveLength(CONFIDENCE_ROWS.length + 1);
    expect(screen.getByText('500m 칸 하나의 값')).toBeInTheDocument();
    expect(screen.getByText(/보정 전 계측 건물 합계/)).toBeInTheDocument();
  });

  it('시·군·구 총량 보정식과 단계별 평균 차이를 보여 준다', () => {
    render(<ConfidenceGrades />);
    const block = screen.getByTestId('correction-formula');
    expect(block).toHaveTextContent('계측 건물 전력 합 ÷ ① 계측 포함률 × ② 부문 범위 × ③ 계수 비');
    expect(within(block).getAllByRole('listitem')).toHaveLength(CORRECTION_STEPS.length);
    expect(block).toHaveTextContent('44.4%');
    expect(block).toHaveTextContent('8.1%');
    expect(block).toHaveTextContent('자기 지역을 빼고 구함');
  });

  it('요약 줄은 고른 대상만 보여 준다', () => {
    render(<ConfidenceGrades compact ids={['cell', 'measure']} />);
    const line = screen.getByTestId('confidence-line');
    expect(line).toHaveTextContent('500m 칸 하나의 값');
    expect(line).toHaveTextContent('감축 수단 지표');
    expect(line).not.toHaveTextContent('시·군·구');
    expect(screen.queryByTestId('correction-formula')).toBeNull();   // 보정식은 전체 표에서만
  });
});
