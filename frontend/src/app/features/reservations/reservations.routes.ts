import { Routes } from '@angular/router';

export const reservationsRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./pages/reservation-list-page').then((m) => m.ReservationListPage),
  },
  {
    path: 'new',
    loadComponent: () => import('./pages/reservation-new-page').then((m) => m.ReservationNewPage),
  },
  {
    path: ':id',
    loadComponent: () =>
      import('./pages/reservation-detail-page').then((m) => m.ReservationDetailPage),
  },
];
