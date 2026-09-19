import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { csrfInterceptor } from './csrf.interceptor';
import { environment } from '../../../environments/environment';

describe('csrfInterceptor', () => {
  let http: HttpClient;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    document.cookie = 'csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/';
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([csrfInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    http = TestBed.inject(HttpClient);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
    document.cookie = 'csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/';
  });

  it('attaches X-CSRFToken from the csrftoken cookie on a mutating request', () => {
    document.cookie = 'csrftoken=abc123';

    http.post(`${environment.apiBaseUrl}/auth/login/`, {}).subscribe();

    const req = httpMock.expectOne(`${environment.apiBaseUrl}/auth/login/`);
    expect(req.request.headers.get('X-CSRFToken')).toBe('abc123');
    req.flush({});
  });

  it('does not attach the header on a GET request', () => {
    document.cookie = 'csrftoken=abc123';

    http.get(`${environment.apiBaseUrl}/tenants/`).subscribe();

    const req = httpMock.expectOne(`${environment.apiBaseUrl}/tenants/`);
    expect(req.request.headers.has('X-CSRFToken')).toBe(false);
    req.flush([]);
  });

  it('does not attach a header when no csrftoken cookie exists yet', () => {
    http.post(`${environment.apiBaseUrl}/auth/login/`, {}).subscribe();

    const req = httpMock.expectOne(`${environment.apiBaseUrl}/auth/login/`);
    expect(req.request.headers.has('X-CSRFToken')).toBe(false);
    req.flush({});
  });

  it('does not touch requests outside the API base URL', () => {
    document.cookie = 'csrftoken=abc123';

    http.post('https://other-host.example/thing', {}).subscribe();

    const req = httpMock.expectOne('https://other-host.example/thing');
    expect(req.request.headers.has('X-CSRFToken')).toBe(false);
    req.flush({});
  });
});
