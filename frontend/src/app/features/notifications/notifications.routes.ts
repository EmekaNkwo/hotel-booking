import { Routes } from '@angular/router';

export const notificationsRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./pages/notification-list-page').then((m) => m.NotificationListPage),
  },
  {
    path: ':id',
    loadComponent: () =>
      import('./pages/notification-detail-page').then((m) => m.NotificationDetailPage),
  },
];
