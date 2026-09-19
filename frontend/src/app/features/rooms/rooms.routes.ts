import { Routes } from '@angular/router';

export const roomsRoutes: Routes = [
  {
    path: '',
    loadComponent: () => import('./pages/room-list-page').then((m) => m.RoomListPage),
  },
  {
    path: ':id',
    loadComponent: () => import('./pages/room-detail-page').then((m) => m.RoomDetailPage),
  },
];
