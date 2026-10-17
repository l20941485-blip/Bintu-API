import os
print("API_KEY env:", repr(os.getenv("API_KEY")))
print("RAPIDAPI_PROXY_SECRET env:", repr(os.getenv("RAPIDAPI_PROXY_SECRET")))
print("REQUIRE_AUTH env:", repr(os.getenv("REQUIRE_AUTH")))

os.environ.pop('REQUIRE_AUTH', None)
from bintu_api.settings import Settings
from bintu_api.auth import verify_api_access
from fastapi import HTTPException

class FakeRequest:
    headers = {}

s = Settings.from_env()
print('Test 1 - require_auth default:', s.require_auth)
print('Test 1 - api_key:', repr(s.api_key))
print('Test 1 - rapidapi_proxy_secret:', repr(s.rapidapi_proxy_secret))
assert s.require_auth == False

os.environ['REQUIRE_AUTH'] = 'true'
s2 = Settings.from_env()
print('Test 2 - require_auth=true:', s2.require_auth)
print('Test 2 - api_key:', repr(s2.api_key))
print('Test 2 - rapidapi_proxy_secret:', repr(s2.rapidapi_proxy_secret))
assert s2.require_auth == True

try:
    verify_api_access(FakeRequest(), s2)
    print('Test 3 - FAIL: should have raised 500')
except HTTPException as e:
    print('Test 3 - status:', e.status_code, 'code:', e.detail.get('code'))

s3 = Settings(api_key='test-key', rapidapi_proxy_secret='', require_auth=True)
verify_api_access(FakeRequest(), s3)
print('Test 4 - with api_key: passes')

os.environ.pop('REQUIRE_AUTH', None)
s4 = Settings.from_env()
verify_api_access(FakeRequest(), s4)
print('Test 5 - require_auth=False, no secrets: open dev OK')

print('ALL TESTS PASSED')