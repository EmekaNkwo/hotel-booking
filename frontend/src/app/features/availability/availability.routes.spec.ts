import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { availabilityRoutes } from './availability.routes';
import { AvailabilityStore } from './store/availability.store';

describe('availability.routes', () => {
  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [NoopAnimationsModule],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([{ path: '', children: availabilityRoutes }]),
      ],
    });
    vi.spyOn(TestBed.inject(AvailabilityStore), 'loadReferenceData').mockResolvedValue();
  });

  it('"" resolves to the availability search page', async () => {
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/');
    expect(harness.routeNativeElement?.querySelector('h1')?.textContent).toContain('Availability');
  });
});
