import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import { DataPage } from './DataPage';

afterEach(() => vi.restoreAllMocks());

it('외부 공급기관과 안전한 단계별 수집 범위를 선택할 수 있다', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
    const url = String(input);
    const readiness = {
      generated_at: '2025-01-01T00:00:00Z',
      offline_mode: false,
      summary: { total_sources: 2, collectable_now: 1, states: { AVAILABLE: 1, CREDENTIAL_REQUIRED: 1 } },
      pipeline: [
        { id: 'acquire', label: '수집', value: 2, detail: '공식 API·수동 원본' },
        { id: 'decision', label: '의사결정', value: 4, detail: '지도·탄소·모델·보고서' },
      ],
      sources: [
        { id: 'kapt_energy', name: 'K-apt 월별 에너지', organization: '한국부동산원', status: 'NEEDS_API_KEY', state: 'CREDENTIAL_REQUIRED', acquisition: 'API_KEY', collection_dataset: 'kapt_energy', collectable_now: false, credentials: [{ name: 'DATA_GO_KR_SERVICE_KEY', configured: false }], scopes: { smoke: '1단지 × 1개월' }, products: ['단지·월 에너지'], uses: ['운영탄소', '실데이터 모델 학습'], raw_rows: 0, normalized_rows: 0, blocker: '환경변수 미설정: DATA_GO_KR_SERVICE_KEY' },
        { id: 'weather', name: 'ERA5-Land 대체 기상', organization: 'Open-Meteo', status: 'COLLECTED', state: 'AVAILABLE', acquisition: 'OPEN_API', collection_dataset: 'weather', collectable_now: true, credentials: [], scopes: { smoke: '저장 원본 재사용' }, products: ['월평균 기온'], uses: ['기상 차트'], raw_rows: 12, normalized_rows: 12 },
      ],
      truth_rules: ['0행은 미수집이며 실제 사용량 0과 다릅니다.'],
    };
    const engine = { status: 'READY', model: 'qwen2.5:1.5b', provider: 'Ollama local container', privacy: '로컬 Docker 네트워크 내부 처리', allowed_tasks: ['검증된 근거 ID 선택', '한국어 보고서 요약'], prohibited_tasks: '수치 계산·새로운 사실 생성·법적 판정' };
    const jobs = [{ id: 'job-1', status: 'PARTIAL', datasets: ['kapt_energy'], updated_at: '2025-01-01T00:00:00Z', message: '일부 자료 수집 불가 — 오류 내역 확인', errors: [{ dataset: 'kapt_energy', message: 'API 인증 실패: 서비스 승인 및 키 확인 필요 (30/20)' }, '페이지 제한 5 도달'] }];
    const payload = url.includes('/readiness') ? readiness : url.includes('/reports/engine') ? engine : url.includes('/collections') ? jobs : [];
    return Promise.resolve(new Response(JSON.stringify(payload), { status: 200 }));
  });
  render(<MemoryRouter><DataPage /></MemoryRouter>);
  expect(await screen.findByText('K-apt 에너지')).toBeInTheDocument();
  expect(screen.getByText('KMA ASOS')).toBeInTheDocument();
  expect(screen.getByText('SGIS 인구·가구')).toBeInTheDocument();
  expect(screen.getByText('VWorld 용도지역')).toBeInTheDocument();
  expect(screen.getByText('VWorld 연속지적')).toBeInTheDocument();
  expect(screen.getByLabelText('수집 범위')).toHaveValue('smoke');
  expect(screen.getByText('데이터가 의사결정으로 연결되는 과정')).toBeInTheDocument();
  expect(screen.getAllByText('K-apt 월별 에너지').length).toBeGreaterThan(0);
  expect(screen.getByText('운영탄소')).toBeInTheDocument();
  expect(screen.getByText('로컬 LLM 운영 구조')).toBeInTheDocument();
  expect(screen.getByText(/qwen2\.5:1\.5b/)).toBeInTheDocument();
  expect(screen.getByRole('checkbox', { name: /K-apt 에너지/ })).toBeDisabled();
  await waitFor(() => expect(screen.getByRole('checkbox', { name: /ERA5-Land 기상/ })).toBeChecked());
  expect(screen.getByText('API 인증 실패: 서비스 승인 및 키 확인 필요 (30/20)')).toBeInTheDocument();
  expect(screen.getByText('페이지 제한 5 도달')).toBeInTheDocument();
});

it('자리표시자 키는 설정됨이 아니라 형식 오류로 표시한다', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
    const url = String(input);
    const readiness = {
      generated_at: '2025-01-01T00:00:00Z',
      offline_mode: false,
      summary: { total_sources: 1, collectable_now: 0, states: { CREDENTIAL_REQUIRED: 1 } },
      pipeline: [{ id: 'acquire', label: '수집', value: 1, detail: '공식 API' }],
      sources: [
        { id: 'kapt_energy', name: 'K-apt 월별 에너지', organization: '한국부동산원', status: 'NEEDS_API_KEY', state: 'CREDENTIAL_REQUIRED', acquisition: 'API_KEY', collection_dataset: 'kapt_energy', collectable_now: false, credentials: [{ name: 'DATA_GO_KR_SERVICE_KEY', configured: true, format_ok: false, problem: '자리표시자로 보입니다' }], scopes: { smoke: '1단지 × 1개월' }, products: ['단지·월 에너지'], uses: ['운영탄소'], raw_rows: 0, normalized_rows: 0, blocker: '환경변수 형식 오류: DATA_GO_KR_SERVICE_KEY' },
      ],
      truth_rules: [],
    };
    const payload = url.includes('/readiness') ? readiness : url.includes('/reports/engine') ? { status: 'UNAVAILABLE', allowed_tasks: [], prohibited_tasks: '' } : [];
    return Promise.resolve(new Response(JSON.stringify(payload), { status: 200 }));
  });
  render(<MemoryRouter><DataPage /></MemoryRouter>);
  expect(await screen.findByText('형식 오류')).toBeInTheDocument();
  expect(screen.queryByText('설정됨')).not.toBeInTheDocument();
});
