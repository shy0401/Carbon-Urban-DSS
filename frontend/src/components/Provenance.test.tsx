import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MetricCard } from './MetricCard';
import { MissingValue } from './MissingValue';
import { ProvenanceBadge } from './ProvenanceBadge';

describe('근거 배지와 결측 값', () => {
  it('배지는 색만이 아니라 한글 라벨을 쓴다', () => {
    render(<><ProvenanceBadge kind="estimated" /><ProvenanceBadge kind="scenario" /><ProvenanceBadge kind="missing" /></>);
    expect(screen.getByText('추정')).toHaveClass('prov-estimated');
    expect(screen.getByText('시나리오')).toHaveClass('prov-scenario');
    expect(screen.getByText('자료 미확보')).toHaveClass('prov-missing');
  });
  it('결측은 0이나 빈칸이 아니라 "—"와 사유로 보인다', () => {
    render(<MissingValue reason="월별 에너지 관측 없음" />);
    expect(screen.getByText('—')).toBeInTheDocument();
    expect(screen.getByText('자료 없음')).toHaveClass('sr-only');
    expect(screen.getByText('월별 에너지 관측 없음')).toBeInTheDocument();
    expect(screen.queryByText('0')).not.toBeInTheDocument();
  });
  it('지표 카드는 값이 없으면 해치 카드와 자료 미확보 배지를 쓰고 유효한 0은 0으로 둔다', () => {
    const { container } = render(<><MetricCard title="가스 탄소" value={null} unit="tCO₂eq" missingReason="계수 확정 전" /><MetricCard title="냉방도일" value={0} unit="°C·일" provenance="observed" /></>);
    const cards = container.querySelectorAll('.metric-card');
    expect(cards[0]).toHaveClass('is-missing');
    expect(screen.getByText('계수 확정 전')).toBeInTheDocument();
    expect(screen.getByText('자료 미확보')).toBeInTheDocument();
    expect(cards[1]).not.toHaveClass('is-missing');
    expect(screen.getByText('0 °C·일')).toHaveClass('sr-only');
    expect(screen.getByText('실측')).toBeInTheDocument();
  });
  it('대상이 없는 카드(건물·단지 없음)는 해치·자료 미확보 배지 없이 해당 없음으로 쓴다', () => {
    const { container } = render(<MetricCard title="공동주택 세대당 전력" value={null} unit="kWh" missingReason="관측 없음" none="격자 안 공동주택 단지 없음" basis="쓰지 않음" />);
    const card = container.querySelector('.metric-card');
    expect(card).not.toHaveClass('is-missing');
    expect(card).toHaveClass('is-none');
    expect(screen.getByText('격자 안 공동주택 단지 없음')).toBeInTheDocument();
    expect(screen.getByText('해당 없음')).toHaveClass('sr-only');
    expect(screen.queryByText('자료 미확보')).not.toBeInTheDocument();
    expect(screen.queryByText('관측 없음')).not.toBeInTheDocument();
    expect(screen.queryByText('쓰지 않음')).not.toBeInTheDocument();
  });
});
