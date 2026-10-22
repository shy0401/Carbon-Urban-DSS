/**
 * 긴 화면(대시보드·수집 데이터) 머리 아래의 구역 길잡이. 같은 화면 안의 id로만 옮기고(브라우저 기본 이동,
 * html의 scroll-padding-top이 고정 머리 높이를 뺀다) 값은 바꾸지 않는다.
 */
export function SectionNav({ items, label = '이 화면의 구역' }: { items: Array<{ id: string; label: string }>; label?: string }) {
  if (!items.length) return null;
  return <nav className="section-nav" aria-label={label}>
    {items.map((item) => <a key={item.id} href={`#${item.id}`}>{item.label}</a>)}
  </nav>;
}
