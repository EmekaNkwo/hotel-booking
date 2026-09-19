import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideHttpClient } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';

import { TenantService } from './tenant.service';
import { environment } from '../../../environments/environment';

describe('TenantService', () => {
  let service: TenantService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    sessionStorage.clear();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(TenantService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
    sessionStorage.clear();
  });

  it('loadTenants() auto-selects when exactly one tenant is returned', async () => {
    const promise = service.loadTenants();

    const req = httpMock.expectOne(`${environment.apiBaseUrl}/tenants/`);
    expect(req.request.method).toBe('GET');
    req.flush([
      { tenant_id: 7, code: 'acme', name: 'Acme', tenant_status: 'active', membership_status: 'active', role_names: ['tenant_owner'] },
    ]);

    await promise;
    expect(service.tenants().length).toBe(1);
    expect(service.selectedTenantId()).toBe(7);
    expect(service.needsSelection()).toBe(false);
  });

  it('loadTenants() leaves selection unresolved when multiple tenants exist and none is persisted', async () => {
    const promise = service.loadTenants();

    const req = httpMock.expectOne(`${environment.apiBaseUrl}/tenants/`);
    req.flush([
      { tenant_id: 1, code: 'acme', name: 'Acme', tenant_status: 'active', membership_status: 'active', role_names: [] },
      { tenant_id: 2, code: 'beta', name: 'Beta', tenant_status: 'active', membership_status: 'active', role_names: [] },
    ]);

    await promise;
    expect(service.tenants().length).toBe(2);
    expect(service.selectedTenantId()).toBeNull();
    expect(service.needsSelection()).toBe(true);
  });

  it('selectTenant() updates the signal and persists to sessionStorage', async () => {
    const promise = service.loadTenants();
    const req = httpMock.expectOne(`${environment.apiBaseUrl}/tenants/`);
    req.flush([
      { tenant_id: 1, code: 'acme', name: 'Acme', tenant_status: 'active', membership_status: 'active', role_names: [] },
      { tenant_id: 2, code: 'beta', name: 'Beta', tenant_status: 'active', membership_status: 'active', role_names: [] },
    ]);
    await promise;

    service.selectTenant(2);

    expect(service.selectedTenantId()).toBe(2);
    expect(service.selectedTenant()?.code).toBe('beta');
    expect(sessionStorage.getItem('hbp.selectedTenantId')).toBe('2');
  });

  it('a previously persisted tenant id is honored on the next loadTenants()', async () => {
    sessionStorage.setItem('hbp.selectedTenantId', '2');
    // The persisted value is read at construction — reset the testing
    // module so a fresh instance picks it up (the beforeEach instance was
    // already constructed before this test set the storage key).
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(TenantService);
    httpMock = TestBed.inject(HttpTestingController);

    const promise = service.loadTenants();
    const req = httpMock.expectOne(`${environment.apiBaseUrl}/tenants/`);
    req.flush([
      { tenant_id: 1, code: 'acme', name: 'Acme', tenant_status: 'active', membership_status: 'active', role_names: [] },
      { tenant_id: 2, code: 'beta', name: 'Beta', tenant_status: 'active', membership_status: 'active', role_names: [] },
    ]);
    await promise;

    expect(service.selectedTenantId()).toBe(2);
  });

  it('clear() resets tenants, selection, and storage', async () => {
    const promise = service.loadTenants();
    const req = httpMock.expectOne(`${environment.apiBaseUrl}/tenants/`);
    req.flush([
      { tenant_id: 7, code: 'acme', name: 'Acme', tenant_status: 'active', membership_status: 'active', role_names: [] },
    ]);
    await promise;

    service.clear();

    expect(service.tenants()).toEqual([]);
    expect(service.selectedTenantId()).toBeNull();
    expect(sessionStorage.getItem('hbp.selectedTenantId')).toBeNull();
  });
});
