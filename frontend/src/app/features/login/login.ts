import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ReactiveFormsModule, FormBuilder, Validators } from '@angular/forms';
import { Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';

import { AuthService } from '../../core/auth/auth.service';
import { TenantService } from '../../core/tenant/tenant.service';

/** The login screen. Two steps only because the backend genuinely has two
 * steps for MFA-required roles (`tenant_owner`) — confirmed from
 * `LoginView`/`MfaLoginView` in `apps/accounts/api/views.py`. No MFA UI is
 * invented beyond submitting the single TOTP code the backend's contract
 * calls for. */
@Component({
  selector: 'app-login',
  imports: [
    ReactiveFormsModule,
    MatButtonModule,
    MatCardModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressSpinnerModule,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './login.html',
  styleUrl: './login.scss',
})
export class Login {
  private readonly fb = inject(FormBuilder);
  private readonly authService = inject(AuthService);
  private readonly tenantService = inject(TenantService);
  private readonly router = inject(Router);

  protected readonly loading = this.authService.loading;
  protected readonly error = this.authService.error;
  protected readonly mfaPending = this.authService.mfaPending;
  protected readonly hidePassword = signal(true);

  protected readonly credentialsForm = this.fb.nonNullable.group({
    email: ['', [Validators.required, Validators.email]],
    password: ['', Validators.required],
  });

  protected readonly mfaForm = this.fb.nonNullable.group({
    code: ['', [Validators.required, Validators.pattern(/^\d{6}$/)]],
  });

  // `FormGroup.invalid` is a plain property, not a signal — reading it
  // inside `computed()` would never re-trigger recomputation as the user
  // types (only `loading()` would). `statusChanges` is the form's actual
  // reactive source, converted to a signal so validity is tracked properly.
  private readonly credentialsStatus = toSignal(this.credentialsForm.statusChanges, {
    initialValue: this.credentialsForm.status,
  });
  private readonly mfaStatus = toSignal(this.mfaForm.statusChanges, {
    initialValue: this.mfaForm.status,
  });

  protected readonly submitDisabled = computed(
    () => this.loading() || this.credentialsStatus() !== 'VALID',
  );
  protected readonly mfaSubmitDisabled = computed(
    () => this.loading() || this.mfaStatus() !== 'VALID',
  );

  async submitCredentials(): Promise<void> {
    if (this.credentialsForm.invalid) {
      this.credentialsForm.markAllAsTouched();
      return;
    }
    const { email, password } = this.credentialsForm.getRawValue();
    const outcome = await this.authService.login(email, password);
    if (outcome.kind === 'authenticated') {
      await this.enterApplication();
    }
    // 'mfa_required' switches the template to the code step via the
    // mfaPending signal; 'error' is rendered from authService.error().
  }

  async submitMfaCode(): Promise<void> {
    if (this.mfaForm.invalid) {
      this.mfaForm.markAllAsTouched();
      return;
    }
    const { code } = this.mfaForm.getRawValue();
    const outcome = await this.authService.completeMfa(code);
    if (outcome.kind === 'authenticated') {
      await this.enterApplication();
    }
  }

  private async enterApplication(): Promise<void> {
    await this.tenantService.loadTenants();
    await this.router.navigateByUrl('/');
  }
}
