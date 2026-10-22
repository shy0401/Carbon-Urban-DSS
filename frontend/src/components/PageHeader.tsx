import { useEffect, useRef, useState, type ReactNode } from 'react';

/**
 * 화면 제목(20px/600)과 한 줄 설명. 영문 눈썹 라벨은 두지 않는다(DESIGN.md 3).
 * 760px 이하에서는 설명을 두 줄로 접고(지도·표가 먼저 보이게) '설명 더 보기'로 펼친다. 글이 두 줄 안에 들어가면 단추를 두지 않는다.
 */
export function PageHeader({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  const text = useRef<HTMLParagraphElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [clamped, setClamped] = useState(false);
  useEffect(() => {
    const el = text.current;
    if (!el) return undefined;
    const measure = () => { if (!expanded) setClamped(el.scrollHeight > el.clientHeight + 1); };
    measure();
    window.addEventListener('resize', measure);
    return () => window.removeEventListener('resize', measure);
  }, [description, expanded]);
  return <header className="page-header"><div>
    <h1>{title}</h1>
    <p ref={text} className={`page-description${expanded ? ' expanded' : ''}`}>{description}</p>
    {(clamped || expanded) && <button type="button" className="page-description-toggle" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? '설명 접기' : '설명 더 보기'}</button>}
  </div>{action}</header>;
}
