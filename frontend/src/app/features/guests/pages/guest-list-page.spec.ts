import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { GuestListPage } from './guest-list-page';
import { GuestStore } from '../store/guest.store';
import { GuestProfile } from '../models/guest.model';

const GUEST: GuestProfile = {
  id: 1, primary_email: 'jane@example.com', primary_phone: null,
  name: { given_name: 'Jane', family_name: 'Doe', display_name: 'Jane Doe' },
  language: '', status: 'active', created_at: '2026-01-01T00:00:00Z',
};

describe('GuestListPage', () => {
  let fixture: ComponentFixture<GuestListPage>;
  let component: GuestListPage;
  let store: GuestStore;
  let router: Router;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [GuestListPage, NoopAnimationsModule],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([{ path: 'guests/:id', children: [] }])],
    });
    fixture = TestBed.createComponent(GuestListPage);
    component = fixture.componentInstance;
    store = TestBed.inject(GuestStore);
    router = TestBed.inject(Router);
    vi.spyOn(store, 'search').mockResolvedValue();
    fixture.detectChanges();
  });

  it('loads all guests (empty query) on init', () => {
    expect(store.search).toHaveBeenCalledWith('');
  });

  it('search() calls the store with the trimmed query field', () => {
    component['searchForm'].setValue({ q: '  jane  ' });
    component.search();
    expect(store.search).toHaveBeenCalledWith('jane');
  });

  it('shows an empty state with no results', () => {
    store.searchResults.set([]);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('app-empty-state')).toBeTruthy();
  });

  it('renders a row per guest from the store', () => {
    store.searchResults.set([GUEST]);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Jane Doe');
  });

  it('createGuest() resolves via the store and navigates to the new guest detail', async () => {
    const resolveSpy = vi.spyOn(store, 'resolve').mockResolvedValue(GUEST);
    const navigateSpy = vi.spyOn(router, 'navigate').mockResolvedValue(true);
    component['createForm'].patchValue({ email: 'jane@example.com', given_name: 'Jane' });

    await component.createGuest();

    expect(resolveSpy).toHaveBeenCalledWith(
      expect.objectContaining({ email: 'jane@example.com', given_name: 'Jane' }),
    );
    expect(navigateSpy).toHaveBeenCalledWith(['/guests', 1]);
    expect(component['showCreateForm']()).toBe(false);
  });

  it('createGuest() does not navigate on failure', async () => {
    vi.spyOn(store, 'resolve').mockResolvedValue(null);
    const navigateSpy = vi.spyOn(router, 'navigate');
    component['createForm'].patchValue({ email: 'bad' });

    await component.createGuest();

    expect(navigateSpy).not.toHaveBeenCalled();
  });

  it('create form is disabled with neither email nor phone', () => {
    expect(component['createDisabled']()).toBe(true);
    component['createForm'].patchValue({ phone: '+15551234567' });
    expect(component['createDisabled']()).toBe(false);
  });
});
