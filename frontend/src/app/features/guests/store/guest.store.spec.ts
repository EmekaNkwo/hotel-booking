import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideHttpClient } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';

import { GuestStore } from './guest.store';
import { environment } from '../../../../environments/environment';

describe('GuestStore', () => {
  let store: GuestStore;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    store = TestBed.inject(GuestStore);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('search() populates searchResults from the server', async () => {
    const promise = store.search('jane');
    const req = httpMock.expectOne((r) => r.url.includes('/guests/') && r.params.get('q') === 'jane');
    req.flush({
      count: 1,
      next: null,
      previous: null,
      results: [
        { id: 1, primary_email: 'jane@example.com', primary_phone: null, name: { given_name: 'Jane', family_name: '', display_name: 'Jane' }, language: '', status: 'active', created_at: '2026-01-01T00:00:00Z' },
      ],
    });
    await promise;
    expect(store.searchResults().length).toBe(1);
  });

  it('resolve() sets selectedGuest from the created/found guest', async () => {
    const promise = store.resolve({ email: 'new@example.com' });
    const req = httpMock.expectOne(`${environment.apiBaseUrl}/guests/create/`);
    expect(req.request.body).toEqual({ email: 'new@example.com' });
    req.flush(
      { id: 2, primary_email: 'new@example.com', primary_phone: null, name: {}, language: '', status: 'active', created_at: '2026-01-01T00:00:00Z' },
      { status: 201, statusText: 'Created' },
    );
    const guest = await promise;
    expect(guest?.id).toBe(2);
    expect(store.selectedGuest()?.id).toBe(2);
  });

  it('resolve() failure sets error and returns null, without selecting anything', async () => {
    const promise = store.resolve({});
    httpMock
      .expectOne(`${environment.apiBaseUrl}/guests/create/`)
      .flush({ detail: 'email or phone is required.' }, { status: 400, statusText: 'Bad Request' });
    const guest = await promise;
    expect(guest).toBeNull();
    expect(store.selectedGuest()).toBeNull();
    expect(store.error()?.message).toBe('email or phone is required.');
  });

  it('select()/clearSelection() manage the current selection locally (no request)', () => {
    store.select({ id: 3, primary_email: 'x@example.com', primary_phone: null, name: {}, language: '', status: 'active', created_at: '2026-01-01T00:00:00Z' });
    expect(store.selectedGuest()?.id).toBe(3);
    store.clearSelection();
    expect(store.selectedGuest()).toBeNull();
  });

  it('loadOne() populates current from the authoritative detail response', async () => {
    const promise = store.loadOne(4);
    httpMock.expectOne(`${environment.apiBaseUrl}/guests/4/`).flush({
      id: 4, primary_email: 'd@example.com', primary_phone: null,
      name: { given_name: 'D', family_name: '', display_name: 'D' },
      language: 'en', status: 'active', created_at: '2026-01-01T00:00:00Z',
    });
    await promise;
    expect(store.current()?.id).toBe(4);
  });

  it('loadOne() failure clears current and sets detailError (not the search error)', async () => {
    const promise = store.loadOne(999);
    httpMock
      .expectOne(`${environment.apiBaseUrl}/guests/999/`)
      .flush({ detail: 'guest not found.' }, { status: 404, statusText: 'Not Found' });
    await promise;
    expect(store.current()).toBeNull();
    expect(store.detailError()?.message).toBe('guest not found.');
    expect(store.error()).toBeNull();
  });

  describe('R1.1: pagination', () => {
    it('nextPage() loads page 2, replacing page 1\'s results, using the server\'s count/next/previous', async () => {
      const load1 = store.search('a');
      httpMock
        .expectOne((r) => r.params.get('page') === '1' && r.params.get('q') === 'a')
        .flush({
          count: 30, next: 'http://x/guests/?page=2&q=a', previous: null,
          results: [{ id: 1, primary_email: 'a1@example.com', primary_phone: null, name: {}, language: '', status: 'active', created_at: '2026-01-01T00:00:00Z' }],
        });
      await load1;
      expect(store.hasNextPage()).toBe(true);

      const load2 = store.nextPage();
      httpMock
        .expectOne((r) => r.params.get('page') === '2' && r.params.get('q') === 'a')
        .flush({
          count: 30, next: null, previous: 'http://x/guests/?page=1&q=a',
          results: [{ id: 2, primary_email: 'a2@example.com', primary_phone: null, name: {}, language: '', status: 'active', created_at: '2026-01-01T00:00:00Z' }],
        });
      await load2;
      expect(store.currentPage()).toBe(2);
      expect(store.searchResults().length).toBe(1);
      expect(store.searchResults()[0].id).toBe(2);
      expect(store.hasNextPage()).toBe(false);
    });

    it('previousPage() is a no-op on page 1', async () => {
      const load1 = store.search('');
      httpMock
        .expectOne((r) => r.params.get('page') === '1')
        .flush({ count: 1, next: null, previous: null, results: [] });
      await load1;
      await store.previousPage();
      httpMock.expectNone((r) => r.params.get('page') === '0');
    });
  });
});
