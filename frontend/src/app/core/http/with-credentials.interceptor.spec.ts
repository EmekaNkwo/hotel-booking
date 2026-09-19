import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { withCredentialsInterceptor } from './with-credentials.interceptor';
import { environment } from '../../../environments/environment';

describe('withCredentialsInterceptor', () => {
  let http: HttpClient;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([withCredentialsInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    http = TestBed.inject(HttpClient);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('sets withCredentials on requests to the API base URL', () => {
    http.get(`${environment.apiBaseUrl}/auth/me/`).subscribe();

    const req = httpMock.expectOne(`${environment.apiBaseUrl}/auth/me/`);
    expect(req.request.withCredentials).toBe(true);
    req.flush({});
  });

  it('leaves requests outside the API base URL untouched', () => {
    http.get('https://other-host.example/thing').subscribe();

    const req = httpMock.expectOne('https://other-host.example/thing');
    expect(req.request.withCredentials).toBe(false);
    req.flush({});
  });
});
