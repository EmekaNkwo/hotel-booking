import { Routes } from '@angular/router';

export const availabilityRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./pages/availability-search-page').then((m) => m.AvailabilitySearchPage),
  },
];
