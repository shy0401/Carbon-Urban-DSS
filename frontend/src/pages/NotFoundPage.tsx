import { Link, useLocation } from 'react-router-dom';
import { PageHeader } from '../components/PageHeader';

/** 없는 주소(UX 검토 F15): 대시보드를 그냥 보여 주지 않고, 주소가 없다는 것과 갈 수 있는 화면을 알려 준다. */
export function NotFoundPage() {
  const { pathname } = useLocation();
  return <div className="page" data-testid="not-found">
    <PageHeader title="없는 화면입니다" description={`'${pathname}' 주소에는 화면이 없습니다. 주소를 다시 확인하거나 아래 화면으로 가세요.`} />
    <section className="panel" role="status">
      <ul className="not-found-links">
        <li><Link to="/">대시보드</Link> — 분석 지역·연도의 핵심 지표</li>
        <li><Link to="/map">지도 분석</Link> — 500m 격자 지도</li>
        <li><Link to="/area">지역 시뮬레이션</Link> — 행정동·구역의 개발 전후와 감축 노력</li>
        <li><Link to="/regions">전국 지역</Link> — 다른 시·군·구 고르기</li>
        <li><Link to="/guide">사용 방법</Link></li>
      </ul>
    </section>
  </div>;
}
