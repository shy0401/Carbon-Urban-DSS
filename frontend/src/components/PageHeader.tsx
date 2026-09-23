import type { ReactNode } from 'react';

/** 화면 제목(20px/600)과 한 줄 설명. 영문 눈썹 라벨은 두지 않는다(DESIGN.md 3). */
export function PageHeader({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return <header className="page-header"><div><h1>{title}</h1><p>{description}</p></div>{action}</header>;
}
