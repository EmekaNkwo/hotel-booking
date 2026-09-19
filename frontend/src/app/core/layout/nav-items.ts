export interface NavItem {
  label: string;
  path: string;
  icon: string;
}

/** The sidebar's fixed nav list (A1 §9). All entries now resolve to real
 * feature areas: Reservations/Availability (A2), Guests/Bookings (A3),
 * Rooms (A4), Housekeeping (A5), Dashboard/Notifications (A6). */
export const NAV_ITEMS: NavItem[] = [
  { label: 'Dashboard', path: '/dashboard', icon: 'dashboard' },
  { label: 'Reservations', path: '/reservations', icon: 'event_available' },
  { label: 'Guests', path: '/guests', icon: 'people' },
  { label: 'Availability', path: '/availability', icon: 'calendar_month' },
  { label: 'Bookings', path: '/bookings', icon: 'book_online' },
  { label: 'Rooms', path: '/rooms', icon: 'meeting_room' },
  { label: 'Housekeeping', path: '/housekeeping', icon: 'cleaning_services' },
  { label: 'Notifications', path: '/notifications', icon: 'notifications' },
];
