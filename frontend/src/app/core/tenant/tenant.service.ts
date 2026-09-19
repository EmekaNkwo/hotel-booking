import { Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { TenantApiService } from '../api/tenant-api.service';
import { TenantMembership } from '../../shared/models/tenant.model';
import { ApiError, fromHttpError } from '../../shared/models/api-error.model';

const STORAGE_KEY = 'hbp.selectedTenantId';

/** Tenant list + selection state (signals only). The selected tenant id is
 * the ONLY thing persisted (sessionStorage — cleared with the tab, never
 * localStorage) — no authentication data is ever written to storage. */
@Injectable({ providedIn: 'root' })
export class TenantService {
  private readonly api = inject(TenantApiService);

  readonly tenants = signal<TenantMembership[]>([]);
  readonly selectedTenantId = signal<number | null>(readPersistedTenantId());
  readonly loading = signal(false);
  readonly error = signal<ApiError | null>(null);

  readonly selectedTenant = computed(() => {
    const id = this.selectedTenantId();
    return this.tenants().find((t) => t.tenant_id === id) ?? null;
  });

  /** Requires a tenant selection before the shell can be entered. */
  readonly needsSelection = computed(
    () => this.tenants().length > 0 && this.selectedTenantId() === null,
  );

  /** Load the user's accessible tenants and auto-select only when the
   * backend response makes the choice unambiguous (exactly one tenant, or a
   * previously-persisted id that is still valid). */
  async loadTenants(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      const tenants = await firstValueFrom(this.api.list());
      this.tenants.set(tenants);

      const persisted = this.selectedTenantId();
      const persistedIsValid = tenants.some((t) => t.tenant_id === persisted);
      if (persistedIsValid) {
        return;
      }
      if (tenants.length === 1) {
        this.selectTenant(tenants[0].tenant_id);
      } else {
        this.selectedTenantId.set(null);
        persistTenantId(null);
      }
    } catch (err) {
      this.error.set(fromHttpError(err));
    } finally {
      this.loading.set(false);
    }
  }

  selectTenant(tenantId: number): void {
    this.selectedTenantId.set(tenantId);
    persistTenantId(tenantId);
  }

  /** Called on logout / 401 recovery — no tenant-scoped state should
   * survive into a different session. */
  clear(): void {
    this.tenants.set([]);
    this.selectedTenantId.set(null);
    this.error.set(null);
    persistTenantId(null);
  }
}

function readPersistedTenantId(): number | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    return raw ? Number(raw) : null;
  } catch {
    return null;
  }
}

function persistTenantId(id: number | null): void {
  try {
    if (id === null) {
      sessionStorage.removeItem(STORAGE_KEY);
    } else {
      sessionStorage.setItem(STORAGE_KEY, String(id));
    }
  } catch {
    // Storage unavailable (private browsing, etc.) — selection still works
    // for the current session via the signal; it just won't survive reload.
  }
}

