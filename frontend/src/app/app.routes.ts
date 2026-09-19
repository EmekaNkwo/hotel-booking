import { Routes } from '@angular/router';

import { authGuard, guestGuard } from './core/auth/auth.guard';

export const routes: Routes = [
  {
    path: 'login',
    loadComponent: () => import('./features/login/login').then((m) => m.Login),
    canActivate: [guestGuard],
  },
  {
    path: '',
    loadComponent: () => import('./core/layout/shell').then((m) => m.Shell),
    canActivate: [authGuard],
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'dashboard' },
      {
        path: 'dashboard',
        loadComponent: () => import('./features/dashboard/pages/dashboard-page').then((m) => m.DashboardPage),
      },
      {
        path: 'reservations',
        loadChildren: () =>
          import('./features/reservations/reservations.routes').then((m) => m.reservationsRoutes),
      },
      {
        path: 'guests',
        loadChildren: () => import('./features/guests/guests.routes').then((m) => m.guestsRoutes),
      },
      {
        path: 'availability',
        loadChildren: () =>
          import('./features/availability/availability.routes').then((m) => m.availabilityRoutes),
      },
      {
        path: 'bookings',
        loadChildren: () =>
          import('./features/bookings/bookings.routes').then((m) => m.bookingsRoutes),
      },
      {
        path: 'rooms',
        loadChildren: () => import('./features/rooms/rooms.routes').then((m) => m.roomsRoutes),
      },
      {
        path: 'housekeeping',
        loadChildren: () =>
          import('./features/housekeeping/housekeeping.routes').then((m) => m.housekeepingRoutes),
      },
      {
        path: 'notifications',
        loadChildren: () =>
          import('./features/notifications/notifications.routes').then((m) => m.notificationsRoutes),
      },
    ],
  },
  { path: '**', redirectTo: '' },
];
