import { useEffect, useRef, useState, type ReactNode } from 'react';

/**
 * 화면 정보 3단 (DESIGN.md 4.6): ① 핵심 수치 → ② 그림·표 하나 → ③ 근거·산식·보조 자료(접어 둠).
 * 이 파일은 ③을 담는 부품이다. 접힌 내용도 DOM에는 그대로 있어 찾기(Ctrl+F)·인쇄·화면 낭독기에서 빠지지 않는다.
 */

/** 접이식 구역: 제목과 핵심 숫자 한 줄만 보이고, 누르면 표·그림·설명이 열린다. 주소의 #id로 오면 스스로 열린다. */
export function Fold({ title, figures, hint = '자세히', children, defaultOpen = false, id, className, testId, label, flat = true }: {
  title: ReactNode;
  /** 접힌 상태에서도 보이는 핵심 숫자 한 줄. 값이 없으면 넣지 않는다(0으로 채우지 않음). */
  figures?: ReactNode;
  hint?: string;
  children: ReactNode;
  defaultOpen?: boolean;
  id?: string;
  className?: string;
  testId?: string;
  label?: string;
  /** 안에 패널 하나만 넣을 때(기본): 패널 테두리와 제목을 접이식 머리에 맡긴다. 패널 여러 개를 넣으면 false. */
  flat?: boolean;
}) {
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    if (!id || typeof window === 'undefined') return undefined;
    const openIfTarget = () => { if (window.location.hash === `#${id}` && ref.current) ref.current.open = true; };
    openIfTarget();
    window.addEventListener('hashchange', openIfTarget);
    return () => window.removeEventListener('hashchange', openIfTarget);
  }, [id]);
  return <details ref={ref} className={`fold${flat ? ' flat' : ''}${className ? ` ${className}` : ''}`} id={id} open={defaultOpen || undefined} data-testid={testId} aria-label={label}>
    <summary><span className="fold-title">{title}</span>{figures ? <span className="fold-figures">{figures}</span> : null}<span className="fold-hint" aria-hidden="true">{hint}</span></summary>
    <div className="fold-body">{children}</div>
  </details>;
}

/** 그림·표 아래의 긴 설명: '설명' 한 줄로 접어 두고 누르면 펼친다. 짧은 기준 문구(연도·관측 기간)는 접지 않고 그대로 둔다. */
export function Note({ children, label = '설명·주의' }: { children: ReactNode; label?: string }) {
  return <details className="note"><summary>{label}</summary><div className="note-body">{children}</div></details>;
}

/** 접힌 구역을 한 번에 펼치거나 접는다(발표·인쇄·검토용). 값은 바꾸지 않는다. */
export function FoldAllButton() {
  const [open, setOpen] = useState(false);
  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (typeof document !== 'undefined') document.querySelectorAll<HTMLDetailsElement>('details.fold, details.note').forEach((el) => { el.open = next; });
  };
  return <button type="button" className="button ghost small fold-all" aria-pressed={open} onClick={toggle}>{open ? '모두 접기' : '모두 펼치기'}</button>;
}

/** 접이식 구역 묶음의 머리(작은 제목 + 한 줄 안내). */
export function FoldStack({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return <section className="fold-stack" aria-label={title}>
    <div className="fold-stack-head"><h2>{title}</h2>{hint && <span>{hint}</span>}</div>
    {children}
  </section>;
}
