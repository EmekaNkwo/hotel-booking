import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';

import { Login } from './login';
import { AuthService } from '../../core/auth/auth.service';
import { TenantService } from '../../core/tenant/tenant.service';
import { toApiError } from '../../shared/models/api-error.model';

describe('Login', () => {
  let fixture: ComponentFixture<Login>;
  let component: Login;
  let authService: AuthService;
  let tenantService: TenantService;
  let router: Router;

  beforeEach(async () => {
    TestBed.configureTestingModule({
      imports: [Login],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([{ path: '', children: [] }]),
      ],
    });
    fixture = TestBed.createComponent(Login);
    component = fixture.componentInstance;
    authService = TestBed.inject(AuthService);
    tenantService = TestBed.inject(TenantService);
    router = TestBed.inject(Router);
    vi.spyOn(tenantService, 'loadTenants').mockResolvedValue();
    vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    fixture.detectChanges();
  });

  it('shows a validation error and does not submit with an empty form', async () => {
    const loginSpy = vi.spyOn(authService, 'login');

    await component.submitCredentials();

    expect(loginSpy).not.toHaveBeenCalled();
    expect(component['credentialsForm'].controls.email.touched).toBe(true);
  });

  it('rejects an invalid email format without calling the backend', async () => {
    const loginSpy = vi.spyOn(authService, 'login');
    component['credentialsForm'].setValue({ email: 'not-an-email', password: 'x' });

    await component.submitCredentials();

    expect(loginSpy).not.toHaveBeenCalled();
    expect(component['credentialsForm'].controls.email.hasError('email')).toBe(true);
  });

  it('on backend login failure, surfaces the error and does not navigate', async () => {
    component['credentialsForm'].setValue({ email: 'owner@acme.example', password: 'wrong' });
    vi.spyOn(authService, 'login').mockImplementation(async () => {
      const error = toApiError(401, { detail: 'invalid credentials.' });
      authService.error.set(error);
      return { kind: 'error', error };
    });

    await component.submitCredentials();

    expect(authService.error()?.message).toBe('invalid credentials.');
    expect(router.navigateByUrl).not.toHaveBeenCalled();
  });

  it('on successful login, loads tenants and navigates into the app', async () => {
    component['credentialsForm'].setValue({ email: 'owner@acme.example', password: 'secret' });
    vi.spyOn(authService, 'login').mockResolvedValue({ kind: 'authenticated' });

    await component.submitCredentials();

    expect(tenantService.loadTenants).toHaveBeenCalled();
    expect(router.navigateByUrl).toHaveBeenCalledWith('/');
  });

  it('on requires_mfa, switches to the code step without navigating', async () => {
    component['credentialsForm'].setValue({ email: 'owner@acme.example', password: 'secret' });
    vi.spyOn(authService, 'login').mockImplementation(async () => {
      authService.mfaPending.set(true);
      return { kind: 'mfa_required' };
    });

    await component.submitCredentials();

    expect(authService.mfaPending()).toBe(true);
    expect(router.navigateByUrl).not.toHaveBeenCalled();
  });

  it('submits the MFA code and navigates on success', async () => {
    authService.mfaPending.set(true);
    component['mfaForm'].setValue({ code: '123456' });
    vi.spyOn(authService, 'completeMfa').mockResolvedValue({ kind: 'authenticated' });

    await component.submitMfaCode();

    expect(authService.completeMfa).toHaveBeenCalledWith('123456');
    expect(router.navigateByUrl).toHaveBeenCalledWith('/');
  });

  it('rejects a malformed MFA code without calling the backend', async () => {
    authService.mfaPending.set(true);
    const spy = vi.spyOn(authService, 'completeMfa');
    component['mfaForm'].setValue({ code: '12' });

    await component.submitMfaCode();

    expect(spy).not.toHaveBeenCalled();
  });
});
