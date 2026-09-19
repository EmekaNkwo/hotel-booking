import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';

import { errorInterceptor, NormalizedHttpError } from './error.interceptor';
import { AuthService } from '../auth/auth.service';
import { TenantService } from '../tenant/tenant.service';
import { ToastService } from '../../shared/ui/toast/toast.service';
import { environment } from '../../../environments/environment';

describe('errorInterceptor', () => {
  let http: HttpClient;
  let httpMock: HttpTestingController;
  let router: Router;
  let authService: AuthService;
  let tenantService: TenantService;
  let toast: { error: ReturnType<typeof vi.fn>; info: ReturnType<typeof vi.fn> };

  beforeEach(async () => {
    toast = { error: vi.fn(), info: vi.fn() };
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([
          { path: 'login', loadComponent: () => import('../../features/placeholder/placeholder').then((m) => m.Placeholder) },
          { path: '', loadComponent: () => import('../../features/placeholder/placeholder').then((m) => m.Placeholder) },
        ]),
        { provide: ToastService, useValue: toast },
      ],
    });
    http = TestBed.inject(HttpClient);
    httpMock = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
    authService = TestBed.inject(AuthService);
    tenantService = TestBed.inject(TenantService);
    // Establish the router's initial navigation so router.url is defined.
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/');
  });

  afterEach(() => httpMock.verify());

  it('normalizes a 409 conflict and preserves the backend detail message', async () => {
    let caught: NormalizedHttpError | undefined;
    http.post(`${environment.apiBaseUrl}/bookings/confirm/`, {}).subscribe({
      error: (err) => (caught = err),
    });

    httpMock
      .expectOne(`${environment.apiBaseUrl}/bookings/confirm/`)
      .flush({ detail: 'reservation is not awaiting payment.' }, { status: 409, statusText: 'Conflict' });

    await Promise.resolve();
    expect(caught?.apiError.status).toBe(409);
    expect(caught?.apiError.message).toBe('reservation is not awaiting payment.');
    expect(toast.error).not.toHaveBeenCalled();
  });

  it('normalizes a 403 without toasting (left for the component to render)', async () => {
    let caught: NormalizedHttpError | undefined;
    http.get(`${environment.apiBaseUrl}/rooms/`).subscribe({ error: (err) => (caught = err) });

    httpMock
      .expectOne(`${environment.apiBaseUrl}/rooms/`)
      .flush({ detail: 'not a member of the requested tenant' }, { status: 403, statusText: 'Forbidden' });

    await Promise.resolve();
    expect(caught?.apiError.message).toBe('not a member of the requested tenant');
    expect(toast.error).not.toHaveBeenCalled();
  });

  it('a 401 on an already-authenticated session clears state and redirects to /login', async () => {
    authService.currentUser.set({ id: 1, email: 'a@b.com', is_staff: false, is_active: true });
    tenantService.selectTenant(9);

    // The interceptor's own side effects are what this test verifies; the
    // subscriber just needs to exist so the error doesn't surface unhandled.
    http.get(`${environment.apiBaseUrl}/rooms/`).subscribe({ error: () => undefined });
    httpMock
      .expectOne(`${environment.apiBaseUrl}/rooms/`)
      .flush({ detail: 'session expired' }, { status: 401, statusText: 'Unauthorized' });

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(authService.authenticated()).toBe(false);
    expect(tenantService.selectedTenantId()).toBeNull();
    expect(router.url).toBe('/login');
  });

  it('a 401 on the login endpoint itself does not redirect (no loop)', async () => {
    let caught: NormalizedHttpError | undefined;
    http.post(`${environment.apiBaseUrl}/auth/login/`, {}).subscribe({
      error: (err) => (caught = err),
    });

    httpMock
      .expectOne(`${environment.apiBaseUrl}/auth/login/`)
      .flush({ detail: 'invalid credentials.' }, { status: 401, statusText: 'Unauthorized' });

    await Promise.resolve();
    expect(caught?.apiError.message).toBe('invalid credentials.');
    expect(router.url).toBe('/');
  });

  it('a 500 server error shows a toast', async () => {
    http.get(`${environment.apiBaseUrl}/rooms/`).subscribe({ error: () => undefined });

    httpMock.expectOne(`${environment.apiBaseUrl}/rooms/`).flush(
      { detail: 'internal error' },
      { status: 500, statusText: 'Internal Server Error' },
    );

    await Promise.resolve();
    expect(toast.error).toHaveBeenCalled();
  });

  it('a network error (status 0) shows a toast with a connectivity message', async () => {
    let caught: NormalizedHttpError | undefined;
    http.get(`${environment.apiBaseUrl}/rooms/`).subscribe({ error: (err) => (caught = err) });

    httpMock.expectOne(`${environment.apiBaseUrl}/rooms/`).error(new ProgressEvent('error'), {
      status: 0,
      statusText: 'Unknown Error',
    });

    await Promise.resolve();
    expect(caught?.apiError.message).toBe('Could not reach the server. Check your connection.');
    expect(toast.error).toHaveBeenCalled();
  });
});
