import { Routes } from '@angular/router';

export const bookingsRoutes: Routes = [
  {
    path: '',
    loadComponent: () => import('./pages/booking-list-page').then((m) => m.BookingListPage),
  },
  {
    path: ':id',
    loadComponent: () => import('./pages/booking-detail-page').then((m) => m.BookingDetailPage),
  },
];
