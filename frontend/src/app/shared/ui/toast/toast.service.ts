import { Injectable, inject } from '@angular/core';
import { MatSnackBar } from '@angular/material/snack-bar';

/** Thin wrapper over MatSnackBar — the global toast/notification surface.
 * No abstraction beyond what A1 needs: an error, and a brief confirmation. */
@Injectable({ providedIn: 'root' })
export class ToastService {
  private readonly snackBar = inject(MatSnackBar);

  error(message: string): void {
    this.snackBar.open(message, 'Dismiss', {
      duration: 6000,
      panelClass: ['hbp-toast', 'hbp-toast--error'],
      horizontalPosition: 'end',
      verticalPosition: 'top',
    });
  }

  info(message: string): void {
    this.snackBar.open(message, undefined, {
      duration: 4000,
      panelClass: ['hbp-toast'],
      horizontalPosition: 'end',
      verticalPosition: 'top',
    });
  }
}
