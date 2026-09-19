import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { Pagination } from './pagination';

describe('Pagination', () => {
  let fixture: ComponentFixture<Pagination>;

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [Pagination, NoopAnimationsModule] });
    fixture = TestBed.createComponent(Pagination);
  });

  function setInputs(count: number, page: number, hasNext: boolean, hasPrevious: boolean) {
    fixture.componentRef.setInput('count', count);
    fixture.componentRef.setInput('page', page);
    fixture.componentRef.setInput('hasNext', hasNext);
    fixture.componentRef.setInput('hasPrevious', hasPrevious);
    fixture.detectChanges();
  }

  it('shows the total count and current page', () => {
    setInputs(30, 1, true, false);
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('30 total');
    expect(text).toContain('Page 1');
  });

  function getButtons(): HTMLButtonElement[] {
    return Array.from(fixture.nativeElement.querySelectorAll('button'));
  }

  it('disables Previous on the first page and enables Next', () => {
    setInputs(30, 1, true, false);
    const buttons = getButtons();
    const previous = buttons.find((b) => b.textContent?.trim() === 'Previous')!;
    const next = buttons.find((b) => b.textContent?.trim() === 'Next')!;
    expect(previous.disabled).toBe(true);
    expect(next.disabled).toBe(false);
  });

  it('disables Next on the last page and enables Previous', () => {
    setInputs(30, 2, false, true);
    const buttons = getButtons();
    const previous = buttons.find((b) => b.textContent?.trim() === 'Previous')!;
    const next = buttons.find((b) => b.textContent?.trim() === 'Next')!;
    expect(previous.disabled).toBe(false);
    expect(next.disabled).toBe(true);
  });

  it('emits next/previous on click', () => {
    setInputs(30, 1, true, true);
    const nextSpy = vi.fn();
    const prevSpy = vi.fn();
    fixture.componentInstance.next.subscribe(nextSpy);
    fixture.componentInstance.previous.subscribe(prevSpy);

    const buttons = getButtons();
    const previous = buttons.find((b) => b.textContent?.trim() === 'Previous')!;
    const next = buttons.find((b) => b.textContent?.trim() === 'Next')!;
    next.click();
    previous.click();

    expect(nextSpy).toHaveBeenCalled();
    expect(prevSpy).toHaveBeenCalled();
  });
});
