import { Routes } from '@angular/router';

export const guestsRoutes: Routes = [
  {
    path: '',
    loadComponent: () => import('./pages/guest-list-page').then((m) => m.GuestListPage),
  },
  {
    path: ':id',
    loadComponent: () => import('./pages/guest-detail-page').then((m) => m.GuestDetailPage),
  },
];
