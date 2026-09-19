import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { routes } from './app.routes';
import { AuthService } from './core/auth/auth.service';
import { AvailabilityStore } from './features/availability/store/availability.store';
import { ReservationStore } from './features/reservations/store/reservation.store';
import { BookingStore } from './features/bookings/store/booking.store';
import { GuestStore } from './features/guests/store/guest.store';
import { RoomStore } from './features/rooms/store/room.store';
import { HousekeepingStore } from './features/housekeeping/store/housekeeping.store';
import { NotificationStore } from './features/notifications/store/notification.store';
import { DashboardStore } from './features/dashboard/store/dashboard.store';

describe('app.routes', () => {
  let router: Router;
  let authService: AuthService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [NoopAnimationsModule],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter(routes)],
    });
    router = TestBed.inject(Router);
    authService = TestBed.inject(AuthService);
    vi.spyOn(TestBed.inject(AvailabilityStore), 'loadReferenceData').mockResolvedValue();
    vi.spyOn(TestBed.inject(ReservationStore), 'loadList').mockResolvedValue();
    vi.spyOn(TestBed.inject(BookingStore), 'loadList').mockResolvedValue();
    vi.spyOn(TestBed.inject(GuestStore), 'search').mockResolvedValue();
    vi.spyOn(TestBed.inject(RoomStore), 'loadReferenceData').mockResolvedValue();
    vi.spyOn(TestBed.inject(RoomStore), 'loadList').mockResolvedValue();
    vi.spyOn(TestBed.inject(HousekeepingStore), 'loadList').mockResolvedValue();
    vi.spyOn(TestBed.inject(NotificationStore), 'loadList').mockResolvedValue();
    vi.spyOn(TestBed.inject(DashboardStore), 'loadAll').mockResolvedValue();
  });

  it('an unauthenticated user is redirected from a protected route to /login', async () => {
    const harness = await RouterTestingHarness.create();

    await harness.navigateByUrl('/dashboard');

    expect(router.url).toBe('/login');
  });

  it('/login renders for an unauthenticated user', async () => {
    const harness = await RouterTestingHarness.create();

    await harness.navigateByUrl('/login');

    expect(router.url).toBe('/login');
  });

  it('an authenticated user is redirected away from /login into the shell', async () => {
    authService.currentUser.set({ id: 1, email: 'a@b.com', is_staff: false, is_active: true });
    const harness = await RouterTestingHarness.create();

    await harness.navigateByUrl('/login');

    expect(router.url).toBe('/dashboard');
  });

  it('an authenticated user can reach a protected route, and "/" redirects to /dashboard', async () => {
    authService.currentUser.set({ id: 1, email: 'a@b.com', is_staff: false, is_active: true });
    const harness = await RouterTestingHarness.create();

    await harness.navigateByUrl('/');

    expect(router.url).toBe('/dashboard');
  });

  it('an unknown path falls back to the root (and onward through the guards)', async () => {
    const harness = await RouterTestingHarness.create();

    await harness.navigateByUrl('/some/unknown/path');

    expect(router.url).toBe('/login');
  });

  it('an authenticated user can reach /availability', async () => {
    authService.currentUser.set({ id: 1, email: 'a@b.com', is_staff: false, is_active: true });
    const harness = await RouterTestingHarness.create();

    await harness.navigateByUrl('/availability');

    expect(router.url).toBe('/availability');
  });

  it('an authenticated user can reach /reservations', async () => {
    authService.currentUser.set({ id: 1, email: 'a@b.com', is_staff: false, is_active: true });
    const harness = await RouterTestingHarness.create();

    await harness.navigateByUrl('/reservations');

    expect(router.url).toBe('/reservations');
  });

  it('an authenticated user can reach /reservations/new', async () => {
    authService.currentUser.set({ id: 1, email: 'a@b.com', is_staff: false, is_active: true });
    const harness = await RouterTestingHarness.create();

    await harness.navigateByUrl('/reservations/new');

    expect(router.url).toBe('/reservations/new');
  });

  it('an authenticated user can reach /reservations/:id', async () => {
    authService.currentUser.set({ id: 1, email: 'a@b.com', is_staff: false, is_active: true });
    vi.spyOn(TestBed.inject(ReservationStore), 'loadOne').mockResolvedValue();
    const harness = await RouterTestingHarness.create();

    await harness.navigateByUrl('/reservations/42');

    expect(router.url).toBe('/reservations/42');
  });

  it('an authenticated user can reach /bookings', async () => {
    authService.currentUser.set({ id: 1, email: 'a@b.com', is_staff: false, is_active: true });
    const harness = await RouterTestingHarness.create();

    await harness.navigateByUrl('/bookings');

    expect(router.url).toBe('/bookings');
  });

  it('an authenticated user can reach /bookings/:id', async () => {
    authService.currentUser.set({ id: 1, email: 'a@b.com', is_staff: false, is_active: true });
    vi.spyOn(TestBed.inject(BookingStore), 'loadOne').mockResolvedValue();
    const harness = await RouterTestingHarness.create();

    await harness.navigateByUrl('/bookings/7');

    expect(router.url).toBe('/bookings/7');
  });

  it('an authenticated user can reach /guests', async () => {
    authService.currentUser.set({ id: 1, email: 'a@b.com', is_staff: false, is_active: true });
    const harness = await RouterTestingHarness.create();

    await harness.navigateByUrl('/guests');

    expect(router.url).toBe('/guests');
  });

  it('an authenticated user can reach /guests/:id', async () => {
    authService.currentUser.set({ id: 1, email: 'a@b.com', is_staff: false, is_active: true });
    vi.spyOn(TestBed.inject(GuestStore), 'loadOne').mockResolvedValue();
    const harness = await RouterTestingHarness.create();

    await harness.navigateByUrl('/guests/9');

    expect(router.url).toBe('/guests/9');
  });

  it('an authenticated user can reach /rooms', async () => {
    authService.currentUser.set({ id: 1, email: 'a@b.com', is_staff: false, is_active: true });
    const harness = await RouterTestingHarness.create();

    await harness.navigateByUrl('/rooms');

    expect(router.url).toBe('/rooms');
  });

  it('an authenticated user can reach /rooms/:id', async () => {
    authService.currentUser.set({ id: 1, email: 'a@b.com', is_staff: false, is_active: true });
    vi.spyOn(TestBed.inject(RoomStore), 'loadOne').mockResolvedValue();
    const harness = await RouterTestingHarness.create();

    await harness.navigateByUrl('/rooms/3');

    expect(router.url).toBe('/rooms/3');
  });

  it('an authenticated user can reach /housekeeping', async () => {
    authService.currentUser.set({ id: 1, email: 'a@b.com', is_staff: false, is_active: true });
    const harness = await RouterTestingHarness.create();

    await harness.navigateByUrl('/housekeeping');

    expect(router.url).toBe('/housekeeping');
  });

  it('an authenticated user can reach /housekeeping/:id', async () => {
    authService.currentUser.set({ id: 1, email: 'a@b.com', is_staff: false, is_active: true });
    vi.spyOn(TestBed.inject(HousekeepingStore), 'loadOne').mockResolvedValue();
    const harness = await RouterTestingHarness.create();

    await harness.navigateByUrl('/housekeeping/4');

    expect(router.url).toBe('/housekeeping/4');
  });

  it('an authenticated user can reach /dashboard', async () => {
    authService.currentUser.set({ id: 1, email: 'a@b.com', is_staff: false, is_active: true });
    const harness = await RouterTestingHarness.create();

    await harness.navigateByUrl('/dashboard');

    expect(router.url).toBe('/dashboard');
  });

  it('an authenticated user can reach /notifications', async () => {
    authService.currentUser.set({ id: 1, email: 'a@b.com', is_staff: false, is_active: true });
    const harness = await RouterTestingHarness.create();

    await harness.navigateByUrl('/notifications');

    expect(router.url).toBe('/notifications');
  });

  it('an authenticated user can reach /notifications/:id', async () => {
    authService.currentUser.set({ id: 1, email: 'a@b.com', is_staff: false, is_active: true });
    vi.spyOn(TestBed.inject(NotificationStore), 'loadOne').mockResolvedValue();
    const harness = await RouterTestingHarness.create();

    await harness.navigateByUrl('/notifications/11');

    expect(router.url).toBe('/notifications/11');
  });
});
