import { ChevronLeft, ChevronRight } from 'lucide-react';
import { Link, useLocation } from 'react-router-dom';

/**
 * 보는 순서 (DESIGN.md 4.7): 최종 발표의 순서(현황 → 자료 → 개발 전후 → 지역별 → 감축 방안 → 검증)를
 * 화면 위에 한 줄로 두어, 지금 어느 단계인지와 다음에 볼 화면을 한눈에 알게 한다. 왼쪽 메뉴(하는 일 묶음)를 대신하지 않는다.
 */
export interface FlowStep { key: string; label: string; question: string; stops: string[]; also: string[] }

export const FLOW_STEPS: FlowStep[] = [
  { key: 'now', label: '현황', question: '지금 얼마나 나오나', stops: ['/'], also: [] },
  { key: 'data', label: '자료', question: '무슨 자료로 셌나', stops: ['/data'], also: ['/regions'] },
  { key: 'change', label: '개발 전후', question: '개발하면 얼마나 느나', stops: ['/area'], also: [] },
  { key: 'where', label: '지역별', question: '어디서 많이 나오나', stops: ['/map'], also: ['/analysis'] },
  { key: 'reduce', label: '감축 방안', question: '어떻게 줄이나', stops: ['/simulation', '/reports'], also: [] },
  { key: 'trust', label: '검증', question: '얼마나 믿을 수 있나', stops: ['/model'], also: [] },
];

/** 넘김 단추에 적는 화면 이름(왼쪽 메뉴와 같은 이름). */
export const FLOW_STOP_LABEL: Record<string, string> = {
  '/': '대시보드', '/data': '수집 데이터', '/area': '지역 시뮬레이션', '/map': '지도 분석',
  '/simulation': '시뮬레이션', '/reports': '검토 보고서', '/model': '모델',
};

const STOPS = FLOW_STEPS.flatMap((step, stepIndex) => step.stops.map((path) => ({ path, stepIndex })));
const under = (pathname: string, path: string) => (path === '/' ? pathname === '/' : pathname === path || pathname.startsWith(`${path}/`));

/** 주소가 속한 단계와 넘김 위치. 순서에 없는 화면(사용 방법 등)은 step = -1. */
export function flowPosition(pathname: string): { step: number; stop: number } {
  const stop = STOPS.findIndex((s) => under(pathname, s.path));
  if (stop >= 0) return { step: STOPS[stop].stepIndex, stop };
  const step = FLOW_STEPS.findIndex((s) => s.also.some((path) => under(pathname, path)));
  return { step, stop: step >= 0 ? STOPS.findIndex((s) => s.stepIndex === step) : -1 };
}

export function FlowBar() {
  const { pathname } = useLocation();
  const { step, stop } = flowPosition(pathname);
  const onStop = stop >= 0 && under(pathname, STOPS[stop].path);
  const prev = stop > 0 ? STOPS[stop - 1].path : null;
  // 순서에 든 화면이 아니면(전국 지역·분석) '다음'은 그 단계의 대표 화면 다음으로 간다
  const next = stop >= 0 ? (stop + 1 < STOPS.length ? STOPS[stop + 1].path : null) : STOPS[0].path;
  return <nav className="flow-bar" aria-label="보는 순서" data-testid="flow-bar">
    <ol>
      {FLOW_STEPS.map((s, i) => <li key={s.key} className={i === step ? 'current' : step >= 0 && i < step ? 'done' : undefined}>
        <Link to={s.stops[0]} aria-current={i === step ? 'step' : undefined} title={`${i + 1}단계 ${s.label}: ${s.question}`}>
          <span className="flow-no" aria-hidden="true">{i + 1}</span><span className="flow-label">{s.label}</span><span className="flow-q">{s.question}</span>
        </Link>
      </li>)}
    </ol>
    <div className="flow-move">
      {prev && onStop && <Link className="flow-prev" to={prev} aria-label={`이전 화면: ${FLOW_STOP_LABEL[prev]}`} title={`이전: ${FLOW_STOP_LABEL[prev]}`}><ChevronLeft size={16} aria-hidden="true" /></Link>}
      {next && <Link className="flow-next" to={next} aria-label={`다음 화면: ${FLOW_STOP_LABEL[next]}`}><span>{stop >= 0 ? '다음' : '처음'}: {FLOW_STOP_LABEL[next]}</span><ChevronRight size={16} aria-hidden="true" /></Link>}
    </div>
  </nav>;
}
