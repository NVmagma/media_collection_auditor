"""Send one Arr deletion request with file removal and import exclusion enabled. Do not retry or follow redirects."""
from http.client import HTTPException
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.request import Request

from app.arr_title_transport import ArrTitleUpdate, ArrTitleTransportError


class ArrTitleDelete(ArrTitleUpdate):
    def read(self, title_id):
        if type(title_id) is not int or title_id <= 0:
            raise ValueError('Exact Arr identifier required')
        try:
            return self._request('GET', self._url+'/'+str(title_id), monotonic()+10)
        except ArrTitleTransportError:
            # The normal transport hides status details. Only this specific
            # GET can treat an authenticated 404 as missing. Other failures still block.
            raise

    def read_absence(self, title_id):
        if type(title_id) is not int or title_id <= 0:
            raise ValueError('Exact Arr identifier required')
        self._verify()
        try:
            request = Request(self._url+'/'+str(title_id), method='GET', headers={
                'X-Api-Key':self._token, 'Cache-Control':'no-cache', 'Accept':'application/json'})
            with self._opener.open(request, timeout=10) as response:
                if response.status == 200:
                    return False
                raise ValueError('Unexpected Arr readback')
        except HTTPError as error:
            code=error.code; error.close()
            if code != 404:
                raise ArrTitleTransportError('Arr deletion readback unavailable') from None
            self._verify()
            return True
        except (URLError, HTTPException, OSError, ValueError):
            raise ArrTitleTransportError('Arr deletion readback unavailable') from None

    def delete(self, title_id):
        if self._used or type(title_id) is not int or title_id <= 0:
            raise ArrTitleTransportError('Deletion dispatch already used or invalid; no retry')
        self._used=True
        exclusion='addImportExclusion' if self._service=='radarr' else 'addImportListExclusion'
        self._verify()
        try:
            request=Request(self._url+'/'+str(title_id)+'?deleteFiles=true&'+exclusion+'=true',
                method='DELETE', headers={'X-Api-Key':self._token,'Accept':'application/json'})
            with self._opener.open(request,timeout=10) as response:
                if response.status not in (200,202,204): raise ValueError('Deletion not accepted')
            self._verify()
        except HTTPError as error:
            error.close()
            raise ArrTitleTransportError('Arr deletion outcome unresolved; no retry') from None
        except (URLError, HTTPException, OSError, ValueError, RuntimeError):
            raise ArrTitleTransportError('Arr deletion outcome unresolved; no retry') from None
