import { Routes } from '@angular/router';

export const housekeepingRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./pages/housekeeping-list-page').then((m) => m.HousekeepingListPage),
  },
  {
    path: ':id',
    loadComponent: () =>
      import('./pages/housekeeping-detail-page').then((m) => m.HousekeepingDetailPage),
  },
];
