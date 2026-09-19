import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { Shell } from './shell';
import { AuthService } from '../auth/auth.service';
import { TenantService } from '../tenant/tenant.service';
import { NAV_ITEMS } from './nav-items';

describe('Shell', () => {
  let fixture: ComponentFixture<Shell>;
  let authService: AuthService;
  let tenantService: TenantService;
  let router: Router;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [Shell, NoopAnimationsModule],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([{ path: 'login', children: [] }]),
      ],
    });
    authService = TestBed.inject(AuthService);
    tenantService = TestBed.inject(TenantService);
    router = TestBed.inject(Router);
    authService.currentUser.set({ id: 1, email: 'owner@acme.example', is_staff: false, is_active: true });
    fixture = TestBed.createComponent(Shell);
    // `reloadPage()` wraps `window.location.reload()` purely so it can be
    // stubbed here instead of fighting jsdom's non-configurable Location.
    vi.spyOn(fixture.componentInstance as unknown as { reloadPage(): void }, 'reloadPage')
      .mockImplementation(() => undefined);
  });

  it('renders every configured nav item', () => {
    fixture.detectChanges();
    const links = fixture.nativeElement.querySelectorAll('a[mat-list-item]');
    expect(links.length).toBe(NAV_ITEMS.length);
  });

  it('shows the tenant selector once tenants are loaded', () => {
    tenantService.tenants.set([
      { tenant_id: 1, code: 'acme', name: 'Acme', tenant_status: 'active', membership_status: 'active', role_names: ['tenant_owner'] },
    ]);
    fixture.detectChanges();

    const select = fixture.nativeElement.querySelector('mat-select.tenant-select');
    expect(select).toBeTruthy();
  });

  it('gates the content area behind explicit tenant selection when ambiguous', () => {
    tenantService.tenants.set([
      { tenant_id: 1, code: 'acme', name: 'Acme', tenant_status: 'active', membership_status: 'active', role_names: [] },
      { tenant_id: 2, code: 'beta', name: 'Beta', tenant_status: 'active', membership_status: 'active', role_names: [] },
    ]);
    tenantService.selectedTenantId.set(null);
    fixture.detectChanges();

    const gate = fixture.nativeElement.querySelector('.tenant-gate');
    expect(gate).toBeTruthy();
  });

  it('logout() clears session and tenant state and navigates to /login', async () => {
    tenantService.tenants.set([
      { tenant_id: 1, code: 'acme', name: 'Acme', tenant_status: 'active', membership_status: 'active', role_names: [] },
    ]);
    fixture.detectChanges();
    vi.spyOn(authService, 'logout').mockResolvedValue();
    const navigateSpy = vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);

    await fixture.componentInstance.logout();

    expect(authService.logout).toHaveBeenCalled();
    expect(tenantService.tenants()).toEqual([]);
    expect(navigateSpy).toHaveBeenCalledWith('/login');
  });

  it('onSelectTenant() delegates to TenantService.selectTenant() and reloads (no stale tenant data survives on screen)', () => {
    fixture.detectChanges();
    const spy = vi.spyOn(tenantService, 'selectTenant');

    fixture.componentInstance.onSelectTenant(5);

    expect(spy).toHaveBeenCalledWith(5);
    expect((fixture.componentInstance as unknown as { reloadPage(): void }).reloadPage).toHaveBeenCalled();
  });
});
