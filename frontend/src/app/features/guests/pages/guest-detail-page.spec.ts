import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap } from '@angular/router';

import { GuestDetailPage } from './guest-detail-page';
import { GuestStore } from '../store/guest.store';
import { GuestProfile } from '../models/guest.model';

const GUEST: GuestProfile = {
  id: 4, primary_email: 'd@example.com', primary_phone: '+15551234567',
  name: { given_name: 'D', family_name: 'Guest', display_name: 'D Guest' },
  language: 'en', status: 'active', created_at: '2026-01-01T00:00:00Z',
};

describe('GuestDetailPage', () => {
  let fixture: ComponentFixture<GuestDetailPage>;
  let store: GuestStore;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [GuestDetailPage],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: ActivatedRoute, useValue: { snapshot: { paramMap: convertToParamMap({ id: '4' }) } } },
      ],
    });
    fixture = TestBed.createComponent(GuestDetailPage);
    store = TestBed.inject(GuestStore);
    vi.spyOn(store, 'loadOne').mockResolvedValue();
    fixture.detectChanges();
  });

  it('loads the guest by the route id on init', () => {
    expect(store.loadOne).toHaveBeenCalledWith(4);
  });

  it('renders the authoritative guest fields once loaded', () => {
    store.current.set(GUEST);
    fixture.detectChanges();
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('D Guest');
    expect(text).toContain('d@example.com');
    expect(text).toContain('+15551234567');
    expect(text).toContain('en');
  });

  it('renders the backend error message on a detail failure', () => {
    store.current.set(null);
    store.detailError.set({ status: 404, message: 'guest not found.', raw: null });
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('guest not found.');
  });

  it('does not render any edit/update controls (no backend update endpoint)', () => {
    store.current.set(GUEST);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('form')).toBeNull();
    expect(fixture.nativeElement.querySelector('button')).toBeNull();
  });
});
