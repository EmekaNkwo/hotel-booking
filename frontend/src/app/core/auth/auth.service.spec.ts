import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideHttpClient } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';

import { AuthService } from './auth.service';
import { environment } from '../../../environments/environment';

describe('AuthService', () => {
  let service: AuthService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(AuthService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('login() success sets currentUser and authenticated', async () => {
    const promise = service.login('owner@acme.example', 'secret');

    const req = httpMock.expectOne(`${environment.apiBaseUrl}/auth/login/`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ email: 'owner@acme.example', password: 'secret' });
    req.flush({
      user: { id: 1, email: 'owner@acme.example', is_staff: false, is_active: true },
      memberships: [],
    });

    const outcome = await promise;
    expect(outcome.kind).toBe('authenticated');
    expect(service.authenticated()).toBe(true);
    expect(service.currentUser()?.email).toBe('owner@acme.example');
  });

  it('login() with requires_mfa sets mfaPending and does not authenticate', async () => {
    const promise = service.login('owner@acme.example', 'secret');

    const req = httpMock.expectOne(`${environment.apiBaseUrl}/auth/login/`);
    req.flush({ requires_mfa: true, expires_in: 300 });

    const outcome = await promise;
    expect(outcome.kind).toBe('mfa_required');
    expect(service.mfaPending()).toBe(true);
    expect(service.authenticated()).toBe(false);
  });

  it('login() backend failure surfaces the detail message and stays unauthenticated', async () => {
    const promise = service.login('owner@acme.example', 'wrong');

    const req = httpMock.expectOne(`${environment.apiBaseUrl}/auth/login/`);
    req.flush({ detail: 'invalid credentials.' }, { status: 401, statusText: 'Unauthorized' });

    const outcome = await promise;
    expect(outcome.kind).toBe('error');
    if (outcome.kind === 'error') {
      expect(outcome.error.message).toBe('invalid credentials.');
      expect(outcome.error.status).toBe(401);
    }
    expect(service.authenticated()).toBe(false);
    expect(service.error()?.message).toBe('invalid credentials.');
  });

  it('completeMfa() success authenticates and clears mfaPending', async () => {
    service.mfaPending.set(true);
    const promise = service.completeMfa('123456');

    const req = httpMock.expectOne(`${environment.apiBaseUrl}/auth/mfa/`);
    expect(req.request.body).toEqual({ code: '123456' });
    req.flush({
      user: { id: 2, email: 'owner@acme.example', is_staff: false, is_active: true },
      memberships: [],
    });

    const outcome = await promise;
    expect(outcome.kind).toBe('authenticated');
    expect(service.mfaPending()).toBe(false);
    expect(service.authenticated()).toBe(true);
  });

  it('loadCurrentUser() restores session state from GET /api/auth/me/', async () => {
    const promise = service.loadCurrentUser();

    const req = httpMock.expectOne(`${environment.apiBaseUrl}/auth/me/`);
    expect(req.request.method).toBe('GET');
    req.flush({
      user: { id: 1, email: 'owner@acme.example', is_staff: false, is_active: true },
      memberships: [{ id: 1, tenant_id: 1, email: 'owner@acme.example', status: 'active', role_names: ['tenant_owner'] }],
      tenant_id: 1,
    });

    await promise;
    expect(service.authenticated()).toBe(true);
    expect(service.memberships().length).toBe(1);
  });

  it('loadCurrentUser() failure (no session) leaves the user unauthenticated', async () => {
    const promise = service.loadCurrentUser();

    const req = httpMock.expectOne(`${environment.apiBaseUrl}/auth/me/`);
    req.flush({ detail: 'authentication credentials were not provided.' }, { status: 401, statusText: 'Unauthorized' });

    await promise;
    expect(service.authenticated()).toBe(false);
    expect(service.currentUser()).toBeNull();
  });

  it('logout() clears local state even if already logged out server-side', async () => {
    service.currentUser.set({ id: 1, email: 'x@example.com', is_staff: false, is_active: true });

    const promise = service.logout();
    const req = httpMock.expectOne(`${environment.apiBaseUrl}/auth/logout/`);
    req.flush(null, { status: 204, statusText: 'No Content' });

    await promise;
    expect(service.authenticated()).toBe(false);
    expect(service.currentUser()).toBeNull();
  });
});
