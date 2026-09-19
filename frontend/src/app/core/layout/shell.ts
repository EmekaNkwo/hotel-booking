import { BreakpointObserver, Breakpoints } from '@angular/cdk/layout';
import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { RouterLink, RouterLinkActive, RouterOutlet, Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatDividerModule } from '@angular/material/divider';
import { MatIconModule } from '@angular/material/icon';
import { MatListModule } from '@angular/material/list';
import { MatMenuModule } from '@angular/material/menu';
import { MatSelectModule } from '@angular/material/select';
import { MatSidenavModule } from '@angular/material/sidenav';
import { MatToolbarModule } from '@angular/material/toolbar';
import { map } from 'rxjs';

import { AuthService } from '../auth/auth.service';
import { TenantService } from '../tenant/tenant.service';
import { LoadingIndicator } from '../../shared/ui/loading-indicator/loading-indicator';
import { NAV_ITEMS } from './nav-items';

/** The authenticated application shell: top bar (tenant/user), sidebar nav,
 * and the routed page content. Tenant-scoped content is gated behind an
 * explicit selection when the backend leaves it ambiguous (A1 §5/§11). */
@Component({
  selector: 'app-shell',
  imports: [
    RouterLink,
    RouterLinkActive,
    RouterOutlet,
    MatButtonModule,
    MatDividerModule,
    MatIconModule,
    MatListModule,
    MatMenuModule,
    MatSelectModule,
    MatSidenavModule,
    MatToolbarModule,
    LoadingIndicator,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './shell.html',
  styleUrl: './shell.scss',
})
export class Shell {
  private readonly authService = inject(AuthService);
  private readonly tenantService = inject(TenantService);
  private readonly router = inject(Router);
  private readonly breakpointObserver = inject(BreakpointObserver);

  protected readonly navItems = NAV_ITEMS;
  protected readonly currentUser = this.authService.currentUser;
  protected readonly tenants = this.tenantService.tenants;
  protected readonly selectedTenant = this.tenantService.selectedTenant;
  protected readonly selectedTenantId = this.tenantService.selectedTenantId;
  protected readonly needsTenantSelection = this.tenantService.needsSelection;
  protected readonly loading = this.tenantService.loading;

  protected readonly isHandset = toSignal(
    this.breakpointObserver
      .observe([Breakpoints.Handset, Breakpoints.TabletPortrait])
      .pipe(map((result) => result.matches)),
    { initialValue: false },
  );

  /** A full reload is deliberate: every root-provided feature Store is a
   * singleton that otherwise keeps the previous tenant's already-loaded
   * data mounted on screen (the routed component doesn't change, so the
   * router never re-triggers a load) — reloading is the simplest way to
   * guarantee no tenant's data is ever visible while another is selected.
   * Split into its own method (rather than calling `location.reload()`
   * inline) purely so tests can stub it without touching jsdom's
   * non-configurable `Location`. */
  onSelectTenant(tenantId: number): void {
    this.tenantService.selectTenant(tenantId);
    this.reloadPage();
  }

  protected reloadPage(): void {
    window.location.reload();
  }

  async logout(): Promise<void> {
    await this.authService.logout();
    this.tenantService.clear();
    await this.router.navigateByUrl('/login');
  }
}
