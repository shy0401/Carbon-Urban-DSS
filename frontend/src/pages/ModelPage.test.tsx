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

  it('검증 결과는 총량 R²와 원단위 R², nMAE를 함께 보여주고 사용 변수를 밝힌다', async () => {
    const metrics = { mae: 38484.3, rmse: 66891.9, r2: 0.962, nmae: 0.091, intensity_r2: 0.41 };
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      status: 'SPATIALLY_EVALUATED',
      models: [{ name: '관측 월별 연면적 원단위', energy_type: 'ELECTRICITY', status: 'SPATIALLY_EVALUATED', observations: 1608, grid_count: 134, spatial_blocks: 28, months: 12,
        features: ['연면적(분모)', '월(계절)', '세대당 연면적'], scope: 'K-apt 공동주택 지번', models: [{ name: 'RandomForestRegressor', metrics }, { name: 'Intensity baseline', metrics: { ...metrics, mae: 41994.7 } }] }],
    }), { status: 200 }));
    render(<ModelPage />);
    expect(await screen.findByText('R² 원단위')).toBeInTheDocument();
    expect(screen.getAllByText('0.41').length).toBe(2);
    expect(screen.getAllByText('9.1%').length).toBe(2);
    expect(screen.getByText('연면적(분모), 월(계절), 세대당 연면적')).toBeInTheDocument();
    expect(screen.getByText('오차 최소', { exact: false }).closest('td')).toHaveTextContent('RandomForestRegressor');
  });
});
