import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ModelPage } from './ModelPage';

describe('ModelPage', () => {
  afterEach(() => vi.restoreAllMocks());

  it('학습 자료가 부족하면 검증 지표를 만들어내지 않고 상태를 설명한다', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ status: 'INSUFFICIENT_TRAINING_DATA', models: [], reason: '공간 매칭 관측 격자가 부족합니다.' }), { status: 200 }));
    render(<ModelPage />);
    expect((await screen.findAllByText('학습 데이터 부족')).length).toBeGreaterThan(0);
    expect(screen.getByText('공간 매칭 관측 격자가 부족합니다.')).toBeInTheDocument();
    expect(screen.queryByText('R²')).not.toBeInTheDocument();
  });
});
