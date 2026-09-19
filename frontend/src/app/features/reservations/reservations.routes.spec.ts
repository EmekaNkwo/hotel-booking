import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { reservationsRoutes } from './reservations.routes';
import { ReservationStore } from './store/reservation.store';

describe('reservations.routes', () => {
  let store: ReservationStore;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [NoopAnimationsModule],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([{ path: '', children: reservationsRoutes }]),
      ],
    });
    store = TestBed.inject(ReservationStore);
    vi.spyOn(store, 'loadList').mockResolvedValue();
    vi.spyOn(store, 'loadOne').mockResolvedValue();
  });

  it('"" resolves to the reservation list page', async () => {
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/');
    expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toContain('Reservations');
  });

  it('"new" resolves to the new-reservation page', async () => {
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/new');
    expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toContain('New reservation');
  });

  it('":id" resolves to the detail page and loads that reservation', async () => {
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/42');
    expect(store.loadOne).toHaveBeenCalledWith(42);
  });
});
