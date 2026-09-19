import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { GuestSearch } from './guest-search';
import { GuestStore } from '../store/guest.store';
import { GuestProfile } from '../models/guest.model';

const GUEST: GuestProfile = {
  id: 1, primary_email: 'jane@example.com', primary_phone: null,
  name: { given_name: 'Jane', family_name: '', display_name: 'Jane' },
  language: '', status: 'active', created_at: '2026-01-01T00:00:00Z',
};

describe('GuestSearch', () => {
  let fixture: ComponentFixture<GuestSearch>;
  let component: GuestSearch;
  let store: GuestStore;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [GuestSearch, NoopAnimationsModule],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    fixture = TestBed.createComponent(GuestSearch);
    component = fixture.componentInstance;
    store = TestBed.inject(GuestStore);
    fixture.detectChanges();
  });

  it('search button is disabled with a blank query', () => {
    expect(component['searchDisabled']()).toBe(true);
  });

  it('search() calls the store with the trimmed query', () => {
    const spy = vi.spyOn(store, 'search').mockResolvedValue();
    component['searchForm'].setValue({ q: '  jane  ' });

    component.search();

    expect(spy).toHaveBeenCalledWith('jane');
  });

  it('select() sets the store selection and emits guestSelected', () => {
    let emitted: GuestProfile | undefined;
    component.guestSelected.subscribe((g) => (emitted = g));

    component.select(GUEST);

    expect(store.selectedGuest()).toEqual(GUEST);
    expect(emitted).toEqual(GUEST);
  });

  it('create form is disabled with neither email nor phone filled', () => {
    expect(component['createDisabled']()).toBe(true);
    component['createForm'].patchValue({ email: 'x@example.com' });
    expect(component['createDisabled']()).toBe(false);
  });

  it('createGuest() resolves and emits the guest on success', async () => {
    const resolveSpy = vi.spyOn(store, 'resolve').mockResolvedValue(GUEST);
    let emitted: GuestProfile | undefined;
    component.guestSelected.subscribe((g) => (emitted = g));
    component['createForm'].patchValue({ email: 'jane@example.com', given_name: 'Jane' });

    await component.createGuest();

    expect(resolveSpy).toHaveBeenCalledWith(
      expect.objectContaining({ email: 'jane@example.com', given_name: 'Jane' }),
    );
    expect(emitted).toEqual(GUEST);
    expect(component['showCreateForm']()).toBe(false);
  });

  it('createGuest() does not emit on failure', async () => {
    vi.spyOn(store, 'resolve').mockResolvedValue(null);
    let emitted: GuestProfile | undefined;
    component.guestSelected.subscribe((g) => (emitted = g));
    component['createForm'].patchValue({ email: 'bad' });

    await component.createGuest();

    expect(emitted).toBeUndefined();
  });
});
