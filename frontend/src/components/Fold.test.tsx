import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Fold, FoldAllButton, FoldStack, Note } from './Fold';

describe('Fold (화면 정보 3단의 접힌 근거)', () => {
  it('접혀 있어도 제목·핵심 값·내용이 문서에 남는다', () => {
    render(<Fold title="건물 전체 에너지" figures="전력 1,200 kWh" testId="fold-a"><p>표와 설명</p></Fold>);
    const fold = screen.getByTestId('fold-a') as HTMLDetailsElement;
    expect(fold.open).toBe(false);
    expect(screen.getByText('건물 전체 에너지')).toBeInTheDocument();
    expect(screen.getByText('전력 1,200 kWh')).toBeInTheDocument();
    expect(screen.getByText('표와 설명')).toBeInTheDocument();
  });

  it('핵심 값이 없으면 빈 칸이나 0을 만들지 않는다', () => {
    const { container } = render(<Fold title="기상"><p>본문</p></Fold>);
    expect(container.querySelector('.fold-figures')).toBeNull();
  });

  it('처음부터 펼쳐 둘 수 있고, 패널 여러 개를 담을 때는 flat을 끈다', () => {
    render(<><Fold title="가" defaultOpen testId="fold-open"><p>열린 내용</p></Fold><Fold title="나" flat={false} testId="fold-many"><p>패널 둘</p></Fold></>);
    expect((screen.getByTestId('fold-open') as HTMLDetailsElement).open).toBe(true);
    expect(screen.getByTestId('fold-open')).toHaveClass('flat');
    expect(screen.getByTestId('fold-many')).not.toHaveClass('flat');
  });

  it('모두 펼치기는 접이식 구역과 설명을 한 번에 열고 다시 접는다', () => {
    render(<FoldStack title="더 보기" hint="눌러서 펼칩니다"><FoldAllButton /><Fold title="다" testId="fold-b"><p>내용</p></Fold><Note label="읽는 법">긴 설명</Note></FoldStack>);
    const fold = screen.getByTestId('fold-b') as HTMLDetailsElement;
    const note = screen.getByText('긴 설명').closest('details') as HTMLDetailsElement;
    expect(screen.getByRole('heading', { name: '더 보기' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '모두 펼치기' }));
    expect(fold.open).toBe(true);
    expect(note.open).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: '모두 접기' }));
    expect(fold.open).toBe(false);
    expect(note.open).toBe(false);
  });
});
