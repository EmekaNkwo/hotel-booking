import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { tenantInterceptor } from './tenant.interceptor';
import { TenantService } from '../tenant/tenant.service';
import { environment } from '../../../environments/environment';

describe('tenantInterceptor', () => {
  let http: HttpClient;
  let httpMock: HttpTestingController;
  let tenantService: TenantService;

  beforeEach(() => {
    sessionStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([tenantInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    http = TestBed.inject(HttpClient);
    httpMock = TestBed.inject(HttpTestingController);
    tenantService = TestBed.inject(TenantService);
  });

  afterEach(() => {
    httpMock.verify();
    sessionStorage.clear();
  });

  it('attaches X-Tenant-Id when a tenant is selected', () => {
    tenantService.selectTenant(42);

    http.get(`${environment.apiBaseUrl}/reservations/`).subscribe();

    const req = httpMock.expectOne(`${environment.apiBaseUrl}/reservations/`);
    expect(req.request.headers.get('X-Tenant-Id')).toBe('42');
    req.flush([]);
  });

  it('sends no X-Tenant-Id header when no tenant is selected', () => {
    http.get(`${environment.apiBaseUrl}/tenants/`).subscribe();

    const req = httpMock.expectOne(`${environment.apiBaseUrl}/tenants/`);
    expect(req.request.headers.has('X-Tenant-Id')).toBe(false);
    req.flush([]);
  });

  it('updates the header automatically after switching tenants', () => {
    tenantService.selectTenant(1);
    http.get(`${environment.apiBaseUrl}/reservations/`).subscribe();
    httpMock.expectOne(`${environment.apiBaseUrl}/reservations/`).flush([]);

    tenantService.selectTenant(2);
    http.get(`${environment.apiBaseUrl}/reservations/`).subscribe();
    const req = httpMock.expectOne(`${environment.apiBaseUrl}/reservations/`);
    expect(req.request.headers.get('X-Tenant-Id')).toBe('2');
    req.flush([]);
  });

  it('does not touch requests outside the API base URL', () => {
    tenantService.selectTenant(42);

    http.get('https://other-host.example/thing').subscribe();

    const req = httpMock.expectOne('https://other-host.example/thing');
    expect(req.request.headers.has('X-Tenant-Id')).toBe(false);
    req.flush({});
  });
});
